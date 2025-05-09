# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import subprocess
import pytest

from buildstream._testing import Repo
from buildstream import utils, ProgramNotFoundError

try:
    OSTREE_CLI = utils.get_host_tool("ostree")
    HAVE_OSTREE_CLI = True
except ProgramNotFoundError:
    HAVE_OSTREE_CLI = False


class OSTree(Repo):
    def __init__(self, directory, subdir):
        if not HAVE_OSTREE_CLI:
            pytest.skip("ostree cli is not available")

        super().__init__(directory, subdir)
        self.ostree = OSTREE_CLI

    def create(self, directory, *, gpg_sign=None, gpg_homedir=None):
        subprocess.call(
            [self.ostree, "init", "--repo", self.repo, "--mode", "archive-z2"]
        )

        commit_args = [
            self.ostree,
            "commit",
            "--repo",
            self.repo,
            "--branch",
            "master",
            "--subject",
            "Initial commit",
        ]

        if gpg_sign and gpg_homedir:
            commit_args += [
                "--gpg-sign={}".format(gpg_sign),
                "--gpg-homedir={}".format(gpg_homedir),
            ]

        commit_args += [directory]

        subprocess.call(commit_args)

        latest = self.latest_commit()

        return latest

    def source_config(self, ref=None, *, gpg_key=None):
        config = {
            "kind": "ostree",
            "url": "file://" + self.repo,
            "track": "master",
        }
        if ref is not None:
            config["ref"] = ref
        if gpg_key is not None:
            config["gpg-key"] = gpg_key

        return config

    def latest_commit(self):
        return subprocess.check_output(
            [self.ostree, "rev-parse", "--repo", self.repo, "master"],
            universal_newlines=True,
        ).strip()
