import os

from buildstream import SourceError

from .git_tag import AbstractGitTagSource, GitTagMirror


class GitModuleSource(AbstractGitTagSource):
    # pylint: disable=attribute-defined-outside-init

    BST_REQUIRES_PREVIOUS_SOURCES_TRACK = True

    def get_extra_unique_key(self):
        key = []

        # Distinguish different submodules that reference the same commit
        if self.path:
            key.append({"path": self.path})
        return key

    def get_extra_config_keys(self):
        return ["path"]

    def extra_configure(self, node):
        ref = node.get_str("ref", None)

        self.path = node.get_str("path", None)
        if os.path.isabs(self.path):
            self.path = os.path.relpath(self.path, "/")
        self.mirror = GitTagMirror(
            self,
            self.path,
            self.original_url,
            ref,
            primary=True,
            full_clone=self.full_clone,
        )

    def track(self, previous_sources_dir):
        # list objects in the parent repo tree to find the commit
        # object that corresponds to the submodule
        _, output = self.check_output(
            [self.host_git, "submodule", "status", self.path],
            fail=f"{self}: Failed to run 'git submodule status {self.path}'",
            cwd=previous_sources_dir,
        )

        fields = output.split()
        commit = fields[0].lstrip("-+")
        if len(commit) != 40:
            raise SourceError(
                f"{self}: Unexpected output from 'git submodule status'"
            )

        return commit

    def get_source_fetchers(self):
        yield self.mirror


def setup():
    return GitModuleSource
