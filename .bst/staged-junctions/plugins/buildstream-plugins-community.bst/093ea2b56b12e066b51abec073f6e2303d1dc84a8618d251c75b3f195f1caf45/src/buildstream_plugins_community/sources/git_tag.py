#
#  Copyright (C) 2016 Codethink Limited
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors:
#        Tristan Van Berkom <tristan.vanberkom@codethink.co.uk>

# Copyright (c) 2018 freedesktop-sdk
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Authors:
#        Thomas Coldrick <thomas.coldrick@codethink.co.uk>


"""
git-tag - extension of BuildStream git plugin to track latest tag
=================================================================

**Host dependencies**

  * git

**Usage:**

.. code:: yaml

   # Specify the git_tag source kind
   kind: git_tag

   # Optionally specify a relative staging directory
   # directory: path/to/stage

   # Specify the repository url, using an alias defined
   # in your project configuration is recommended
   url: upstream:foo.git

   # Optionally specify a symbolic tracking branch or tag, this
   # will be used to update the 'ref' when refreshing the pipeline.
   track: master

   # Optionally specify an additional list of symbolic tracking branches,
   # this will be used to update the 'ref' when refreshing the pipeline
   # n.b. Tracks to the latest overall commit on any of the branches
   track-extra:
   - foo
   - bar

   # Optionally specify to track the latest tag of a branch,
   # rather than the latest commit when updating 'ref'.
   # If not set, this will default to 'False'
   track-tags: False

   # Optionally match the tracked tag to a list of glob patterns
   # NOTE: This does nothing if the 'track-tags' attribute is
   # not set to True
   match:

   # Optionally exclude a list of glob patterns from tracked tags
   # NOTE: This does nothing if the 'track-tags' attribute is
   # not set to True
   exclude:

   # Specify the commit ref, this must be specified in order to
   # checkout sources and build, but can be automatically updated
   # if the 'track' attribute was specified.
   ref: d63cbb6fdc0bbdadc4a1b92284826a6d63a7ebcd

   # Optionally specify whether submodules should be checked-out.
   # If not set, this will default to 'True'
   checkout-submodules: True

   # Optionally specify whether or not to clone Git LFS objects
   use-lfs: False

   # If your repository has submodules, explicitly specifying the
   # url from which they are to be fetched allows you to easily
   # rebuild the same sources from a different location. This is
   # especially handy when used with project defined aliases which
   # can be redefined at a later time.
   # You may also explicitly specify whether to check out this
   # submodule. If checkout is set, it will override
   # 'checkout-submodules' with the value set below.
   submodules:
     plugins/bar:
       url: upstream:bar.git
       checkout: True
     plugins/baz:
       url: upstream:baz.git
       checkout: False

   # Fetch a full clone instead of a shallow clone.
   full-clone: False

**Configurable Warnings:**

This plugin provides the following `configurable warnings
<https://docs.buildstream.build/master/format_project.html#configurable-warnings>`:

- ``git:unused-lfs`` - There are files with Git LFS attributes but 'use-lfs' is not explicitly set.

"""

import os
import errno
import re
from io import StringIO
from urllib.parse import urljoin

from configparser import RawConfigParser

from buildstream import Source, SourceError, SourceFetcher
from buildstream import utils

GIT_MODULES = ".gitmodules"
GIT_ATTRIBUTES = ".gitattributes"

# Warnings
WARN_UNUSED_GITLFS = "unused-lfs"

