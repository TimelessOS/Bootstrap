#
#  Copyright (C) 2016, 2019 Codethink Limited
#  Copyright (C) 2018 Bloomberg Finance LP
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
#        Thomas Coldrick <thomas.coldrick@codethink.co.uk>
"""
BazelElement - Element plugin for Bazel builds
================================================

BuildElement implementation for bazel builds. This plugin should be
sufficiently powerful to build any bazel project, provided it is
combined with a `BazelSource` source transform plugin to fetch any external
bazel dependencies.

To use this plugin, add a source for your bazel project upstream, as well as
a `BazelSource` plugin. The source requires a "repository resolved" file in
the bazel workspace, this can be provided in the upstream project, or via a
`local` or `patch` source. This resolved file must have been generated for the
targets you wish to build, otherwise there may be missing dependencies.

This plugin really just provides a nice way to run bazel, with overwriteable
variables you can use to add options. Some sensible looking defaults have
been set, which can be overridden using specific variables.

Most importantly, you should specify the `target` variable with the bazel
target you wish to build, e.g. `//foo:bar`.

Here is the default configuration for the `bazel` element

.. literalinclude:: ../../../src/buildstream_plugins_community/elements/bazel_build.yaml
     :language: yaml
"""

from buildstream import BuildElement


class BazelElement(BuildElement):

    BST_MIN_VERSION = "2.0"

    def configure_sandbox(self, sandbox):
        super().configure_sandbox(sandbox)

        # We set this to be the output user root for bazel. Perhaps we
        # could just use a tmpdir, but I think this could mean we lose
        # the output between build and install. We also may want this to
        # persist for the cache.
        #
        sandbox.mark_directory("/bazel-home")


def setup():
    return BazelElement
