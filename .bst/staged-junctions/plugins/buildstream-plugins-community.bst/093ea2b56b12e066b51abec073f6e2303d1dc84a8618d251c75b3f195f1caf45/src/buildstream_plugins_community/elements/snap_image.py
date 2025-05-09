#
#  Copyright (C) 2018, 2019 Codethink Limited
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
from ruamel.yaml import YAML
from buildstream import Element


class SnapImageElement(Element):

    BST_MIN_VERSION = "2.0"
    BST_FORBID_RDEPENDS = True
    BST_FORBID_SOURCES = True
    BST_ARTIFACT_VERSION = 1

    def configure(self, node):
        node.validate_keys(
            ["directory", "include", "exclude", "metadata", "include-orphans"]
        )
        self.directory = node.get_str("directory")
        self.include = node.get_str_list("include")
        self.exclude = node.get_str_list("exclude")
        self.include_orphans = node.get_bool("include-orphans")
        self.metadata = node.get_node("metadata").strip_node_info()

    def preflight(self):
        pass

    def get_unique_key(self):
        key = {}
        key["directory"] = self.directory
        key["include"] = sorted(self.include)
        key["exclude"] = sorted(self.exclude)
        key["include-orphans"] = self.include_orphans
        key["metadata"] = self.metadata
        return key

    def configure_sandbox(self, sandbox):
        pass

    def stage(self, sandbox):
        with self.timed_activity("Staging dependencies", silent_nested=True):
            self.stage_dependency_artifacts(
                sandbox,
                include=self.include,
                exclude=self.exclude,
                orphans=self.include_orphans,
            )

    def assemble(self, sandbox):

        with self.timed_activity("Creating snap image", silent_nested=True):
            reldirectory_path = os.path.relpath(self.directory, os.sep)
            metadir_path = os.path.join(reldirectory_path, "meta")
            metadata_filename = "snap.yaml"

            basedir = sandbox.get_virtual_directory()
            metadir = basedir.open_directory(
                metadir_path.lstrip(os.path.sep), create=True
            )

            yaml = YAML(typ="unsafe", pure=True)
            with metadir.open_file(metadata_filename, mode="w") as file:
                yaml.dump(self.metadata, file)

        return os.path.join(os.sep, reldirectory_path)


def setup():
    return SnapImageElement
