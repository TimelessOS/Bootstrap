#
#  Copyright (C) 2022 Seppo Yli-Olli
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
#         Seppo Yli-Olli <seppo.yli-olli@gmail.com>


from buildstream import BuildElement


# Element implementation for the 'pep517' kind.
class PEP517Element(BuildElement):

    BST_MIN_VERSION = "2.0"


# Plugin entry point
def setup():
    return PEP517Element
