#  Copyright (C) 2018 Codethink Limited
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
#        Christopher Phang <christopher.phang@codethink.co.uk>

"""fastboot_bootimg image build element

A `ScriptElement
<https://docs.buildstream.build/master/buildstream.scriptelement.html#module-buildstream.scriptelement>`_
implementation for creating fastboot boot images

The fastboot default configuration:
  .. literalinclude:: ../../../src/buildstream_plugins_community/elements/fastboot_bootimg.yaml
     :language: yaml
"""

from buildstream import ScriptElement, ElementError


# Element implementation for the 'FastbootBootImage' kind.
# Based on the implementation for generating x86 images
class FastbootBootImageElement(ScriptElement):
    BST_MIN_VERSION = "2.0"

    def configure(self, node):
        command_steps = ["create_dtb", "create_img", "install_img"]

        for step in command_steps:
            cmds = node.get_str_list(step)
            self.add_commands(step, cmds)

        self.set_work_dir()
        self.set_install_root()
        self.set_root_read_only(True)

    def configure_dependencies(self, dependencies):
        have_input = False
        for dep in dependencies:
            input_dep = False
            # Separate base dependencies from input dependencies
            if dep.config:
                dep.config.validate_keys(["input"])
                input_dep = dep.config.get_bool("input", False)

            if input_dep:
                have_input = True
                self.layout_add(
                    dep.element, dep.path, self.get_variable("build-root")
                )
            else:
                self.layout_add(dep.element, dep.path, "/")

        if not have_input:
            raise ElementError(
                "{}: No 'input' dependency specified".format(self)
            )

    def configure_sandbox(self, sandbox):
        super().configure_sandbox(sandbox)

        # We do some work in this directory, and need it to be read-write
        sandbox.mark_directory("/buildstream")


# Plugin entry point
def setup():
    return FastbootBootImageElement
