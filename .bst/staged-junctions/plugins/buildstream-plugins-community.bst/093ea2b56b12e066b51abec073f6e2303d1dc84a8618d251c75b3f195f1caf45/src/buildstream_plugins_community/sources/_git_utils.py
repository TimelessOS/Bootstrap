"""
This module contains common helpers for git plugins
==============================================

"""

import fnmatch
import os
import re
import threading


from enum import Enum
from stat import S_ISDIR, S_ISLNK
from urllib.parse import urlparse

from buildstream import SourceFetcher, SourceError
from buildstream.utils import url_directory_name

import dulwich
from dulwich.repo import Repo
from dulwich.objects import Commit, Tag, S_ISGITLINK
from dulwich.client import get_transport_and_path, HTTPUnauthorized
from dulwich.errors import GitProtocolError, NotGitRepository
from dulwich.refs import ANNOTATED_TAG_SUFFIX
from urllib3 import PoolManager, Timeout
from urllib3.exceptions import HTTPError

from ._utils import get_netrc_credentials


REF_REGEX = re.compile(r"(?:(.*)(?:-(\d+)-g))?([0-9a-f]{40})")
SPLITTER_REGEX = re.compile(rb"[a-zA-Z]+|[0-9]+")

CONNECTION_ERRORS = (
    GitProtocolError,
    HTTPUnauthorized,
    NotGitRepository,
    HTTPError,
)


def init_repo(mirror_dir):
    """
    Open a repo at the given mirror_dir, creating an empty bare repo if it doesn't exist.
    """
    try:
        return Repo.init_bare(mirror_dir, mkdir=True)
    except FileExistsError:
        return Repo(mirror_dir, bare=True)


def resolve_mirror_dir(source, url):
    if url.endswith(".git"):
        norm_url = url[:-4]
    else:
        norm_url = url

    return os.path.join(
        source.get_mirror_directory(),
        url_directory_name(norm_url) + ".git",
    )


def collect_objects(mirror, commit, base, trees_only):
    if commit == base:
        commits = {commit}
    elif base is None:
        commits = {entry.commit for entry in mirror.get_walker(commit.id)}
    else:
        excluded = {commit for commit in base.parents if commit in mirror}
        commits = {
            entry.commit for entry in mirror.get_walker(commit.id, excluded)
        }

    # All the tree objects. `git log .` and `git describe --dirty` need them
    trees = set(commit.tree for commit in commits)
    objects = set()

    while trees:
        tree = trees.pop()

        if tree in objects:
            continue
        objects.add(tree)

        for _, mode, sha in mirror[tree].items():
            if S_ISDIR(mode):
                trees.add(sha)
            elif S_ISLNK(mode) or (not trees_only and not S_ISGITLINK(mode)):
                objects.add(sha)

    objects = {mirror[sha] for sha in objects}

    return commits | objects


def stage_repository(mirror, directory, objects, refs, remotes, pack=False):
    object_ids = {obj.id for obj in objects}
    shallow = {
        obj.id
        for obj in objects
        if isinstance(obj, Commit) and not object_ids.issuperset(obj.parents)
    }

    with Repo.init(directory) as dest:
        if pack:
            dest.object_store.add_objects([(obj, None) for obj in objects])
        else:
            for obj in objects:
                dest.object_store.add_object(obj)

        for ref, target in refs.items():
            dest.refs[ref] = target

        dest.update_shallow(shallow, [])

        conf = dest.get_config()
        for remote, url in remotes.items():
            conf.set(("remote", remote), "url", url)
        conf.write_to_path()

    # checkout
    with Repo(directory, object_store=mirror.object_store) as dest:
        dest.reset_index()


def git_describe(repo, revision, remote_refs):
    """
    Returns the equivalent of `git describe --tags --abbrev=40`
    """

    commit_tags = {}

    for ref, sha in remote_refs.items():
        if not ref.startswith(b"refs/tags/"):
            continue

        if sha not in repo:
            continue
        commit = repo.get_object(sha)

        tag = ref[len(b"refs/tags/") :]

        if tag.endswith(ANNOTATED_TAG_SUFFIX):
            tag = tag[: -len(ANNOTATED_TAG_SUFFIX)]

        while isinstance(commit, Tag):
            commit = repo.get_object(commit.object[1])

        commit_tags[commit.id] = tag.decode()

    count = 0

    walker = repo.get_walker([revision.encode()])
    for entry in walker:
        commit_id = entry.commit.id
        if commit_id in commit_tags:
            return f"{commit_tags[commit_id]}-{count}-g{revision}"

        count += 1

    return revision


LOCKS = {}


class RefFormat(Enum):
    SHA1 = "sha1"
    GIT_DESCRIBE = "git-describe"


def make_lock(mirror_dir):
    return LOCKS.setdefault(mirror_dir, threading.Lock())


