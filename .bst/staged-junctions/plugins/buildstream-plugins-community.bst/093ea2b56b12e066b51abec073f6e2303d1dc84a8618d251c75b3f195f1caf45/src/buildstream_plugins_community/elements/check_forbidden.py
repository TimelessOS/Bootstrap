#
#  Copyright (C) 2019-2020 Codethink Limited
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
#         Frazer Leslie Clews <frazer.clews@codethink.co.uk>

import os
from buildstream import Element, ElementError


class CheckForbiddenElement(Element):

    BST_MIN_VERSION = "2.0"

    def configure(self, node):
        node.validate_keys(["forbidden"])

        self.forbidden = set(node.get_str_list("forbidden"))

    def preflight(self):
        pass

    def get_unique_key(self):
        return {"forbidden": sorted(list(self.forbidden))}

    def configure_sandbox(self, sandbox):
        pass

    def _find_bad_dependencies(self, elt, traversed):
        if elt in traversed:
            return False
        if elt.name in self.forbidden:
            return True
        traversed.add(elt)
        bad = False
        for dep in elt.dependencies(recurse=False):
            if self._find_bad_dependencies(dep, traversed):
                self.warn(
                    "{} depends on {}".format(elt.normal_name, dep.normal_name)
                )
                bad = True
        return bad

    def stage(self, sandbox):
        pass

    def assemble(self, sandbox):
        traversed = set()
        for dep in self.dependencies(recurse=False):
            if self._find_bad_dependencies(dep, traversed):
                raise ElementError("Some elements were forbidden")
        return os.sep


def setup():
    return CheckForbiddenElement
