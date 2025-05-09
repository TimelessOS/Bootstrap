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
tar_element - Output tarballs
=============================

An element plugin for creating tarballs from the specified
dependencies

Default Configuration
~~~~~~~~~~~~~~~~~~~~~

The tarball_element default configuration:
  .. literalinclude:: ../../../src/buildstream_plugins_community/elements/tar_element.yaml
     :language: yaml
"""

import tarfile

from buildstream import Element, ElementError


class TarElement(Element):

    BST_MIN_VERSION = "2.0"

    # The tarball's output is its dependencies, so
    # we must rebuild if they change
    BST_STRICT_REBUILD = True

    # Tarballs don't need runtime dependencies
    BST_FORBID_RDEPENDS = True

    # Our only sources are previous elements, so we forbid
    # remote sources
    BST_FORBID_SOURCES = True

    def configure(self, node):
        node.validate_keys(["filename", "compression"])
        self.filename = self.node_subst_vars(node.get_scalar("filename"))
        self.compression = node.get_str("compression")

        if self.compression not in ["none", "gzip", "xz", "bzip2"]:
            raise ElementError(
                "{}: Invalid compression option {}".format(
                    self, self.compression
                )
            )

    def preflight(self):
        pass

    def get_unique_key(self):
        key = {}
        key["filename"] = self.filename
        key["compression"] = self.compression
        return key

    def configure_sandbox(self, sandbox):
        pass

    def stage(self, sandbox):
        # Stage deps in the sandbox at "/input"
        with self.timed_activity("Staging dependencies", silent_nested=True):
            self.stage_dependency_artifacts(sandbox, path="/input")

    def assemble(self, sandbox):
        basedir = sandbox.get_virtual_directory()
        inputdir = basedir.open_directory("input", create=True)
        outputdir = basedir.open_directory("output", create=True)

        with self.timed_activity("Creating tarball", silent_nested=True):

            # Create an uncompressed tar archive
            compress_map = {
                "none": "",
                "gzip": "gz",
                "xz": "xz",
                "bzip2": "bz2",
            }
            extension_map = {
                "none": ".tar",
                "gzip": ".tar.gz",
                "xz": ".tar.xz",
                "bzip2": ".tar.bz2",
            }
            with outputdir.open_file(
                self.filename + extension_map[self.compression], mode="wb"
            ) as outputfile:
                mode = "w:" + compress_map[self.compression]
                with tarfile.TarFile.open(
                    fileobj=outputfile, mode=mode
                ) as tar:
                    inputdir.export_to_tar(tar, "")

        return "/output"


def setup():
    return TarElement
