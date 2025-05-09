#
#  Copyright (C) 2020 Codethink Limited
#  Copyright (C) 2021 Abderrahim Kitouni
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

import codecs
import gzip
import os

import requests
from buildstream import Source, SourceError, utils

from ._utils import HTTPFetcher, TarStager, ZipStager, translate_url, add_alias

PKG_INDEX = "modules/02packages.details.txt.gz"
BY_AUTHOR = "authors/id/"
UTF_CODEC = codecs.lookup("utf-8")


class CpanSource(Source):
    BST_MIN_VERSION = "2.0"
    BST_EXPORT_MANIFEST = True

    def configure(self, node):
        node.validate_keys(
            ["name", "suffix", "sha256sum", "index"]
            + Source.COMMON_CONFIG_KEYS
        )

        self.name = node.get_str("name")
        self.mirror_directory = os.path.join(
            self.get_mirror_directory(), utils.url_directory_name(self.name)
        )

        self.orig_index = node.get_str("index", "https://cpan.metacpan.org/")
        self.index = self.translate_url(self.orig_index)

        self.load_ref(node)

    def preflight(self):
        pass

    def get_unique_key(self):
        return [self.suffix, self.sha256sum]

    def load_ref(self, node):
        self.sha256sum = node.get_str("sha256sum", None)
        self.suffix = node.get_str("suffix", None)
        self.fetcher = HTTPFetcher(
            self,
            self.mirror_directory,
            self.orig_index,
            self.suffix,
            self.sha256sum,
        )

    def get_ref(self):
        if self.suffix is None or self.sha256sum is None:
            return None
        return {"suffix": self.suffix, "sha256sum": self.sha256sum}

    def set_ref(self, ref, node):
        node["suffix"] = self.suffix = ref["suffix"]
        node["sha256sum"] = self.sha256sum = ref["sha256sum"]

    def track(self):
        found = None
        response = requests.get(
            f"{self.index}{PKG_INDEX}", stream=True, timeout=60
        )
        with gzip.GzipFile(fileobj=response.raw) as data:
            listing = UTF_CODEC.streamreader(data)
            while True:
                line = listing.readline()
                if not line:
                    break
                line = line.rstrip("\r\n")
                if len(line) == 0:
                    break
            while True:
                line = listing.readline()
                if not line:
                    break
                line = line.rstrip("\r\n")
                package, _, url = line.split()
                if package == self.name:
                    found = url
                    break
        if not found:
            raise SourceError(
                f'{self}: "{self.name}" not found in {self.index}'
            )

        self.suffix = BY_AUTHOR + found
        self.fetcher = HTTPFetcher(
            self, self.mirror_directory, self.orig_index, self.suffix
        )
        self.sha256sum = self.fetcher.fetch()

        return self.get_ref()

    def get_source_fetchers(self):
        return [self.fetcher]

    def stage(self, directory):
        if self.suffix.endswith(".zip"):
            stager = ZipStager(self.fetcher.mirror_file)
        else:
            stager = TarStager(self.fetcher.mirror_file)

        stager.stage(directory)

    def is_cached(self):
        return self.fetcher.is_cached()

    def export_manifest(self):
        url = translate_url(
            self,
            self.orig_index,
            self.suffix,
        )
        manifest = {
            "type": "archive",
            "url": url,
            "sha256": self.sha256sum,
        }
        add_alias(manifest, self.orig_index)
        return manifest


def setup():
    return CpanSource
