#
#  Copyright (C) 2020 Codethink Limited
#  Copyright (C) 2020-2022 Seppo Yli-Olli
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
#         Seppo Yli-Olli <seppo.yli-olli@iki.fi>
#         Abderrahim Kitouni <akitouni@gnome.org>

import os
import re
import fnmatch

import requests
import packaging.utils

from buildstream import Source, SourceError
from buildstream.utils import url_directory_name

from ._utils import HTTPFetcher, TarStager, ZipStager, translate_url, add_alias


# We do not support parsing HTML
ACCEPT = "application/vnd.pypi.simple.v1+json"


def filter_files(files, matcher):
    processed = {}
    for file in files:
        if file["yanked"]:
            continue
        try:
            _, version = packaging.utils.parse_sdist_filename(file["filename"])
        except (
            packaging.utils.InvalidSdistFilename,
            packaging.utils.InvalidVersion,
        ):
            continue
        if matcher.should_include(version) and not matcher.should_exclude(
            version
        ):
            processed[version] = file
    return processed


class Matcher:
    def __init__(self, prereleases, include, exclude):
        self.prereleases = prereleases
        self.include = [
            re.compile(fnmatch.translate(item)) for item in include
        ]
        self.exclude = [
            re.compile(fnmatch.translate(item)) for item in exclude
        ]

    def should_include(self, version):
        if not self.prereleases and version.is_prerelease:
            return False
        for matcher in self.include:
            if not matcher.match(str(version)):
                return False
        return True

    def should_exclude(self, version):
        for matcher in self.exclude:
            if matcher.match(str(version)):
                return True
        return False


class PyPISource(Source):
    BST_MIN_VERSION = "2.0"
    BST_EXPORT_MANIFEST = True

    REST_API = "https://pypi.org/simple/{name}"
    STORAGE_ROOT = "https://files.pythonhosted.org/packages/"
    KEYS = [
        "url",
        "name",
        "ref",
        "prereleases",
        "include",
        "exclude",
    ] + Source.COMMON_CONFIG_KEYS

    def configure(self, node):
        node.validate_keys(self.KEYS)

        self.name = node.get_str("name")
        self.suffix = ""
        self.sha256sum = None
        self.fetcher = None

        self.matcher = Matcher(
            node.get_bool("prereleases", False),
            node.get_str_list("include", []),
            node.get_str_list("exclude", []),
        )

        self.mirror_directory = os.path.join(
            self.get_mirror_directory(), url_directory_name(self.name)
        )

        self.base_url = node.get_str("url", self.STORAGE_ROOT)
        self.mark_download_url(self.base_url)

        self.load_ref(node)

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
        url = self.REST_API.format(name=self.name)
        resp = requests.get(url, headers={"ACCEPT": ACCEPT}, timeout=10)

        if not resp.ok:
            raise SourceError(
                f"{url} returned HTTP Error {resp.status_code}: {resp.reason}"
            )

        payload = resp.json()

        if not payload["files"]:
            raise SourceError(f"Cannot find any tracking for {self.name}")
        files = filter_files(payload["files"], self.matcher)
        if not files:
            self.warn("No matching release found")
            return None

        latest = files[max(files)]
        return {
            "sha256sum": latest["hashes"]["sha256"],
            "suffix": latest["url"].replace(self.STORAGE_ROOT, ""),
        }

    def stage(self, directory):
        if self.suffix.endswith(".zip"):
            stager = ZipStager(self.fetcher.mirror_file)
        else:
            stager = TarStager(self.fetcher.mirror_file)

        stager.stage(directory)

    def is_cached(self):
        return self.fetcher.is_cached()

    def get_source_fetchers(self):
        return [self.fetcher]

    def export_manifest(self):
        url = translate_url(
            self,
            self.base_url,
            self.suffix,
        )
        manifest = {
            "type": "archive",
            "url": url,
            "sha256": self.sha256sum,
        }
        add_alias(manifest, self.base_url)
        return manifest


def setup():
    return PyPISource