class GitMirror(SourceFetcher):
    def __init__(self, source, url, ref):
        super().__init__()
        self.mark_download_url(url)

        self.source = source
        self.url = url
        self.ref = ref

        match = REF_REGEX.match(ref)
        assert match is not None
        tag, depth, sha = match.groups()

        self.sha = sha
        self.tagref = f"refs/tags/{tag}".encode() if tag else None
        self.depth = int(depth) + 1 if depth else None
        self.mirror_dir = resolve_mirror_dir(source, url)

    def fetch(self, alias_override=None):
        url = self.source.translate_url(
            self.url, alias_override=alias_override
        )
        lock = make_lock(self.mirror_dir)

        with lock, init_repo(
            self.mirror_dir
        ) as repo, self.source.timed_activity(f"Fetching from {url}"):
            if self.sha.encode() in repo and (
                not self.tagref or self.tagref in repo.refs
            ):
                return

            self.source.status(f"Fetching {self.sha}")

            # Git protocol version 2 allows requesting any object, not necessarily an object
            # pointed to by a ref. Unfortunately, dulwich doesn't support protocol version 2.
            # In practice a lot of version 2 servers accept this even when speaking protocol
            # version 1. We try to take advantage of this by requesting exact refs.
            def exact_want(refs, depth=None):
                wanted = set([self.sha.encode()])
                if not self.tagref:
                    return wanted

                if self.tagref in refs:
                    wanted.add(refs[self.tagref])
                    return wanted

                raise SourceError(
                    f"ref {self.tagref.decode()} not found in remote {url}"
                )

            # Another optimization we can do is to request all the refs that match what we're
            # tracking. This is almost guaranteed to get us what we need without downloading
            # everything.
            def track_want(refs, depth=None):
                wanted_refs = get_matching_refs(
                    refs, self.source.tracking, self.source.exclude
                )

                if self.tagref:
                    wanted_refs.append(self.tagref)

                self.source.status(
                    "fetching tracked refs",
                    detail=b"\n".join(wanted_refs).decode(),
                )
                wanted = {refs[ref] for ref in wanted_refs}
                return wanted

            client, path = get_authenticated_transport_and_path(url)

            try:
                try:
                    remote_refs = client.fetch(
                        path,
                        repo,
                        determine_wants=exact_want,
                        depth=self.depth,
                    )
                except GitProtocolError as e:
                    if "not our ref" not in str(e):
                        raise

                    remote_refs = client.fetch(
                        path, repo, determine_wants=track_want
                    )

                    # Fall back to downloading everything
                    if self.sha.encode() not in repo:
                        remote_refs = client.fetch(path, repo)
            except CONNECTION_ERRORS as e:
                raise SourceError(f"failed to fetch: {e}") from e
            except NotImplementedError as e:
                self.source.warn(f"not implemented {e}")
                if client.dumb:
                    raise SourceError(
                        "Fetching from a dumb repository is not currently supported, "
                        "please set up a mirror on a smart server"
                    ) from e
                raise SourceError(f"failed to fetch: {e}") from e

            # check that we actually pulled the required commit
            if self.sha.encode() not in repo:
                raise SourceError(f"{self.sha} not found in remote {url}")

            if self.tagref:
                repo.refs.add_if_new(self.tagref, remote_refs[self.tagref])

    def stage(self, directory):
        tag, _, sha = REF_REGEX.match(self.ref).groups()
        self.source.status(f"Checking out {sha}")

        with Repo(self.mirror_dir, bare=True) as mirror:
            refs = {b"HEAD": sha.encode()}
            tag_objects = set()

            commit = mirror[sha.encode()]
            base = mirror[sha.encode()]

            if tag:
                tag_ref = f"refs/tags/{tag}".encode()
                tag_target = mirror[tag_ref]
                refs[tag_ref] = tag_target.id

                if isinstance(tag_target, Tag):
                    # Annotated tag
                    tag_objects.add(tag_target)
                    tag_target = mirror[tag_target.object[1]]

                assert isinstance(
                    tag_target, Commit
                ), f"Tag {tag} does not point to a commit (type {type(tag_target)}"

                base = tag_target

            objects = collect_objects(mirror, commit, base, True)
            self.source.status(f"Adding {len(objects)} objects")

            # `|` means union
            stage_repository(
                mirror, directory, tag_objects | objects, refs, {}, pack=False
            )

    def init_workspace(self, directory):
        tag, _, sha = REF_REGEX.match(self.ref).groups()
        self.source.status(f"Checking out {sha}")

        with Repo(self.mirror_dir, bare=True) as mirror:
            refs = {b"HEAD": sha.encode()}
            remotes = {"origin": self.source.translate_url(self.url)}

            commit = mirror[sha.encode()]
            objects = collect_objects(mirror, commit, None, False)

            tag_objects = set()

            for tag, tag_sha in mirror.refs.as_dict(b"refs/tags").items():
                tag_ref = b"refs/tags/" + tag
                tag_target = mirror[tag_sha]
                tag_obj = None

                if isinstance(tag_target, Commit):
                    if tag_target in objects:
                        refs[tag_ref] = tag_target.id

                    continue

                # Annotated tag
                tag_obj = tag_target
                tag_target = mirror[tag_target.object[1]]

                assert isinstance(
                    tag_target, Commit
                ), f"Tag {tag} does not point to a commit (type {type(tag_target)}"

                if tag_target in objects:
                    tag_objects.add(tag_obj)
                    refs[tag_ref] = tag_obj.id

            self.source.status(f"Adding {len(objects)} objects")

            # `|` means union
            stage_repository(
                mirror,
                directory,
                tag_objects | objects,
                refs,
                remotes,
                pack=True,
            )

    def has_ref(self):
        tag, _, sha = REF_REGEX.match(self.ref).groups()

        with Repo(self.mirror_dir, bare=True) as repo:
            cached = sha.encode() in repo
            if tag:
                ref = b"refs/tags/" + tag.encode()
                cached_ref = ref in repo

                cached = cached and cached_ref

        return cached


