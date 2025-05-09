#
#  Copyright (C) 2020 Codethink Limited
#  Copyright (C) 2021 Abderrahim Kitouni
#  Copyright (C) 2022 Kyle Rosenberg
#  Copyright (C) 2023 Adrian Vovk
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
#         Abderrahim Kitouni <akitouni@gnome.org>
#         Kyle Rosenberg <kyle@ekrosenberg.com>
#         Adrian Vovk <adrianvovk@gmail.com>

# History: this source is based on the cpan source, modified to track gnu
# projects by Kyle, and ported to bst2 by Adrian

"""
gnu - automatically track gnu projects
==============================================

**Usage:**

.. code:: yaml

   # Specify the gnu source kind
   kind: gnu

   # name of the project as it appears in the ftp server
   name: autoconf

   # Optionally specify the name of the directory this package is
   # located in on the ftp server (defaults to the project's name)
   dirname: autoconf

   # Optionally specify the mirror you wish to use
   mirror: https://ftpmirror.gnu.org/gnu/

   # Internal source reference: path to the tarball within the mirror,
   # and the sha256sum of the tarball.
   #
   # This will be automatically updated with `bst source track`.
   ref:
     suffix: autoconf/autoconf-2.71.tar.xz
     sha256sum: f14c83cfebcc9427f2c3cea7258bd90df972d92eb26752da4ddad81c87a0faa4
"""

import gzip
import os
import re

import requests
from buildstream import Source, SourceError, utils
from ._utils import HTTPFetcher, TarStager


# Supported compression algorithms, ordered from least-preferred to most-preferred
COMPRESSION = ["gz", "bz2", "xz"]

# Regex that matches files in the GNU ftp index. A match creates a tuple like so:
# (<the path to the tarball>, <the version of the tarball>, <the compression type>)
# https://regex101.com/r/dZ1RQL/11
REGEX = (
    r"\.\/gnu\/({{dirname}}\/.*{{name}}-([0-9][0-9.]*)\.tar\.({exts}))(?!.)"
).format(exts="|".join(COMPRESSION))


# First we stort by version numbers, then by compression method preference
def _version_sort_key(matched):
    _, version, ext = matched
    version_num = [int(x) for x in version.split(".")]
    ext_pref = COMPRESSION.index(ext)
    return (version_num, ext_pref)


class GnuSource(Source):
    BST_MIN_VERSION = "2.0"

    def configure(self, node):
        node.validate_keys(
            ["name", "dirname", "mirror", "track"] + Source.COMMON_CONFIG_KEYS
        )

        self.name = node.get_str("name")
        dirname = node.get_str("dirname", self.name)
        self.pattern = REGEX.format(name=self.name, dirname=dirname)

        self.mirror_directory = os.path.join(
            self.get_mirror_directory(), utils.url_directory_name(dirname)
        )

        self.tracking = node.get_bool("track", True)

        self.load_ref(node)

        self.base_url = node.get_str(
            "mirror", "https://ftpmirror.gnu.org/gnu/"
        )
        self.mark_download_url(self.base_url)

    def preflight(self):
        pass

    def get_unique_key(self):
        return [self.suffix, self.sha256sum]

    def load_ref(self, node):
        ref_mapping = node.get_mapping("ref", None)
        if ref_mapping:
            self.suffix = ref_mapping.get_str("suffix")
            self.sha256sum = ref_mapping.get_str("sha256sum")
            self.fetcher = HTTPFetcher(
                self,
                self.mirror_directory,
                self.base_url,
                self.suffix,
                self.sha256sum,
            )

    def get_ref(self):
        if self.suffix and self.sha256sum:
            return {
                "sha256sum": self.sha256sum,
                "suffix": self.suffix,
            }
        return None

    def set_ref(self, ref, node):
        self.suffix = ref["suffix"]
        self.sha256sum = ref["sha256sum"]
        node["ref"] = ref

    def track(self):
        if not self.tracking:
            # Use requested tracking to be stopped, most likely because source is frozen
            return None

        found = None
        # TODO: is it possible to cache this data somewhere so we only download
        #       this index once per invocation of `bst source track`?
        # TODO: Should we make this URL configurable somehow?
        index_url = "https://ftp.gnu.org/find.txt.gz"

        resp = requests.get(index_url, timeout=60)

        if not resp.ok:
            raise SourceError(
                f"{resp.url} returned HTTP Error {resp.status_code}: {resp.reason}"
            )

        text = gzip.decompress(resp.content).decode()

        versions = re.findall(self.pattern, text)
        versions = list(set(versions))  # Remove duplicates
        if len(versions) > 0:
            versions.sort(reverse=True, key=_version_sort_key)
            found = versions[0][0]

        if not found:
            raise SourceError(
                f'{self}: "{self.name}" not found in {index_url}'
            )

        suffix = found

        if suffix == self.fetcher.suffix:
            sha256sum = self.fetcher.sha256sum
        else:
            sha256sum = None

        fetcher = HTTPFetcher(
            self.mirror_directory,
            self.base_url,
            suffix,
            sha256sum,
        )

        sha256sum = fetcher.fetch()

        self.info(f"Found tarball: {found} (hash: {self.sha256sum})")
        return {
            "sha256sum": sha256sum,
            "suffix": suffix,
        }

    def stage(self, directory):
        stager = TarStager(self.fetcher.mirror_file)

        stager.stage(directory)

    def is_cached(self):
        return self.fetcher.is_cached()

    def get_source_fetchers(self):
        return [self.fetcher]


def setup():
    return GnuSource
