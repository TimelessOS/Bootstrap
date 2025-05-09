#
#  Copyright (C) 2021 Codethink Limited
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
#         Valentin David <valentin.david@codethink.co.uk>

import os
from buildstream import Source, utils


class PatchQueueSource(Source):
    BST_MIN_VERSION = "2.0"
    BST_REQUIRES_PREVIOUS_SOURCES_STAGE = True
    BST_EXPORT_MANIFEST = True

    def configure(self, node):
        node.validate_keys(Source.COMMON_CONFIG_KEYS + ["path", "strip"])
        self.path = self.node_get_project_path(
            node.get_scalar("path"), check_is_dir=True
        )
        self.fullpath = os.path.join(self.get_project_directory(), self.path)

    def preflight(self):
        self.host_git = utils.get_host_tool("git")

    def __get_patches(self):
        for p in sorted(os.listdir(self.fullpath)):
            yield os.path.join(self.fullpath, p)

    def get_unique_key(self):
        return [utils.sha256sum(p) for p in self.__get_patches()]

    def is_resolved(self):
        return True

    def is_cached(self):
        return True

    def load_ref(self, node):
        pass

    def get_ref(self):
        return None

    def set_ref(self, ref, node):
        pass

    def fetch(self):
        pass

    def stage(self, directory):
        with self.timed_activity("Applying patch queue: {}".format(self.path)):
            for patch in self.__get_patches():
                self.call(
                    [
                        self.host_git,
                        "-C",
                        directory,
                        "--git-dir",
                        os.path.join(directory, ".git"),
                        "--work-tree",
                        directory,
                        "apply",
                        patch,
                    ],
                    fail="Failed to apply patches from {}".format(self.path),
                )

    def export_manifest(self):
        return {
            "type": "patch",
            "path": self.path,
        }


def setup():
    return PatchQueueSource