def version_sort_key(elt):
    """
    A sort key that can be used to versions. It sorts letters before numbers (so 1.beta is earlier
    than 1.0) and disregards separators (so 1.beta, 1~beta and 1beta are the same).
    """
    return [
        # to sort letters before digits
        (-1, part) if part.isalpha() else (int(part), "")
        for part in SPLITTER_REGEX.findall(elt)
    ]


def pattern_to_regex(pattern):
    """
    Transforms a glob pattern into a regex to match refs.

    If the pattern doesn't start with "refs/", it will be considered to only match refs in
    refs/tags/ and refs/heads.
    """
    if pattern.startswith("refs/"):
        return re.compile(fnmatch.translate(pattern).encode())

    return re.compile(
        ("refs/(heads|tags)/" + fnmatch.translate(pattern)).encode()
    )


def get_matching_refs(refs, tracking, exclude):
    real_refs = {ref for ref in refs if not ref.endswith(ANNOTATED_TAG_SUFFIX)}
    matching_regex = pattern_to_regex(tracking)

    matching_refs = [ref for ref in real_refs if matching_regex.match(ref)]

    if exclude:
        exclude_regexs = [pattern_to_regex(pattern) for pattern in exclude]
        matching_refs = [
            ref
            for ref in matching_refs
            if not any(regex.match(ref) for regex in exclude_regexs)
        ]

    return matching_refs


def resolve_ref(source, original_url, tracking, ref_format, exclude):
    mirror_dir = resolve_mirror_dir(source, original_url)
    url = source.translate_url(original_url)
    source.status(f"Tracking {tracking} from {url}")

    client, path = get_authenticated_transport_and_path(url)

    try:
        refs = client.get_refs(path)
    except CONNECTION_ERRORS as exc:
        raise SourceError(f"Failed to track {url}") from exc

    matching_refs = get_matching_refs(refs, tracking, exclude)
    if not matching_refs:
        raise SourceError("No matching refs")

    source.debug(
        "Refs to be tracked", detail=b"\n".join(matching_refs).decode()
    )

    ref = max(matching_refs, key=version_sort_key)

    # peel the ref if possible
    peeled_ref = ref + ANNOTATED_TAG_SUFFIX
    if peeled_ref in refs:
        resolved = refs[peeled_ref]
    else:
        resolved = refs[ref]

    # Use str instead of bytes from here on
    ref = ref.decode()
    resolved = resolved.decode()

    source.status(f"Tracked {ref}: {resolved}")

    if ref_format == RefFormat.SHA1:
        return resolved

    if "tags" in ref:
        tag = ref.split("/", 2)[-1]
        return f"{tag}-0-g{resolved}"

    # Need to fetch to generate the ref in git-describe format
    fetcher = GitMirror(source, original_url, resolved)
    fetcher.fetch()

    with Repo(mirror_dir) as repo:
        return git_describe(repo, resolved, refs)


def get_authenticated_transport_and_path(url):
    credentials = get_netrc_credentials(url)
    if urlparse(url).scheme not in ("http", "https"):
        return get_transport_and_path(url, **credentials)

    timeout = Timeout(connect=30.0, read=10 * 60.0)
    pool_manager = PoolManager(timeout=timeout)
    return get_transport_and_path(
        url, **credentials, pool_manager=pool_manager
    )


def get_full_sha(source, url, short_sha):
    mirror_dir = resolve_mirror_dir(source, url)
    url = source.translate_url(url)
    source.status(f"Tracking {short_sha} from {url}")

    lock = make_lock(mirror_dir)

    with lock, init_repo(mirror_dir) as repo:
        client, path = get_authenticated_transport_and_path(url)
        client.fetch(path, repo)

        for candidate in repo.object_store:
            candidate = candidate.decode()
            if candidate.startswith(short_sha):
                source.status(f"Tracked {short_sha}: {candidate}")
                return candidate

    raise SourceError(f"Failed to find {short_sha} from {url}")


def verify_version():
    required = (0, 21, 7)
    if dulwich.__version__ < required:
        version_string = ".".join(map(str, dulwich.__version__))
        required_string = ".".join(map(str, required))
        raise SourceError(
            "Dulwich version was {} but {} required".format(
                version_string, required_string
            )
        )