# Because of handling of submodules, we maintain a GitMirror
# for the primary git source and also for each submodule it
# might have at a given time
#
class GitTagMirror(SourceFetcher):
    def __init__(
        self, source, path, url, ref, *, primary=False, full_clone=False
    ):

        super().__init__()
        self.source = source
        self.path = path
        self.url = url
        self.primary = primary
        self.mirror = os.path.join(
            source.get_mirror_directory(), utils.url_directory_name(url)
        )

        self.mark_download_url(url)
        self.full_clone = full_clone
        self.set_ref(ref)

    def set_ref(self, ref):
        self.ref = ref
        if ref is None:
            self.fetch_mirror = None
        else:
            ref_dirname = utils.url_directory_name(
                "{}#{}".format(self.url, ref)
            )
            self.fetch_mirror = os.path.join(
                self.source.get_mirror_directory(), ref_dirname
            )

    def mirror_path(self):
        if os.path.exists(self.mirror):
            return self.mirror
        else:
            assert os.path.exists(self.fetch_mirror)
            return self.fetch_mirror

    def ensure_fetchable(self, alias_override=None):

        if os.path.exists(self.mirror):
            return

        if os.path.exists(self.fetch_mirror):
            return

        if self.full_clone:
            self.source.status("{}: Full clone requested".format(self.source))
            self.ensure_trackable(alias_override=alias_override)
            return

        m = re.match(r"(?P<tag>.*)-0-g(?P<commit>.*)", self.ref)
        if not m:
            self.source.status(
                "{}: Not fetching exact tag. Getting full clone.".format(
                    self.source
                )
            )
            self.ensure_trackable(alias_override=alias_override)
            return

        tag = m.group("tag")
        commit = m.group("commit")

        with self.source.tempdir() as tmpdir:
            self.source.call(
                [self.source.host_git, "init", "--bare", tmpdir],
                fail="Failed to init git repository",
                fail_temporarily=True,
            )

            url = self.source.translate_url(
                self.url, alias_override=alias_override, primary=self.primary
            )

            self.source.call(
                [
                    self.source.host_git,
                    "remote",
                    "add",
                    "--mirror=fetch",
                    "origin",
                    url,
                ],
                cwd=tmpdir,
                fail="Failed to init git repository",
                fail_temporarily=True,
            )

            _, refs = self.source.check_output(
                [self.source.host_git, "ls-remote", "origin"],
                cwd=tmpdir,
                fail="Failed to list advertised remote refs from git repository {}".format(
                    url
                ),
                fail_temporarily=True,
            )

            advertised = False

            for ref_line in refs.splitlines():
                ad_commit, ad_ref = ref_line.split("\t", 1)
                if ad_commit == commit:
                    if ad_ref in [
                        "refs/tags/{tag}^{{}}".format(tag=tag),
                        "refs/tags/{tag}".format(tag=tag),
                    ]:
                        advertised = True
                        break

            if not advertised:
                self.source.status(
                    "{}: {} is not advertised on {}, so a full clone is required".format(
                        self.source, self.ref, url
                    )
                )

                self.ensure_trackable(alias_override=alias_override)
                return

            exit_code = self.source.call(
                [self.source.host_git, "fetch", "--depth=1", "origin", tag],
                cwd=tmpdir,
            )
            if exit_code != 0:
                self.source.status(
                    "{}: Failed to shallow clone from {}. Probably dumb HTTP server. Trying full clone.".format(
                        self.source, url
                    )
                )

                self.ensure_trackable(alias_override=alias_override)
                return

            # We need to have a ref to make it clonable
            self.source.call(
                [
                    self.source.host_git,
                    "update-ref",
                    "HEAD",
                    "{commit}^{{}}".format(commit=commit),
                ],
                cwd=tmpdir,
                fail="Failed to tag HEAD",
                fail_temporarily=True,
            )

            try:
                os.rename(tmpdir, self.fetch_mirror)
            except OSError as e:
                if e.errno in (errno.ENOTEMPTY, errno.EEXIST):
                    self.source.status(
                        "{}: Discarding duplicate clone of {}".format(
                            self.source, url
                        )
                    )
                else:
                    raise SourceError(
                        "{}: Failed to move cloned git repository {} from '{}' to '{}': {}".format(
                            self.source, url, tmpdir, self.fetch_mirror, e
                        )
                    ) from e

    # Ensures that the mirror exists
    def ensure_trackable(self, alias_override=None):

        # Unfortunately, git does not know how to only clone just a specific ref,
        # so we have to download all of those gigs even if we only need a couple
        # of bytes.
        if not os.path.exists(self.mirror):

            # Do the initial clone in a tmpdir just because we want an atomic move
            # after a long standing clone which could fail overtime, for now do
            # this directly in our git directory, eliminating the chances that the
            # system configured tmpdir is not on the same partition.
            #
            with self.source.tempdir() as tmpdir:
                url = self.source.translate_url(
                    self.url,
                    alias_override=alias_override,
                    primary=self.primary,
                )
                self.source.call(
                    [
                        self.source.host_git,
                        "clone",
                        "--mirror",
                        "-n",
                        url,
                        tmpdir,
                    ],
                    fail="Failed to clone git repository {}".format(url),
                    fail_temporarily=True,
                )

                # Attempt atomic rename into destination, this will fail if
                # another process beat us to the punch
                try:
                    os.rename(tmpdir, self.mirror)
                except OSError as e:

                    # When renaming and the destination repo already exists, os.rename()
                    # will fail with ENOTEMPTY or EEXIST, since an empty directory will
                    # be silently replaced
                    if e.errno in (errno.ENOTEMPTY, errno.EEXIST):
                        self.source.status(
                            "{}: Discarding duplicate clone of {}".format(
                                self.source, url
                            )
                        )
                    else:
                        raise SourceError(
                            "{}: Failed to move cloned git repository {} from '{}' to '{}': {}".format(
                                self.source, url, tmpdir, self.mirror, e
                            )
                        ) from e

    def _fetch(self, alias_override=None):
        url = self.source.translate_url(
            self.url, alias_override=alias_override, primary=self.primary
        )

        self.source.call(
            [
                self.source.host_git,
                "fetch",
                "--prune",
                url,
                "--tags",
                "--force",
            ],
            fail="Failed to fetch from remote git repository: {}".format(url),
            fail_temporarily=True,
            cwd=self.mirror,
        )

    def fetch(self, alias_override=None):
        # Resolve the URL for the message
        resolved_url = self.source.translate_url(
            self.url, alias_override=alias_override, primary=self.primary
        )

        with self.source.timed_activity(
            "Fetching from {}".format(resolved_url), silent_nested=True
        ):
            self.ensure_fetchable(alias_override)
            if not self.has_ref():
                self._fetch(alias_override)
            self.assert_ref()

    def has_ref(self):
        if not self.ref:
            return False

        # If the mirror doesnt exist, we also dont have the ref
        if not os.path.exists(self.mirror) and not os.path.exists(
            self.fetch_mirror
        ):
            return False

        mirror = self.mirror_path()

        # Check if the ref is really there
        rc = self.source.call(
            [self.source.host_git, "cat-file", "-t", self.ref], cwd=mirror
        )
        if not rc == 0:
            return False

        ## This tries to test if git-lfs is used in this repo and if it is then mandates that you have set
        ## whether or not to use git-lfs with the use-lfs option.
        showrc, attrs = self.source.check_output(
            [
                self.source.host_git,
                "show",
                "{}:{}".format(self.ref, GIT_ATTRIBUTES),
            ],
            cwd=mirror,
        )
        if (
            showrc == 0
            and (
                "filter=lfs" in attrs
                or "diff=lfs" in attrs
                or "merge=lfs" in attrs
            )
            and (self.source.use_lfs is None)
        ):
            self.source.warn(
                "{}: Git LFS not configured but LFS objects exist".format(
                    self.source
                ),
                detail="a filter, diff or merge is set to use lfs in {}".format(
                    GIT_ATTRIBUTES
                ),
                warning_token=WARN_UNUSED_GITLFS,
            )
        return rc == 0

    def assert_ref(self):
        if not self.has_ref():
            raise SourceError(
                "{}: expected ref '{}' was not found in git repository: '{}'".format(
                    self.source, self.ref, self.url
                )
            )

    def latest_commit(self, tracking, *, track_tags, track_args):
        if track_tags:
            exit_code, output = self.source.check_output(
                [self.source.host_git, "describe", "--tags", "--abbrev=0"]
                + track_args
                + [tracking],
                cwd=self.mirror,
            )

            if exit_code == 128:
                self.source.info(
                    "Unable to find tag for specified branch name '{}'".format(
                        tracking
                    )
                )
                return None, None
            tracking = output.rstrip("\n")

        else:
            _, output = self.source.check_output(
                [self.source.host_git, "rev-parse", tracking],
                fail="Unable to find commit for specified branch name '{}'".format(
                    tracking
                ),
                cwd=self.mirror,
            )

        ref = output.rstrip("\n")

        # Prefix the ref with the closest annotated tag, if available,
        # to make the ref human readable
        exit_code, output = self.source.check_output(
            [
                self.source.host_git,
                "describe",
                "--tags",
                "--abbrev=40",
                "--long",
            ]
            + track_args
            + [ref],
            cwd=self.mirror,
        )
        if exit_code == 0:
            ref = output.rstrip("\n")

        # Find the time of the commit to avoid stepping onto an older tag
        # on a different branch
        _, time = self.source.check_output(
            [self.source.host_git, "show", "-s", "--format=%ct", ref],
            cwd=self.mirror,
        )

        return ref, time

    def stage(self, directory):
        fullpath = os.path.join(directory, self.path)

        mirror = self.mirror_path()

        # We need to pass '--no-hardlinks' because there's nothing to
        # stop the build from overwriting the files in the .git directory
        # inside the sandbox.
        self.source.call(
            [
                self.source.host_git,
                "clone",
                "--no-checkout",
                "--no-hardlinks",
                mirror,
                fullpath,
            ],
            fail="Failed to create git mirror {} in directory: {}".format(
                mirror, fullpath
            ),
            fail_temporarily=True,
        )

        if self.source.use_lfs:
            self.set_origin_url(directory)

        ## This turns git-lfs off if it is installed but we dont want to use it.
        my_env = os.environ.copy()
        if not self.source.use_lfs:
            my_env["GIT_LFS_SKIP_SMUDGE"] = "TRUE"

        self.source.call(
            [self.source.host_git, "checkout", "--force", self.ref],
            fail="Failed to checkout git ref {}".format(self.ref),
            env=my_env,
            cwd=fullpath,
        )

    def init_workspace(self, directory):
        fullpath = os.path.join(directory, self.path)
        url = self.source.translate_url(self.url, primary=self.primary)

        self.source.call(
            [
                self.source.host_git,
                "clone",
                "--no-checkout",
                self.mirror,
                fullpath,
            ],
            fail="Failed to clone git mirror {} in directory: {}".format(
                self.mirror, fullpath
            ),
            fail_temporarily=True,
        )

        self.source.call(
            [self.source.host_git, "remote", "set-url", "origin", url],
            fail='Failed to add remote origin "{}"'.format(url),
            cwd=fullpath,
        )

        ## This turns git-lfs off if it is installed but we dont want to use it.
        my_env = os.environ.copy()
        if not self.source.use_lfs:
            my_env["GIT_LFS_SKIP_SMUDGE"] = "TRUE"
        self.source.call(
            [self.source.host_git, "checkout", "--force", self.ref],
            fail="Failed to checkout git ref {}".format(self.ref),
            env=my_env,
            cwd=fullpath,
        )

    # List the submodules (path/url tuples) present at the given ref of this repo
    def submodule_list(self):
        mirror = self.mirror_path()

        modules = "{}:{}".format(self.ref, GIT_MODULES)
        exit_code, output = self.source.check_output(
            [self.source.host_git, "show", modules], cwd=mirror
        )

        # If git show reports error code 128 here, we take it to mean there is
        # no .gitmodules file to display for the given revision.
        if exit_code == 128:
            return
        elif exit_code != 0:
            raise SourceError(
                "{plugin}: Failed to show gitmodules at ref {ref}".format(
                    plugin=self, ref=self.ref
                )
            )

        content = "\n".join([l.strip() for l in output.splitlines()])

        io = StringIO(content)
        parser = RawConfigParser()
        parser.read_file(io)

        for section in parser.sections():
            # validate section name against the 'submodule "foo"' pattern
            if re.match(r'submodule "(.*)"', section):
                path = parser.get(section, "path")
                url = parser.get(section, "url")

                yield (path, url)

    # Fetch the ref which this mirror requires its submodule to have,
    # at the given ref of this mirror.
    def submodule_ref(self, submodule, ref=None):
        if not ref:
            ref = self.ref

        mirror = self.mirror_path()

        # list objects in the parent repo tree to find the commit
        # object that corresponds to the submodule
        _, output = self.source.check_output(
            [self.source.host_git, "ls-tree", ref, submodule],
            fail="ls-tree failed for commit {} and submodule: {}".format(
                ref, submodule
            ),
            cwd=mirror,
        )

        # read the commit hash from the output
        fields = output.split()
        if len(fields) >= 2 and fields[1] == "commit":
            submodule_commit = output.split()[2]

            # fail if the commit hash is invalid
            if len(submodule_commit) != 40:
                raise SourceError(
                    "{}: Error reading commit information for submodule '{}'".format(
                        self.source, submodule
                    )
                )

            return submodule_commit

        else:
            detail = (
                "The submodule '{}' is defined either in the BuildStream source\n".format(
                    submodule
                )
                + "definition, or in a .gitmodules file. But the submodule was never added to the\n"
                + "underlying git repository with `git submodule add`."
            )

            self.source.warn(
                "{}: Ignoring inconsistent submodule '{}'".format(
                    self.source, submodule
                ),
                detail=detail,
            )

            return None

    # Git-lfs can not retrieve objects from a file based directory, it needs something like github or gitlab
    # to serve them. This function can be used when gitlfs is requested to set the checkout repo to point to
    # the original url rather than the mirror when it is about to do the full checkout.
    # This happens after the --no-checkout clone so that as little is pulled from the remote as posible.
    def set_origin_url(self, directory):
        fullpath = os.path.join(directory, self.path)
        _, origin_url = self.source.check_output(
            [self.source.host_git, "config", "--get", "remote.origin.url"],
            fail='Failed to get origin url "{}"'.format(self.mirror),
            cwd=self.mirror,
        )
        self.source.call(
            [self.source.host_git, "config", "remote.origin.url", origin_url],
            fail="Failed to set origin url {}".format(origin_url),
            cwd=fullpath,
        )


