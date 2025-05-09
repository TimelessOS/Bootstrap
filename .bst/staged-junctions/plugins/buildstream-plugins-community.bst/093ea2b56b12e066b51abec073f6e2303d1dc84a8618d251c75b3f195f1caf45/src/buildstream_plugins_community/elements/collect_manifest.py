# Copyright (c) 2018 freedesktop-sdk
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Authors:
#        Valentin David <valentin.david@gmail.com>
#        Adam Jones <adam.jones@codethink.co.uk>
"""
Collect Manifest Element

A buildstream plugin used to produce a manifest file
containing a list of elements for a given dependency.

The manifest contains useful information such as:
    - CPE data, such as CVE patches
    - Package name
    - Version
    - Sources
    - Source locations
    - SHAs
    - Patch files

The manifest file is exported as a json file to the path provided
under the "path" variable defined in the .bst file.

Dependency elements can manually declare CPE data in their public
section. For example:

.. code:: yaml

   public:
     cpe:
       product: gnutls
       vendor: gnu
       version: '1.0'

This data will be set in the ``x-cpe`` field of the entry.

If not present, ``product`` will be automatically be inferred from the
name of the element.

For version resolution source plugin must opt-in to export_manifest protocol
by setting BST_EXPORT_MANIFEST and implementing export_manifest method.

Currently allowed outputs are:

.. code-block:: JSON

    {
       "type": "git",
       "url": "https://foo.bar/repo.git",
       "commit": "hash/git-describe"
    }

.. code-block:: JSON

    {
       "type": "archive",
       "url": "https://path/to/package.tgz",
       "sha256": "checksum"
    }

.. code-block:: JSON

    {
       "type": "patch",
       "path": "path/to/patches"
    }

Version will be calculated from commit for git and from basename of URL for
archive.

The default version regular expression is ``\\d+\\.\\d+(?:\\.\\d+)?`` (2 or 3
numerical components separated by dots). It is possible to
change the version regular expression with field ``version-match``.

The version regular exression must follow Python regular expression
syntax.  A version regular expression with no group will match exactly
the version. A version regular expression with groups will match
components of the version with each groups. The components will then
be concatenated using ``.`` (dot) as a separator.

``version-match`` in the ``cpe`` public data will never be exported in
the ``x-cpe`` field of the manifest.

Here is an example of ``version-match`` where the filename is
``openssl1_1_1d.tar.gz``, the result version will be ``1.1.1d``.

.. code:: yaml

   public:
     cpe:
       version-match: '(\\d+)_(\\d+)_(\\d+[a-z]?)'
"""

import os
import re
import json
import posixpath

from buildstream import Element, Node, ElementError


class CollectManifestElement(Element):
    BST_MIN_VERSION = "2.0"
    BST_ARTIFACT_VERSION = 2

    def configure(self, node):
        if "path" in node:
            self.path = self.node_subst_vars(node.get_scalar("path"))
        else:
            self.path = None

    def preflight(self):
        pass

    def get_unique_key(self):
        key = {"path": self.path}
        return key

    def configure_sandbox(self, sandbox):
        pass

    def stage(self, sandbox):
        pass

    def extract_cpe(self, dep):
        cpe = dep.get_public_data("cpe")

        if cpe is None:
            cpe = {}
        else:
            cpe = cpe.strip_node_info()

        if "product" not in cpe:
            cpe["product"] = os.path.basename(os.path.splitext(dep.name)[0])

        version_match = cpe.pop("version-match", None)

        sources = list(dep.sources())

        if "version" not in cpe and sources:
            matcher = VersionMatcher(version_match)
            version = matcher.get_version(sources)

            if version is None:
                if version_match is None:
                    self.warn("Missing version to {}.".format(dep.name))
                else:
                    fmt = '{}: {}: version match string "{}" did not match anything.'
                    msg = fmt.format(self.name, dep, version_match)
                    raise ElementError(msg)

            if version:
                cpe["version"] = version

        return cpe

    def extract_sources(self, dep):
        sources = list(dep.sources())

        source_locations = []

        if sources:
            source_locations = get_source_locations(sources)

        return source_locations

    def get_dependencies(self, dep, visited):
        if dep in visited:
            return
        visited.add(dep)
        for subdep in dep.dependencies(recurse=False):
            yield from self.get_dependencies(subdep, visited)
        yield dep

    def assemble(self, sandbox):
        manifest = {
            "//NOTE": (
                "This is a generated manifest from buildstream files "
                "and not usable by flatpak-builder"
            ),
            "modules": [],
        }

        visited = set()
        for top_dep in self.dependencies(recurse=False):
            for dep in self.get_dependencies(top_dep, visited):
                import_manifest = dep.get_public_data("cpe-manifest")

                if import_manifest:
                    import_manifest = import_manifest.strip_node_info()
                    manifest["modules"].extend(import_manifest["modules"])
                else:
                    cpe = self.extract_cpe(dep)
                    sources = self.extract_sources(dep)

                    if cpe:
                        manifest["modules"].append(
                            {
                                "name": dep.name,
                                "x-cpe": cpe,
                                "sources": sources,
                            }
                        )

        if self.path:
            basedir = sandbox.get_virtual_directory()
            dirname = os.path.dirname(self.path)
            filename = os.path.basename(self.path)
            vdir = basedir.open_directory(
                dirname.lstrip(os.path.sep), create=True
            )
            if vdir.exists(filename):
                if filename[-1].isdigit():
                    version = int(filename[-1]) + 1
                    new_filename = list(filename)
                    new_filename[-1] = str(version)
                    filename = "".join(new_filename)
                else:
                    filename = filename + "-1"

            with vdir.open_file(filename, mode="w") as o:
                json.dump(manifest, o, indent=2)

        manifest_node = Node.from_dict(dict(manifest))
        self.set_public_data("cpe-manifest", manifest_node)
        return os.path.sep


