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
#        Valentin David <valentin.david@gmail.com>


"""Collect Integration Element

A buildstream plugin used to collect the integration
commands of all its dependencies, and compose them
into a single shell script.

Used to generate freedesktop-post.sh
"""
import os
import stat
from buildstream import Element, ElementError


class ExtractIntegrationElement(Element):
    BST_MIN_VERSION = "2.0"
    BST_FORBID_RDEPENDS = True

    def configure(self, node):
        node.validate_keys(["script-path", "ignore"])

        self.script_path = self.node_subst_vars(node.get_scalar("script-path"))
        self.ignore = node.get_str_list("ignore", [])

    def preflight(self):
        sources = list(self.sources())
        if sources:
            raise ElementError(
                "{}: collect-integration elements may not have sources".format(
                    self
                )
            )

        for ignore in self.ignore:
            if self.search(ignore) is None:
                raise ElementError(
                    "{}: element {} is not in dependencies".format(
                        self, ignore
                    )
                )

    def get_unique_key(self):
        key = {
            "script-path": self.script_path,
            "ignore": sorted(set(self.ignore)),
        }
        return key

    def configure_sandbox(self, sandbox):
        pass

    def stage(self, sandbox):
        pass

    def assemble(self, sandbox):
        basedir = sandbox.get_virtual_directory()
        script_dirname = os.path.dirname(self.script_path)
        script_filename = os.path.basename(self.script_path)
        script_vdir = basedir.open_directory(
            script_dirname.lstrip(os.path.sep), create=True
        )

        with script_vdir.open_file(script_filename, mode="w") as f:
            os.chmod(f.name, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
            f.write("#!/bin/sh\n")
            f.write("set -e\n\n")
            for dependency in self.dependencies():
                if dependency.name in self.ignore:
                    continue
                bstdata = dependency.get_public_data("bst")
                if bstdata is not None:
                    if "integration-commands" in bstdata:
                        commands = dependency.node_subst_sequence_vars(
                            bstdata.get_sequence("integration-commands")
                        )

                        f.write(
                            "# integration commands from {}\n".format(
                                dependency.name
                            )
                        )
                        for cmd in commands:
                            f.write("{}\n\n".format(cmd))

        return os.path.sep


def setup():
    return ExtractIntegrationElement
