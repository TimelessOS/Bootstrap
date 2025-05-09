"""
go_module - plugin for handling dependencies in go projects
===========================================================s

**Usage:**

.. code:: yaml

   # Specify the go_module source kind
   kind: go_module

   # Specify the repository url, using an alias defined
   # in your project configuration is recommended.
   url: upstream:repo.git

   # Set the module name
   module: golang.org/x/xerrors
"""

import os
import posixpath

from buildstream import Source, SourceError

from ._git_utils import (
    GitMirror,
    RefFormat,
    REF_REGEX,
    resolve_ref,
    get_full_sha,
    verify_version,
)


class GoModuleSource(Source):
    BST_MIN_VERSION = "2.0"

    BST_REQUIRES_PREVIOUS_SOURCES_TRACK = True
    BST_REQUIRES_PREVIOUS_SOURCES_STAGE = True
    BST_EXPORT_MANIFEST = True

    def configure(self, node):
        CONFIG_KEYS = ["ref", "url", "module"]

        node.validate_keys(Source.COMMON_CONFIG_KEYS + CONFIG_KEYS)
        self.ref = None
        self.load_ref(node)

        self.url = node.get_str("url")
        self.module = node.get_str("module")
        self.mark_download_url(self.url)

    def preflight(self):
        verify_version()

    def get_unique_key(self):
        return {"ref": self.ref, "module": self.module, "bugfix": 0}

    # loading and saving refs
    def load_ref(self, node):
        if "ref" not in node:
            return
        ref = node.get_mapping("ref")
        ref.validate_keys(["go-version", "git-ref", "explicit"])
        self.ref = {
            "go-version": ref.get_str("go-version"),
            "git-ref": ref.get_str("git-ref"),
            "explicit": ref.get_bool("explicit"),
        }
        if REF_REGEX.match(self.ref["git-ref"]) is None:
            raise SourceError(f"ref {ref} is not in the expected format")

    def get_ref(self):
        return self.ref

    def set_ref(self, ref, node):
        self.ref = ref
        node["ref"] = ref

    def is_cached(self):
        mirror = GitMirror(
            self,
            self.url,
            self.ref["git-ref"],
        )
        return mirror.has_ref()

    def track(self, previous_sources_dir):
        go_sum = os.path.join(previous_sources_dir, "go.sum")
        go_mod = os.path.join(previous_sources_dir, "go.mod")
        with open(go_mod, encoding="utf-8") as file:
            explicit = self.module in file.read()
        with open(go_sum, encoding="utf-8") as file:
            for line in file:
                # Third item is checksum which we ignore
                module, version, _ = line.strip().split()
                if version.endswith("/go.sum"):
                    # We ignore these for now
                    continue
                if version.endswith("/go.mod"):
                    # We ignore these for now
                    continue

                if module != self.module:
                    continue

                if version.startswith("v0.0.0"):
                    # Special-case, this encodes git commit
                    _, short_sha = version.rsplit("-", 1)
                    resolved = get_full_sha(self, self.url, short_sha)
                else:
                    lookup = version
                    incompatible = "+incompatible"
                    if version.endswith(incompatible):
                        self.warn(f"{self.module} {version}")
                        lookup = version[: -len(incompatible)]
                    resolved = resolve_ref(
                        self,
                        self.url,
                        lookup,
                        RefFormat.GIT_DESCRIBE,
                        (),
                    )
                return {
                    "go-version": version,
                    "git-ref": resolved,
                    "explicit": explicit,
                }

        raise SourceError(f"go.mod did not contain {self.module}")

    def get_source_fetchers(self):
        yield GitMirror(
            self,
            self.url,
            self.ref["git-ref"],
        )

    def _do_stage(self, directory, workspace=False):
        head, tail = posixpath.split(self.module)
        if self.ref["go-version"].startswith(tail):
            vendor_directory = os.path.join(directory, "vendor", head)
            version_directory = os.path.join(directory, "vendor", self.module)
        else:
            vendor_directory = os.path.join(directory, "vendor", self.module)
            version_directory = None
        os.makedirs(vendor_directory, exist_ok=True)
        mirror = GitMirror(
            self,
            self.url,
            self.ref["git-ref"],
        )
        if workspace:
            mirror.init_workspace(vendor_directory)
        else:
            mirror.stage(vendor_directory)
        if version_directory is not None and not os.path.exists(
            version_directory
        ):
            os.symlink(".", version_directory)
        self._append_modules_txt(directory)

    def stage(self, directory):
        self._do_stage(directory)

    def init_workspace(self, directory):
        self._do_stage(directory, workspace=True)

    def _append_modules_txt(self, directory):
        modules_txt = os.path.join(directory, "vendor/modules.txt")
        with open(modules_txt, "a", encoding="utf-8") as file:
            if self.ref["explicit"]:
                print(f"# {self.module} {self.ref['go-version']}", file=file)
                print("## explicit", file=file)
            else:
                print(f"# {self.module}", file=file)
            print(self.module, file=file)

    def export_manifest(self):
        url = self.translate_url(
            self.url,
            alias_override=None,
            primary=False,
        )
        return {
            "type": "git",
            "url": url,
            "commit": self.ref["git-ref"],
        }


def setup():
    return GoModuleSource
