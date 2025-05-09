#  Copyright (C) 2023 Adrian Vovk
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
#        Adrian Vovk <adrianvovk@gmail.com>

"""
gen-cargo-lock - Generate a Cargo.lock file
===========================================

Some Rust projects lack a Cargo.lock file, making it
impossible to vendor dependencies using the cargo
source. This source, when staged between a source
that provides a Cargo project and the cargo source,
generates the missing Cargo.lock file.

**Host dependencies:**

    * cargo (only needed for tracking)

**Usage:**

.. code:: yaml

   sources:

   # The project sources. These lack a Cargo.lock file
   - kind: git_repo
     url: upstream:foobar.git
     track: refs/tags/*

   # Generates the missing Cargo.lock file
   - kind: gen-cargo-lock

   # Uses generated Cargo.lock file to vendor Rust dependencies
   - kind: cargo
"""

import os
import base64
from buildstream import Source, utils


class GenCargoLockSource(Source):
    BST_MIN_VERSION = "2.0"
    BST_REQUIRES_PREVIOUS_SOURCES_TRACK = True

    def configure(self, node):
        node.validate_keys(Source.COMMON_CONFIG_KEYS + ["ref"])
        self.ref = node.get_str("ref", None)

    def preflight(self):
        # We would normally call utils.get_host_tool here, but this would introduce
        # a dependency on cargo on the host, even though we don't really need it for
        # anything other than tracking. So, we actually only look for the host cargo
        # in the track method
        self.host_cargo = None

    def get_unique_key(self):
        return self.ref

    def load_ref(self, node):
        self.ref = node.get_str("ref", None)

    def get_ref(self):
        return self.ref

    def set_ref(self, ref, node):
        node["ref"] = self.ref = ref

    def track(self, previous_sources_dir):
        if self.host_cargo is None:
            self.host_cargo = utils.get_host_tool("cargo")

        # Generate a new Cargo.lock
        with self.timed_activity("Generating Cargo.lock"):
            command = [self.host_cargo, "generate-lockfile"]
            env = {"CARGO_HOME": self.get_mirror_directory(), **os.environ}
            self.call(
                command,
                cwd=previous_sources_dir,
                env=env,
                fail="Failed to generate lockfile",
            )

        # Encode Cargo.lock into base64
        output = os.path.join(previous_sources_dir, "Cargo.lock")
        with open(output, "rb") as f:
            new_ref = base64.b64encode(f.read()).decode("ascii")

        # We store the entirety of Cargo.lock in the ref, simply because
        # running `cargo generate-lockfile` does not always result in the
        # same Cargo.lock file. We don't want a fetch to effectively re-track
        # the package
        return new_ref

    def fetch(self):
        pass

    def stage(self, directory):
        # Decode the base64 to get back Cargo.lock
        cargo_lock = base64.b64decode(self.ref.encode("ascii")).decode("utf-8")

        # Write the file into the sandbox
        target = os.path.join(directory, "Cargo.lock")
        with open(target, "w", encoding="utf-8") as f:
            f.write(cargo_lock)

    def is_cached(self):
        # All the relevant data for the plugin is stored in the ref, so if this
        # plugin is resolved it is also cached
        return self.is_resolved()


# Entry point
def setup():
    return GenCargoLockSource