class AbstractGitTagSource(Source):
    # pylint: disable=attribute-defined-outside-init

    BST_MIN_VERSION = "2.0"

    def configure(self, node):
        self.mirror = None

        config_keys = [
            "url",
            "ref",
            "full-clone",
            "use-lfs",
        ]
        config_keys.extend(self.get_extra_config_keys())
        config_keys.extend(Source.COMMON_CONFIG_KEYS)
        node.validate_keys(config_keys)

        self.original_url = node.get_str("url")
        self.full_clone = node.get_bool("full-clone", False)

        if "use-lfs" in node.keys():
            self.use_lfs = node.get_bool("use-lfs", False)
        else:
            self.use_lfs = None

        self.extra_configure(node)

        self.mark_download_url(self.original_url)

    def extra_configure(self, node):
        pass

    def get_extra_config_keys(self):
        return []

    def preflight(self):
        # Check if git is installed, get the binary at the same time
        self.host_git = utils.get_host_tool("git")
        if self.use_lfs:
            self.call(
                [self.host_git, "lfs", "--version"],
                fail="Git lfs not installed",
            )

    def get_unique_key(self):
        # Here we want to encode the local name of the repository and
        # the ref, if the user changes the alias to fetch the same sources
        # from another location, it should not effect the cache key.
        key = [self.original_url, self.mirror.ref]

        key.extend(self.get_extra_unique_key())

        if self.use_lfs:
            key.append("use-lfs")

        return key

    def get_extra_unique_key(self):
        return []

    def is_cached(self):
        return self.have_all_refs()

    def load_ref(self, node):
        ref = node.get_str("ref", None)
        self.mirror.set_ref(ref)

    def get_ref(self):
        return self.mirror.ref

    def set_ref(self, ref, node):
        self.mirror.set_ref(ref)
        node["ref"] = ref

    def init_workspace(self, directory):
        # XXX: may wish to refactor this as some code dupe with stage()
        self.mirror.ensure_trackable()

        with self.timed_activity(
            'Setting up workspace "{}"'.format(directory), silent_nested=True
        ):
            self.mirror.init_workspace(directory)
            self.extra_init_workspace(directory)

    def extra_init_workspace(self, directory):
        pass

    def stage(self, directory):
        # Stage the main repo in the specified directory
        #
        with self.timed_activity(
            "Staging {}".format(self.mirror.url), silent_nested=True
        ):
            self.mirror.stage(directory)
            self.extra_stage(directory)

    def extra_stage(self, directory):
        pass

    ###########################################################
    #                     Local Functions                     #
    ###########################################################
    def have_all_refs(self):
        if not self.mirror.has_ref():
            return False

        return self.have_all_extra_refs()

    def have_all_extra_refs(self):
        return True


