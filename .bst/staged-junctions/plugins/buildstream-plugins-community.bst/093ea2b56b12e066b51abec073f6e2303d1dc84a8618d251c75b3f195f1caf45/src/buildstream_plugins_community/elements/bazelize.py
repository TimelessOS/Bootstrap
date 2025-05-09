#
#  Copyright (C) 2020, 2024 Codethink Limited
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
#  License along with this library. If not, see <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt>.
#
#  Authors:
#        Abderrahim Kitouni <abderrahim.kitouni@codethink.co.uk>
#        Darius Makovsky <darius.makovsky@codethink.co.uk>
"""
Bazelize element plugin

An element that creates a Bazel project from its build dependencies.

It creates BUILD.bazel files calling bazel rules.

For each element, it creates a filegroup target with the files belonging
to that element, plus potentially a cc_library and py_library when C/C++
libraries and python packages are detected.

As an example considering an element `makelib.bst` producing an artifact
containing:
* usr/include/hdr.h
* usr/lib/lib.so

An element of this kind ('bazelize.bst') declaring a
`build-depends: makelib.bst` will produce a full Bazel project including
an empty WORKSPACE file, the artifact from the dependency element, and
a BUILD.bazel file containing:

.. code::

    load("@rules_cc//cc:defs.bzl", "cc_library")

    package(default_visibility = ["//visibility:public"])

    filegroup(
        name = "makelib",
        srcs = ['usr/include/hdr.h', 'usr/lib/lib.so'],
    )

    cc_library(
        name = "makelib_cc",
        hdrs = ['usr/include/hdr.h'],
        srcs = ['usr/lib/lib.so'],
    )

You can influence the files included in the output of the plugin by setting the
configuration values for this plugin. It supports the standard ``include``,
``exclude`` and ``include-orphans`` to include or exclude files based on their
split domains.

You can also set some configuration in the dependency elements' public data,
under the ``bazelize-data`` key, which this plugin will pick up and add to the
generated BUILD.bazel file for targets generated from that element. Currently,
only ``includes`` is supported.
"""

import re
import posixpath
from pathlib import Path

from buildstream import (  # pylint: disable=import-error
    Element,
    ElementError,
    MappingNode,
    OverlapAction,
)

SUPPORTED_RULES = {
    "cc_library": "@rules_cc//cc:defs.bzl",
    "py_library": "@rules_python//python:defs.bzl",
    "filegroup": None,
}


def format_list(indent, prefix, lst):
    lst = sorted(lst, key=lambda f: f.split("."))
    formatted_values = ['"' + value + '"' for value in lst]

    lines = [2 * indent + value + "," for value in formatted_values]
    lines.insert(0, prefix + "[")
    lines.append(indent + "],")
    return lines


class BazelRule:
    def __init__(self, rule_name, target_name, deps, data, **kwargs):
        if rule_name not in SUPPORTED_RULES:
            raise ElementError(
                f"The bazelize plugin doesn't support rule '{rule_name}'"
            )

        self.rule_name = rule_name
        self.name = target_name
        self.deps = deps
        self.data = data
        self.args = kwargs

    def get_load_statement(self):
        package = SUPPORTED_RULES[self.rule_name]
        if package is not None:
            return f'load("{package}", "{self.rule_name}")'

        return None

    def get_rule_statement(self):
        lines = []
        indent = " " * 4

        lines.append(f"{self.rule_name}(")
        for arg in (
            "name",
            "srcs",
            "hdrs",
            "data",
            "imports",
            "includes",
            "deps",
        ):
            value = getattr(self, arg, None) or self.args.get(arg)
            if not value:
                continue
            if isinstance(value, str):
                lines.append(f'{indent}{arg} = "{value}",')
            elif len(value) == 1:
                lines.append(f'{indent}{arg} = ["{value.pop()}"],')
            else:
                lines.extend(format_list(indent, f"{indent}{arg} = ", value))
        lines.append(")")

        return "\n" + "\n".join(lines)


def extract_dependencies(element):
    deps = set()
    for dep in element.dependencies(recurse=False):
        if dep.get_kind() == "stack":
            deps.update(extract_dependencies(dep))
        else:
            deps.add(dep)
    return deps


def make_filegroup(element, manifest, **extra):
    srcs = manifest
    name = element.normal_name
    data = [dep.normal_name for dep in extract_dependencies(element)]

    return BazelRule("filegroup", name, [], data, srcs=srcs)


def make_py_library(element, manifest, **extra):
    srcs = set()
    imports = set()

    name = element.normal_name + "_py"
    deps = [dep.normal_name + "_py" for dep in extract_dependencies(element)]
    data = [element.normal_name]

    for filename in manifest:
        siteindex = filename.find("site-packages/")
        if siteindex < 0:
            continue
        imports.add(filename[:siteindex] + "site-packages/")
        if filename.endswith(".py"):
            srcs.add(filename)

    if imports:
        return BazelRule(
            "py_library", name, deps, data, imports=imports, srcs=srcs
        )

    return None


# header regex
HDR_EXT = re.compile(r"\.(h(x{2}|p{2})?|h{2}|H|in(c|l))$")
SRC_EXT = re.compile(r"\.(pic\.(lo|a|o)|a|lo|o|so(\.\d+)*)$")


