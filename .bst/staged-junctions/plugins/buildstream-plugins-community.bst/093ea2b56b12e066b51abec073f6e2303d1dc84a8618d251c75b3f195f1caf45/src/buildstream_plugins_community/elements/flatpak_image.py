# Copyright (c) 2017 freedesktop-sdk
# Copyright (c) 2018 Codethink Limited
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
#        Valentin David <valentin.david@gmail.com>
#        Thomas Coldrick <thomas.coldrick@codethink.co.uk>


"""Flatpak Image Element

.. _flatpak_image:

A buildstream plugin used to stage its build-dependencies, and metadata
provided by the 'metadata' field in a format useful to generate flatpaks.
"""
import configparser
import os

from buildstream import Element, ElementError


class FlatpakImageElement(Element):

    BST_MIN_VERSION = "2.0"
    BST_STRICT_REBUILD = True
    BST_FORBID_RDEPENDS = True
    BST_FORBID_SOURCES = True

    __layout = {}

    __input = "/buildstream/allfiles"
    __install_root = "/buildstream/install"

    def configure(self, node):
        node.validate_keys(
            [
                "directory",
                "include",
                "exclude",
                "metadata",
                "component-ids",
            ]
        )
        self.directory = self.node_subst_vars(node.get_scalar("directory"))
        self.include = node.get_str_list("include")
        self.exclude = node.get_str_list("exclude")
        self.component_ids = node.get_str_list("component-ids")
        self.metadata = configparser.ConfigParser()
        self.metadata.optionxform = str
        self.metadata_dict = {}
        metadata_node = node.get_mapping("metadata")
        for section, pairs in metadata_node.items():
            section_dict = {}
            for key, value in pairs.items():
                section_dict[key] = self.node_subst_vars(value)
            self.metadata_dict[section] = section_dict

        self.metadata.read_dict(self.metadata_dict)
        if not self.__layout:
            self.__layout = {}

        if self.metadata.has_section("Application"):
            self.component_type = "application"
        elif self.metadata.has_section("Runtime"):
            self.component_type = "runtime"
            if self.metadata.has_section("ExtensionOf"):
                self.component_type = "runtime_extension"
        else:
            raise ElementError(
                "Either Application or Runtime section must be present in metadata"
            )

    def preflight(self):
        pass

    def configure_dependencies(self, dependencies):
        for dependency in dependencies:
            if dependency.config:
                dependency.config.validate_keys(["location"])
                location = dependency.config.get_str("location")
            else:
                location = self.__input
            self.__layout.setdefault(location, []).append(dependency.element)

    def get_unique_key(self):
        key = {}
        key["directory"] = self.directory
        key["include"] = sorted(self.include)
        key["exclude"] = sorted(self.exclude)
        key["metadata"] = self.metadata_dict
        if self.component_ids:
            key["component-ids"] = self.component_ids
        key["version"] = 4  # Used to force rebuilds after editing the plugin
        return key

    def configure_sandbox(self, sandbox):
        # Setup the environment and work directory
        sandbox.set_work_directory("/")

        # Setup environment
        sandbox.set_environment(self.get_environment())

        # Mark writable directories
        sandbox.mark_directory(self.__input)
        sandbox.mark_directory(self.__install_root)

    def stage(self, sandbox):
        for location in sorted(self.__layout):
            with self.timed_activity(
                "Staging dependencies at: {}".format(location),
                silent_nested=True,
            ):
                if location == self.__input:
                    include = self.include
                    exclude = self.exclude
                else:
                    include = None
                    exclude = None
                self.stage_dependency_artifacts(
                    sandbox,
                    self.__layout[location],
                    path=location,
                    include=include,
                    exclude=exclude,
                )

    def assemble(self, sandbox):
        self._appstream_compose(sandbox)

        basedir = sandbox.get_virtual_directory()
        allfiles = basedir.open_directory(
            self.__input.lstrip("/"), create=True
        )
        reldirectory = os.path.relpath(self.directory, "/")
        installdir = basedir.open_directory(
            self.__install_root.lstrip("/"), create=True
        )
        filesdir = installdir.open_directory("files", create=True)
        if self.component_type == "application":
            installdir.open_directory("export", create=True)

        for section in self.metadata.sections():
            if section.startswith("Extension "):
                extensiondir = self.metadata.get(section, "directory")
                installdir.open_directory(
                    os.path.join("files", extensiondir),
                    create=True,
                )

        if allfiles.exists(reldirectory):
            subdir = allfiles.open_directory(reldirectory)
            filesdir.import_files(subdir)
        if allfiles.exists("etc") and self.component_type == "runtime":
            etcdir = allfiles.open_directory("etc")
            filesetcdir = filesdir.open_directory("etc", create=True)
            filesetcdir.import_files(etcdir)

        with installdir.open_file("metadata", mode="w") as m:
            self.metadata.write(m)

        return self.__install_root

    def _appstream_compose(self, sandbox):
        if not self.component_ids:
            return
        with sandbox.batch(root_read_only=True, collect=self.__install_root):
            for component_id in self.component_ids:
                cmd = " ".join(
                    [
                        "appstreamcli",
                        "compose",
                        "--components",
                        component_id,
                        "--result-root",
                        self.__install_root,
                        "--prefix",
                        self.directory,
                        "--data-dir",
                        os.path.join(
                            self.__input, self.directory.lstrip("/"), "share"
                        ),
                        "--origin",
                        component_id,
                        self.__input,
                    ]
                )
            sandbox.run(
                ["sh", "-c", "-e", cmd + "\n"],
                root_read_only=True,
                label=cmd,
            )


def setup():
    return FlatpakImageElement
