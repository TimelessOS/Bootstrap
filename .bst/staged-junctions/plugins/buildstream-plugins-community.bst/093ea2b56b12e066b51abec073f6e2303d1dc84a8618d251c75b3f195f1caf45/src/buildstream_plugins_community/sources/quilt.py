#  Copyright (C) 2018 Bloomberg Finance LP
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors:
#        Phillip Smyth <phillip.smyth@codethink.co.uk>
"""
A source implementation for using quilt to add patches.

**Usage:**

.. code:: yaml

   # Specify the quilt source kind
   kind: quilt

   # Specify the directory containing the series file
   path: patches

   # The directory containing the series file should also contain all patches.
   # This would ideally be located within the `files` directory.
"""

import os

from buildstream import Source, SourceError, utils


class QuiltSource(Source):
    BST_MIN_VERSION = "2.0"
    BST_REQUIRES_PREVIOUS_SOURCES_STAGE = True

    def configure(self, node):
        self.path = node.get_str("path", "")

    def preflight(self):
        # Check if patch is installed, get the binary at the same time
        self.host_quilt = utils.get_host_tool("quilt")

    def get_unique_key(self):
        return [self.path]

    def is_resolved(self):
        return True

    def is_cached(self):
        return True

    def get_ref(self):
        return None  # pragma: nocover

    def set_ref(self, ref, node):
        pass  # pragma: nocover

    def fetch(self):
        pass  # pragma: nocover

    def stage(self, directory):
        patch_dir = os.path.join(directory, self.path)
        with self.timed_activity(
            "quilt: Applying patches: {}".format(patch_dir)
        ):
            if not os.path.isdir(patch_dir):
                raise SourceError(
                    "Directory does not exist '{}'".format(patch_dir),
                    reason="no-dir-found",
                )
            # Call quilt command
            self.command = [self.host_quilt, "push", "-a"]
            self.call(
                self.command,
                cwd=directory,
                fail="Error occurred while calling {}".format(self.command),
                env={"QUILT_PATCHES": self.path},
            )


# Plugin entry point
def setup():
    return QuiltSource