def make_cc_library(element, manifest, includes=None, **extra):
    if includes is None:
        includes = []

    name = element.normal_name + "_cc"
    deps = [dep.normal_name + "_cc" for dep in extract_dependencies(element)]
    data = [element.normal_name]

    srcs = set()
    hdrs = set()

    for item in manifest:
        ext = "".join(Path(item).suffixes)
        if SRC_EXT.search(ext) and posixpath.basename(item).startswith("lib"):
            # looks like a source
            srcs.add(item)
        elif HDR_EXT.search(ext):
            # looks like a header
            hdrs.add(item)

    if srcs or hdrs:
        return BazelRule(
            "cc_library",
            name,
            deps,
            data,
            srcs=srcs,
            hdrs=hdrs,
            includes=includes,
        )

    return None


def make_rules(element, manifest):
    bazelize_data = element.get_public_data("bazelize-data")
    if bazelize_data is not None:
        bazelize_data.validate_keys(["includes"])
        extras = bazelize_data.strip_node_info()
    else:
        extras = {}

    rules = []

    for make_rule in make_filegroup, make_cc_library, make_py_library:
        rule = make_rule(element, manifest, **extras)
        if rule is not None:
            rules.append(rule)

    return rules


class BazelizeElement(Element):
    """Buildstream element plugin kind formatting calls to cc_library rules"""

    # pylint: disable=attribute-defined-outside-init

    BST_MIN_VERSION = "2.0"
    BST_ARTIFACT_VERSION = 3

    BST_STRICT_REBUILD = True
    BST_FORBID_RDEPENDS = True
    BST_FORBID_SOURCES = True
    BST_RUN_COMMANDS = False

    def preflight(self) -> None:
        pass

    def configure(self, node: MappingNode) -> None:
        node.validate_keys(["include", "exclude", "include-orphans"])

        self.include = node.get_str_list("include")
        self.exclude = node.get_str_list("exclude")
        self.include_orphans = node.get_bool("include-orphans")

    def configure_sandbox(self, sandbox):
        pass

    def get_unique_key(self) -> "SourceRef":
        return {
            "include": sorted(self.include),
            "exclude": sorted(self.exclude),
            "include-orphans": self.include_orphans,
        }

    def stage(self, sandbox: "Sandbox") -> None:
        for dep in self.dependencies(recurse=False):
            # We can't manipulate artifacts directly, we need to first stage
            # them into the sandbox
            build_path = posixpath.join(
                self.get_variable("build-root").lstrip("/"),
                dep.get_artifact_name(),
            )
            # Stage them again at the install root to be part of the artifact
            install_path = self.get_variable("install-root").lstrip("/")

            for path in build_path, install_path:
                dep.stage_artifact(
                    sandbox,
                    path=path,
                    include=self.include,
                    exclude=self.exclude,
                    orphans=self.include_orphans,
                    action=OverlapAction.WARNING,
                )

    def get_manifest(self, sandbox, element):
        sandbox_root = sandbox.get_virtual_directory()
        artifact_path = posixpath.join(
            self.get_variable("build-root").lstrip("/"),
            element.get_artifact_name(),
        )

        directories = [(sandbox_root.open_directory(artifact_path), "")]

        while directories:
            directory, prefix = directories.pop(0)
            for filename in directory:
                # Currently, Bazel does not support paths/filenames with
                # spaces. So, we exclude such paths/filenames from the
                # manifest.
                if " " in filename:
                    continue
                if directory.isdir(filename):
                    path = posixpath.join(prefix, filename)
                    directories.append(
                        (directory.open_directory(filename), path)
                    )
                else:
                    yield posixpath.join(prefix, filename)

    def _gather_targets(self, sandbox):
        """Gather the required rules for the defined targets

        This returns a list of rule entry objects
        """
        targets = set()

        for dep in self.dependencies(recurse=False):
            manifest = sorted(self.get_manifest(sandbox, dep))
            targets.update(make_rules(dep, manifest))

        # sort by target name
        targets = sorted(targets, key=lambda x: x.name)

        # remove unbound dependencies
        bound = {target.name for target in targets}
        for target in targets:
            target.deps = sorted(set(target.deps).intersection(bound))
            target.data = sorted(set(target.data).intersection(bound))

        return targets

    def assemble(self, sandbox: "Sandbox") -> str:
        # format the visibility
        visibility = "public"
        visibility_stmt = (
            f'\npackage(default_visibility = ["//visibility:{visibility}"])'
        )

        targets = self._gather_targets(sandbox)

        load_stmts = set()
        for target in targets:
            stmt = target.get_load_statement()
            if stmt:
                load_stmts.add(stmt)

        workspace_filename = "WORKSPACE"
        build_filename = "BUILD.bazel"

        sandbox_root = sandbox.get_virtual_directory()
        installdir = sandbox_root.open_directory(
            self.get_variable("install-root").lstrip("/"), create=True
        )

        with installdir.open_file(workspace_filename, mode="w") as f:
            # An empty file is good enough
            pass

        with installdir.open_file(build_filename, mode="w") as f:
            for load in sorted(load_stmts):
                print(load, file=f)

            print(visibility_stmt, file=f)

            for target in targets:
                print(target.get_rule_statement(), file=f)

        return self.get_variable("install-root")


def setup():
    return BazelizeElement