class VersionMatcher:

    DEFAULT_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")

    def __init__(self, match):
        if match is None:
            self.__match = self.DEFAULT_VERSION_RE
        else:
            self.__match = re.compile(match)

    def _parse_version(self, text):
        m = self.__match.search(text)
        if not m:
            return None
        if self.__match.groups == 0:
            return m.group(0)
        else:
            return ".".join(m.groups())

    def get_version(self, sources):
        """
        This method attempts to extract the source version
        from a dependency. This data can generally be found
        in the url for tar balls, or the ref for git repos.

        :sources A list of BuildStream Sources
        """
        for source in sources:
            export_manifest = getattr(source, "BST_EXPORT_MANIFEST", False)
            if export_manifest:
                manifests = source.export_manifest()
                version = None
                if isinstance(manifests, dict):
                    manifests = [manifests]
                elif not isinstance(manifests, list):
                    raise ElementError(
                        f"Invalid manifest for source {source} of type {type(manifests)}"
                    )
                for manifest in manifests:
                    if manifest["type"] == "git":
                        version = self._parse_version(manifest["commit"])
                    elif manifest["type"] == "archive":
                        version = self._parse_version(
                            posixpath.basename(manifest["url"])
                        )
                    if version is not None:
                        break

                if version is None:
                    continue
                return version
            if source.get_kind() in ["tar", "zip"]:
                url = source.url
                filename = url.rpartition("/")[2]
                version = self._parse_version(filename)
                if version is not None:
                    return version
            elif source.get_kind().startswith("git"):
                ref = source.mirror.ref
                version = self._parse_version(ref)
                if version is not None:
                    return version
        return None


def get_source_locations(sources):
    """
    Returns a list of source URLs and refs, currently for
    git, tar and patch sources.

    :sources A list of BuildStream Sources
    """
    source_locations = []
    for source in sources:
        export_manifest = getattr(source, "BST_EXPORT_MANIFEST", False)
        if export_manifest:
            manifest = source.export_manifest()
            if isinstance(manifest, dict):
                source_locations.append(manifest)
            elif isinstance(manifest, list):
                source_locations.extend(manifest)
            else:
                raise ElementError(
                    f"Invalid manifest for source {source} of type {type(manifest)}"
                )
            continue
        if source.get_kind() in ["git"]:
            url = source.translate_url(
                source.mirror.url,
                alias_override=None,
                primary=source.mirror.primary,
            )
            source_locations.append(
                {
                    "type": source.get_kind(),
                    "url": url,
                    "commit": source.mirror.ref,
                }
            )
        if source.get_kind() in ["patch"]:
            patch = source.path.rpartition("/")[2]
            source_locations.append({"type": source.get_kind(), "path": patch})
        if source.get_kind() in ["tar", "zip"]:
            source_locations.append(
                {"type": "archive", "url": source.url, "sha256": source.ref}
            )

    return source_locations


def setup():
    return CollectManifestElement