class GitTagSource(AbstractGitTagSource):
    # pylint: disable=attribute-defined-outside-init
    BST_EXPORT_MANIFEST = True

    def get_extra_config_keys(self):
        return [
            "track",
            "track-extra",
            "track-tags",
            "match",
            "exclude",
            "checkout-submodules",
            "submodules",
        ]

    def extra_configure(self, node):
        ref = node.get_str("ref", None)

        self.mirror = GitTagMirror(
            self,
            "",
            self.original_url,
            ref,
            primary=True,
            full_clone=self.full_clone,
        )
        self.tracking = node.get_str("track", None)
        # FIXME: check if get_sequence would not be better
        self.track_extra = node.get_str_list("track-extra", default=[])
        self.track_tags = node.get_bool("track-tags", False)
        # FIXME: check if get_sequence would not be better
        self.match = node.get_str_list("match", [])
        # FIXME: check if get_sequence would not be better
        self.exclude = node.get_str_list("exclude", [])

        # At this point we now know if the source has a ref and/or a track.
        # If it is missing both then we will be unable to track or build.
        if self.mirror.ref is None and self.tracking is None:
            raise SourceError(
                "{}: Git sources require a ref and/or track".format(self),
                reason="missing-track-and-ref",
            )

        self.checkout_submodules = node.get_bool("checkout-submodules", True)
        self.submodules = []

        # Parse a dict of submodule overrides, stored in the submodule_overrides
        # and submodule_checkout_overrides dictionaries.
        self.submodule_overrides = {}
        self.submodule_checkout_overrides = {}
        modules = node.get_mapping("submodules", {})
        for path in modules.keys():
            submodule = modules.get_mapping(path)
            url = submodule.get_str("url", None)

            # Make sure to mark all URLs that are specified in the configuration
            if url:
                self.mark_download_url(url, primary=False)

            self.submodule_overrides[path] = url
            if "checkout" in submodule:
                checkout = submodule.get_bool("checkout")
                self.submodule_checkout_overrides[path] = checkout

    def get_extra_unique_key(self):
        key = []

        # Only modify the cache key with checkout_submodules if it's something
        # other than the default behaviour.
        if self.checkout_submodules is False:
            key.append({"checkout_submodules": self.checkout_submodules})

        # We want the cache key to change if the source was
        # configured differently, and submodules count.
        if self.submodule_overrides:
            key.append(self.submodule_overrides)

        if self.submodule_checkout_overrides:
            key.append(
                {
                    "submodule_checkout_overrides": self.submodule_checkout_overrides
                }
            )

        return key

    def extra_init_workspace(self, directory):
        self.refresh_submodules()

        for mirror in self.submodules:
            mirror.init_workspace(directory)

    def extra_stage(self, directory):
        # Need to refresh submodule list here again, because
        # it's possible that we did not load in the main process
        # with submodules present (source needed fetching) and
        # we may not know about the submodule yet come time to build.
        #
        self.refresh_submodules()

        # Stage the main repo in the specified directory
        #
        for mirror in self.submodules:
            mirror.stage(directory)

    def track(self):

        # If self.tracking is not specified it's not an error, just silently return
        if not self.tracking:
            return None

        # Resolve the URL for the message
        resolved_url = self.translate_url(self.mirror.url)
        with self.timed_activity(
            "Tracking {} from {}".format(self.tracking, resolved_url),
            silent_nested=True,
        ):
            self.mirror.ensure_trackable()
            self.mirror._fetch()

            track_args = []
            for pattern in self.match:
                track_args.append("--match={}".format(pattern))
            for pattern in self.exclude:
                track_args.append("--exclude={}".format(pattern))

            branches = [self.tracking] + self.track_extra

            # Find new candidate refs from self.tracking branches
            #
            # As we are constructing a dict from the returned tuples of a
            # function, so directly constructing with dict() is nicer than dict
            # comprehension
            # pylint: disable=consider-using-dict-comprehension
            candidates = dict(
                [
                    self.mirror.latest_commit(
                        branch,
                        track_tags=self.track_tags,
                        track_args=track_args,
                    )
                    for branch in branches
                ]
            )

            candidates.pop(None, None)

            # Find latest candidate ref from all branches
            # Update self.mirror.ref, node.ref
            ret = max(candidates, key=candidates.get, default=None)

        return ret

    # Refreshes the GitTagMirror objects for submodules
    #
    # Assumes that we have our mirror and we have the ref which we point to
    #
    def refresh_submodules(self):
        self.mirror.ensure_fetchable()
        submodules = []

        # XXX Here we should issue a warning if either:
        #   A.) A submodule exists but is not defined in the element configuration
        #   B.) The element configuration configures submodules which dont exist at the current ref
        #
        for path, url in self.mirror.submodule_list():

            # Completely ignore submodules which are disabled for checkout
            if self.ignore_submodule(path):
                continue

            # Allow configuration to override the upstream
            # location of the submodules.
            override_url = self.submodule_overrides.get(path)
            if override_url:
                url = override_url

            ref = self.mirror.submodule_ref(path)
            if ref is not None:
                if url.startswith("./") or url.startswith("../"):
                    url = urljoin("{}/".format(self.mirror.url), url)
                mirror = GitTagMirror(self, path, url, ref)
                submodules.append(mirror)

        self.submodules = submodules

    # Checks whether the plugin configuration has explicitly
    # configured this submodule to be ignored
    def ignore_submodule(self, path):
        try:
            checkout = self.submodule_checkout_overrides[path]
        except KeyError:
            checkout = self.checkout_submodules
        return not checkout

    def get_source_fetchers(self):
        yield self.mirror
        self.refresh_submodules()
        yield from self.submodules

    def have_all_extra_refs(self):
        self.refresh_submodules()
        for mirror in self.submodules:
            if not os.path.exists(mirror.mirror) and not os.path.exists(
                mirror.fetch_mirror
            ):
                return False
            if not mirror.has_ref():
                return False

        return True

    def export_manifest(self):
        url = self.translate_url(
            self.mirror.url,
            alias_override=None,
            primary=False,
        )
        return {
            "type": "git",
            "url": url,
            "commit": self.mirror.ref,
        }


# Plugin entry point
def setup():
    return GitTagSource
