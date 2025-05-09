#  Copyright (C) 2017 Codethink Limited
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
#        Jonathan Maw <jonathan.maw@codethink.co.uk>
#        James Ennis <james.ennis@codethink.co.uk>

"""Dpkg build element

A `BuildElement
<https://docs.buildstream.build/master/buildstream.buildelement.html#module-buildstream.buildelement>`_
implementation for using dpkg elements

Default Configuration
~~~~~~~~~~~~~~~~~~~~~

The dpkg default configuration:
  .. literalinclude:: ../../../src/buildstream_plugins_community/elements/dpkg_build.yaml
     :language: yaml

Public data
~~~~~~~~~~~

This plugin writes to an element's public data.

split-rules
-----------

This plugin overwrites the element's split-rules with a list of its own
creation, creating a split domain for every package that it detected.
e.g.

.. code:: yaml

   public:
     bst:
       split-rules:
         foo:
         - /sbin/foo
         - /usr/bin/bar
         bar:
         - /etc/quux

dpkg-data
---------

control
'''''''

The control file will be written as raw text into the control field.
e.g.

.. code:: yaml

   public:
     bst:
       dpkg-data:
         foo:
           control: |
             Source: foo
             Section: blah
             Build-depends: bar (>= 1337), baz
             ...

name
''''

The name of the plugin will be written to the name field.
e.g.

.. code:: yaml

   public:
     bst:
       dpkg-data:
         bar:
           name: foobar

package-scripts
---------------

preinst, postinst, prerm and postrm scripts may be written to the
package if they are detected. They are written as raw text. e.g.

.. code:: yaml

   public:
     bst:
       package-scripts:
         foo:
           preinst: |
             #!/usr/bin/bash
             /sbin/ldconfig
         bar:
           postinst: |
             #!/usr/bin/bash
             /usr/share/fonts/generate_fonts.sh

"""

import os
import re

from buildstream import BuildElement, ElementError, Node


# Element implementation for the 'dpkg' kind.
class DpkgElement(BuildElement):
    BST_MIN_VERSION = "2.0"

    def _get_packages(self, sandbox):
        vdir = sandbox.get_virtual_directory()

        controlfile = os.path.join("debian", "control")
        controlpath = os.path.join(
            self.get_variable("build-root").lstrip(os.sep),
            controlfile,
        )
        with vdir.open_file(controlpath) as f:
            return re.findall(r"Package:\s*(.+)\n", f.read())

    def configure(self, node):
        # __original_commands is needed for cache-key generation,
        # as commands can be altered during builds and invalidate the key
        super().configure(node)
        self.__original_commands = dict(self._BuildElement__commands)

    def get_unique_key(self):
        key = super().get_unique_key()
        # Overriding because we change self._BuildElement__commands mid-build, making it
        # unsuitable to be included in the cache key.
        for domain, cmds in self.__original_commands.items():
            key[domain] = cmds

        return key

    def assemble(self, sandbox):
        # Replace <PACKAGES> if no variable was set
        packages = self._get_packages(sandbox)
        self._BuildElement__commands = {
            group: [
                c.replace("<PACKAGES>", " ".join(packages)) for c in commands
            ]
            for group, commands in self._BuildElement__commands.items()
        }

        collectdir = super().assemble(sandbox)

        vdir = sandbox.get_virtual_directory()
        debian_dir = vdir.open_directory(
            os.path.join(self.get_variable("build-root"), "debian").lstrip(
                os.sep
            )
        )

        bad_overlaps = set()
        new_split_rules = Node.from_dict({})
        new_dpkg_data = Node.from_dict({})
        new_package_scripts = Node.from_dict({})
        have_package_scripts = False
        for package in packages:

            package_dir = debian_dir.open_directory(package)

            # Exclude DEBIAN files because they're pulled in as public metadata
            contents = [
                "/" + x
                for x in package_dir.list_relative_paths()
                if x != "." and not x.startswith("DEBIAN")
            ]

            # Setup the new split rules
            new_split_rules[package] = contents

            # Check for any overlapping files that are different.
            # Since we're storing all these files together, we need to warn
            # because clobbering is bad!
            for content_file in contents:
                for split_package, split_contents in new_split_rules.items():
                    for split_file in split_contents.as_str_list():
                        split_package_dir = debian_dir.open_directory(
                            split_package
                        )
                        if (
                            content_file == split_file
                            and package_dir.isfile(content_file.lstrip(os.sep))
                            and split_package_dir.isfile(
                                split_file.lstrip(os.sep)
                            )
                        ):
                            content_file_digest = package_dir.file_digest(
                                content_file.lstrip(os.sep)
                            )
                            split_file_digest = package_dir.file_digest(
                                split_file.lstrip(os.sep)
                            )
                            if content_file_digest != split_file_digest:
                                bad_overlaps.add(content_file)

            # Store /DEBIAN metadata for each package.
            # DEBIAN/control goes into bst.dpkg-data.<package>.control
            if not package_dir.exists("DEBIAN/control"):
                raise ElementError(
                    "{}: package {} doesn't have a DEBIAN/control in {}!".format(
                        self.name, package, str(package_dir)
                    )
                )
            with package_dir.open_file("DEBIAN/control", mode="r") as f:
                controldata = f.read()

            # Setup the package data
            new_dpkg_data[package] = {"name": package, "control": controldata}

            # DEBIAN/{pre,post}{inst,rm} scripts go into bst.package-scripts.<package>.<script>
            package_scripts = Node.from_dict({})
            scriptfiles = ["preinst", "postinst", "prerm", "postrm"]
            for s in scriptfiles:
                if package_dir.exists(os.path.join("DEBIAN", s)):
                    have_package_scripts = True
                    if package not in new_package_scripts:
                        new_package_scripts[package] = package_scripts
                    with package_dir.open_file(
                        os.path.join("DEBIAN", s), mode="r"
                    ) as f:
                        data = f.read()
                    package_scripts[s] = data

        bstdata = self.get_public_data("bst")
        bstdata["split-rules"] = new_split_rules
        bstdata["dpkg-data"] = new_dpkg_data
        if have_package_scripts:
            bstdata["package-scripts"] = new_package_scripts

        self.set_public_data("bst", bstdata)

        if bad_overlaps:
            self.warn(
                "Destructive overlaps found in some files",
                detail="\n".join(bad_overlaps),
            )

        return collectdir

    def run_cleanup_commands(self, sandbox):
        # This is called by `BuildElement.assemble()` to speed up output capture.
        # Skip the optimization for this plugin as the contents of the build
        # directory are still needed after the call to `super().assemble()`.
        pass


# Plugin entry point
def setup():
    return DpkgElement
