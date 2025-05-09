# Copyright (c) 2019 Codethink Ltd.
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
#        Valentin David <valentin.david@codethink.co.uk>

"""Builds a OCI or Docker image files

Configuration
=============

::

  mode: docker

Valid ``mode`` values are ``oci`` or ``docker``. ``oci`` will output
an OCI image according to the "Image Format Specification"[1]_ at the
time of this plugin was made. `docker` will output Docker images
according to "Docker Image Specification v1.2.0"[2]_.

.. [1] https://github.com/opencontainers/image-spec/blob/master/spec.md
.. [2] https://github.com/moby/moby/blob/master/image/spec/v1.2.md

::

  gzip: True if mode == oci else False

Whether layer should be compressed. When layer is created, this plugin
will need to crawl files from upper layers to see if they exist as part
of deduplication. To optimize creation of layers and avoid decompression
of upper layers, compression can be disabled.

::

  annotations:
    key1: value1

Optional. Only for OCI.

::

  images:
  - ...

Contains a series of images. Not to mix up with layers. Images do not
need to share layers. For example there may be an image for each
architecture.

The configuration of an image contains the following fields:

Image configuration
-------------------

::

  parent:
    element: other-image.bst
    image: 0

``parent`` is optional. If not provided, we are building an image with only
one layer. ``element`` is the build dependency of type ``oci`` which contains
the layers we want to import. ``image`` is the image index number. Default
value for ``image`` is 0.

::

  layer: mylayer.bst

``layer`` is a build dependency which provides the top
layer. Integration commands are not run. So you may want to use depend
on ``compose`` element to run those. `layer` is optional. If not
provided, parent layers will be just used and new configuration will
be set on an empty layer.

::

  architecture: amd64

Must be provided. Must be a "``GOARCH``" value.
https://github.com/golang/go/blob/master/src/go/build/syslist.go

::

  os: linux

Must be provided. Must be a "``GOOS``" value.
https://github.com/golang/go/blob/master/src/go/build/syslist.go

::

  variant: v8
  os.version: 1
  os.features: ['a', 'b']

OCI only. Optional. Only used in image index for selection of the
right image. ``os.version`` and ``os.features`` are Windows related.
``variant`` are for selection of processor variants. For example ARM
version.

::

  author: John Doe <john.doe@example.com>

Author of the layer/image. Optional.

::

  comment: Add my awesome app

Commit message for the layer/image. Optional.

::

  annotations: {'key1': 'value1'}

Optional. Only for OCI.

::

  tags: ['myapp:latest', 'myapp:1.0']

Tags for the images. Only for Docker.

::

  config:
    ...

Optional container config for the image.

Container configuration
-----------------------

All configurations here are optional.

Examples common for OCI and Docker:

::

  User: "webadmin"
  ExposedPorts: ["80/tcp", "8080"]
  Env: ["A=value", "B=value"]
  Entrypoint: ["/bin/myapp"]
  Cmd: ["--default-param"]
  Volumes: ["/var/lib/myapp"]
  WorkingDir: "/home/myuser"

OCI specific:

::

  Labels: {"a": "b"}
  StopSignal: "SIGKILL"

Docker specific:

::

  Memory: 2048
  MemorySwap: 4096
  CpuShares: 2
  Healthcheck:
    Test: ["CMD", "/bin/test", "param"]
    Interval: 50000000000
    Timeout: 10000000000
    Retries: 2

Usage
=====

The artifact generated is an un-tared image and need to be composed
into at tar file. This can be done with ``--tar`` of ``bst checkout``.

The image can be loaded by either ``podman load -i`` or ``docker load -i``.

For example:

::

  bst checkout element.bst --tar element.tar
  podman load -i element.tar

Notes
=====

The element will compute the layering on top of its parents. So the
layer should be provided complete with all the files of the result.

There is no creation dates added to the images to avoid problems with
reproducibility.

Each ``oci`` element can only add one layer. So if you need to build
multiple layers, you must provide an ``oci`` element for each. Remember
that only ``os`` and ``architecture`` are required, so you can make
relatively concise elements.

You can layer OCI on top of Docker images or Docker images on top of
OCI.  So no need to create both versions for images you use for
creating intermediate layers that do not need to be exported.

"""

import os
import tempfile
import tarfile
import hashlib
import gzip
import json
import codecs
import shutil
from contextlib import contextmanager, ExitStack

from buildstream import Element, ElementError, FileType, FastEnum


class Mode(FastEnum):
    DOCKER = "docker"
    OCI = "oci"


class blob:
    def __init__(
        self,
        root,
        media_type=None,
        text=False,
        mode=Mode.OCI,
        legacy_config=None,
    ):
        self.root = root
        self.descriptor = None
        self.media_type = media_type
        self.text = text
        self.mode = mode
        self.path = None
        self.legacy_config = {}
        if legacy_config:
            self.legacy_config.update(legacy_config)
        self.legacy_id = None

    @contextmanager
    def create(self):
        while True:
            # This is in a private sandbox without concurrent access.
            tempname = os.urandom(8).hex()
            if not self.root.exists(tempname):
                break
        try:
            with self.root.open_file(tempname, mode="x+b") as f:
                if self.text:
                    yield codecs.getwriter("utf-8")(f)
                else:
                    yield f
                self.descriptor = {}
                if self.media_type:
                    self.descriptor["mediaType"] = self.media_type
                f.seek(0, 2)
                self.descriptor["size"] = f.tell()
                f.seek(0)
                h = hashlib.sha256()
                while True:
                    data = f.read(16 * 1204)
                    if not data:
                        break
                    h.update(data)
                if self.mode == Mode.OCI:
                    self.descriptor["digest"] = "sha256:{}".format(
                        h.hexdigest()
                    )
                    self.path = ["blobs", "sha256", h.hexdigest()]
                else:
                    assert self.mode == "docker"
                    if self.media_type.endswith("+json"):
                        self.path = ["{}.json".format(h.hexdigest())]
                        self.descriptor = "{}.json".format(h.hexdigest())
                    elif self.media_type.startswith(
                        "application/vnd.oci.image.layer.v1.tar"
                    ):
                        blobdir = self.root.open_directory(
                            h.hexdigest(), create=True
                        )
                        self.path = [h.hexdigest(), "layer.tar"]
                        with blobdir.open_file("VERSION", mode="w") as f:
                            f.write("1.0")
                        self.legacy_config["id"] = h.hexdigest()
                        self.legacy_id = h.hexdigest()
                        with blobdir.open_file(
                            "json",
                            mode="w",
                        ) as f:
                            json.dump(self.legacy_config, f)
                        self.descriptor = os.path.join(
                            h.hexdigest(), "layer.tar"
                        )
                    else:
                        assert False
            self.root.open_directory(*self.path[:-1], create=True)
            self.root.rename([tempname], self.path)
        except Exception:
            if self.root.exists(tempname):
                self.root.remove(tempname)
            raise


class OciElement(Element):
    BST_MIN_VERSION = "2.0"

    def configure(self, node):
        node.validate_keys(["mode", "gzip", "images", "annotations"])

        self.mode = node.get_enum("mode", Mode, Mode.OCI)
        self.gzip = node.get_bool("gzip", self.mode == Mode.OCI)

        if "annotations" not in node:
            self.annotations = None
        else:
            self.annotations = {}
            annotations = node.get_mapping("images")
            for k, value in annotations.items():
                v = self.node_subst_vars(value)
                self.annotations[k] = v

        self.images = []
        for image in node.get_sequence("images"):
            image.validate_keys(
                [
                    "parent",
                    "layer",
                    "architecture",
                    "variant",
                    "os",
                    "os.version",
                    "os.features",
                    "author",
                    "comment",
                    "config",
                    "annotations",
                ]
                + (["tags"] if self.mode == "docker" else [])
            )
            parent = image.get_mapping("parent", None)
            image_value = {}
            if parent:
                parent.validate_keys(["element", "image"])

                parent = {
                    "element": parent.get_str("element"),
                    "image": parent.get_int("image", 0),
                }

                image_value["parent"] = parent
            if "layer" in image:
                image_value["layer"] = self.node_subst_sequence_vars(
                    image.get_sequence("layer")
                )

            image_value["architecture"] = self.node_subst_vars(
                image.get_scalar("architecture")
            )

            if "tags" in image:
                image_value["tags"] = self.node_subst_sequence_vars(
                    image.get_sequence("tags")
                )

            image_value["os"] = self.node_subst_vars(image.get_scalar("os"))

            if "os.version" in image:
                image_value["os.version"] = self.node_subst_vars(
                    image.get_scalar("os.version")
                )
            if "os.features" in image:
                image_value["os.features"] = self.node_subst_sequence_vars(
                    image.get_sequence("os.features")
                )
            if "os.features" in image:
                image_value["variant"] = self.node_subst_vars(
                    image.get_scalar("variant")
                )

            if "author" in image:
                image_value["author"] = self.node_subst_vars(
                    image.get_scalar("author")
                )

            if "comment" in image:
                image_value["comment"] = self.node_subst_vars(
                    image.get_scalar("comment")
                )

            if "config" in image:
                config = image.get_mapping("config")

                common_config = [
                    "User",
                    "ExposedPorts",
                    "Env",
                    "Entrypoint",
                    "Cmd",
                    "Volumes",
                    "WorkingDir",
                ]
                docker_config = [
                    "Memory",
                    "MemorySwap",
                    "CpuShares",
                    "Healthcheck",
                ]
                oci_config = ["Labels", "StopSignal"]

                config.validate_keys(
                    common_config
                    + (docker_config if self.mode == "docker" else oci_config)
                )

                config_value = {}
                for member in ["User", "WorkingDir", "StopSignal"]:
                    if member in config:
                        config_value[member] = self.node_subst_vars(
                            config.get_scalar(member)
                        )

                for member in ["Memory", "MemorySwap", "CpuShares"]:
                    if member in config:
                        config_value[member] = int(
                            self.node_subst_vars(config.get_scalar(member))
                        )

                for member in [
                    "ExposedPorts",
                    "Volumes",
                    "Env",
                    "Entrypoint",
                    "Cmd",
                ]:
                    if member in config:
                        config_value[member] = self.node_subst_sequence_vars(
                            config.get_sequence(member)
                        )

                if "Labels" in config:
                    labels = config.get_mapping("Labels")
                    config_value["Labels"] = {}
                    for k, v in labels.items():
                        config_value["Labels"][k] = v

                if "Healthcheck" in config:
                    healthcheck = config.get_mapping("Healthcheck")
                    healthcheck.validate_keys(
                        ["Test", "Interval", "Timeout", "Retries"]
                    )
                    config_value["Healthcheck"] = {}
                    if "Test" in healthcheck:
                        config_value["Healthcheck"][
                            "Test"
                        ] = self.node_subst_sequence_vars(
                            healthcheck.get_sequence("Test")
                        )
                    for member in ["Interval", "Timeout", "Retries"]:
                        if member in healthcheck:
                            config_value["Healthcheck"][member] = int(
                                self.node_subst_sequence_vars(
                                    healthcheck.get_scalar(member)
                                )
                            )

                image_value["config"] = config_value
            if "annotations" in image:
                image_value["annotations"] = {}
                annotations = image.get_mapping("annotations")
                for k, value in annotations.items():
                    v = self.node_subst_vars(value)
                    image_value["annotations"][k] = v

            self.images.append(image_value)

    def preflight(self):
        pass

    def get_unique_key(self):
        return {
            "annotations": self.annotations,
            "images": self.images,
            "gzip": self.gzip,
        }

    def configure_sandbox(self, sandbox):
        pass

    def stage(self, sandbox):
        pass

    def _build_image(self, sandbox, image, root, output):
        if root.exists("parent_checkout"):
            root.remove("parent_checkout", recursive=True)
        parent_checkout = root.open_directory("parent_checkout", create=True)

        layer_descs = []
        layer_files = []
        diff_ids = []
        history = None
        legacy_parent = None

        config = {}
        if "author" in image:
            config["author"] = image["author"]
        config["architecture"] = image["architecture"]
        config["os"] = image["os"]
        if "config" in image:
            config["config"] = {}
            for k, v in image["config"].items():
                if k in ["ExposedPorts", "Volumes"]:
                    config["config"][k] = {}
                    for value in v:
                        config["config"][k][value] = {}
                else:
                    config["config"][k] = v

        if "parent" in image:
            if root.exists("parent"):
                root.remove("parent", recursive=True)
            parent = root.open_directory("parent", create=True)
            parent_dep = self.search(image["parent"]["element"])
            if not parent_dep:
                raise ElementError(
                    "{}: Element not in dependencies: {}".format(
                        self, image["parent"]["element"]
                    )
                )

            parent_dep.stage_dependency_artifacts(sandbox, path="parent")
            if not parent.exists("index.json"):
                with parent.open_file(
                    "manifest.json",
                    mode="r",
                ) as f:
                    parent_index = json.load(f)
                parent_image = parent_index[image["parent"]["image"]]
                layers = parent_image["Layers"]

                with parent.open_file(
                    *parent_image["Config"].split("/"), mode="r"
                ) as f:
                    image_config = json.load(f)
                diff_ids = image_config["rootfs"]["diff_ids"]

                if "history" in image_config:
                    history = image_config["history"]

                for i, layer in enumerate(layers):
                    _, diff_id = diff_ids[i].split(":", 1)
                    with parent.open_file(
                        *layer.split("/"), mode="rb"
                    ) as origblob:
                        if self.gzip:
                            targz_blob = blob(
                                output,
                                media_type="application/vnd.oci.image.layer.v1.tar+gzip",
                                mode=self.mode,
                            )
                            with targz_blob.create() as gzipfile:
                                with gzip.GzipFile(
                                    filename=diff_id,
                                    fileobj=gzipfile,
                                    mode="wb",
                                    mtime=1320937200,
                                ) as gz:
                                    shutil.copyfileobj(origblob, gz)
                            layer_descs.append(targz_blob.descriptor)
                            layer_files.append(targz_blob.path)
                            legacy_parent = tar_blob.legacy_id
                        else:
                            legacy_config = {"os": image["os"]}
                            if legacy_parent:
                                legacy_config["parent"] = legacy_parent
                            tar_blob = blob(
                                output,
                                media_type="application/vnd.oci.image.layer.v1.tar",
                                mode=self.mode,
                            )
                            with tar_blob.create() as newfile:
                                shutil.copyfileobj(origblob, newfile)
                            layer_descs.append(tar_blob.descriptor)
                            layer_files.append(tar_blob.path)
                            legacy_parent = tar_blob.legacy_id
            else:
                with parent.open_file("index.json", mode="r") as f:
                    parent_index = json.load(f)
                parent_image_desc = parent_index["manifests"][
                    image["parent"]["image"]
                ]
                algo, h = parent_image_desc["digest"].split(":", 1)
                with parent.open_file(
                    "blobs", *algo.split("/"), *h.split("/"), mode="r"
                ) as f:
                    image_manifest = json.load(f)
                algo, h = image_manifest["config"]["digest"].split(":", 1)
                with parent.open_file(
                    "blobs", *algo.split("/"), *h.split("/"), mode="r"
                ) as f:
                    image_config = json.load(f)
                diff_ids = image_config["rootfs"]["diff_ids"]
                if "history" in image_config:
                    history = image_config["history"]
                for i, layer in enumerate(image_manifest["layers"]):
                    _, diff_id = diff_ids[i].split(":", 1)
                    algo, h = layer["digest"].split(":", 1)
                    origfile = ["blobs", *algo.split("/"), *h.split("/")]
                    with ExitStack() as e:
                        if "layer" not in image and i + 1 == len(
                            image_manifest["layers"]
                        ):
                            # The case were we do not add a layer, the last imported layer has to be fully reconfigured
                            legacy_config = {}
                            legacy_config.update(config)
                            if legacy_parent:
                                legacy_config["parent"] = legacy_parent
                        else:
                            legacy_config = {"os": image["os"]}
                        if legacy_parent:
                            legacy_config["parent"] = legacy_parent
                        if self.gzip:
                            output_blob = blob(
                                output,
                                media_type="application/vnd.oci.image.layer.v1.tar+gzip",
                                mode=self.mode,
                            )
                        else:
                            output_blob = blob(
                                output,
                                media_type="application/vnd.oci.image.layer.v1.tar",
                                mode=self.mode,
                                legacy_config=legacy_config,
                            )
                        outp = e.enter_context(output_blob.create())
                        inp = e.enter_context(
                            parent.open_file(*origfile, mode="rb")
                        )
                        if layer["mediaType"].endswith("+gzip"):
                            if self.gzip:
                                shutil.copyfileobj(inp, outp)
                            else:
                                gz = e.enter_context(
                                    gzip.open(filename=inp, mode="rb")
                                )
                                shutil.copyfileobj(gz, outp)
                        else:
                            if self.gzip:
                                gz = e.enter_context(
                                    gzip.GzipFile(
                                        filename=diff_id,
                                        fileobj=outp,
                                        mode="wb",
                                        mtime=1320937200,
                                    )
                                )
                                shutil.copyfileobj(inp, gz)
                            else:
                                shutil.copyfileobj(inp, outp)

                    layer_descs.append(output_blob.descriptor)
                    layer_files.append(output_blob.path)
                    legacy_parent = output_blob.legacy_id

        if "parent" in image and "layer" in image:
            unpacked = False
            if isinstance(parent_dep, OciElement):
                # Here we read the parent configuration to checkout
                # the artifact which is much faster than unpacking the tar
                # files.
                layers = []
                parent_image = image["parent"]["image"]
                for layer in parent_dep.images[parent_image]["layer"]:
                    layer_dep = parent_dep.search(layer)
                    if not layer_dep:
                        raise ElementError(
                            "{}: Element not in dependencies: {}".format(
                                parent_dep, layer
                            )
                        )

                    # We need to verify dependencies. If not in current
                    # element's dependencies, then we cannnot safely assume
                    # it is cached. Parent could be cached while its
                    # dependencies either removed or not pulled.
                    if layer_dep != self.search(layer):
                        self.warn(
                            "In order to optimize building of {}, you should add {} as build dependency".format(
                                self.name, layer
                            )
                        )
                        layers = None
                        break

                    layers.append(layer_dep)
                if layers is not None:
                    with self.timed_activity(
                        "Checking out layer from {}".format(parent_dep.name)
                    ):
                        for layer_dep in layers:
                            layer_dep.stage_dependency_artifacts(
                                sandbox, path="parent_checkout"
                            )
                        unpacked = True

            if not unpacked:
                for layer in layer_files:
                    if self.gzip:
                        mode = "r:gz"
                    else:
                        mode = "r:"
                    with self.timed_activity(
                        "Decompressing layer {}".format(layer)
                    ):
                        with output.open_file(
                            layer, mode="rb"
                        ) as f, tarfile.open(fileobj=f, mode=mode) as t:
                            members = []
                            for info in t.getmembers():
                                if "/../" in info.name:
                                    continue
                                if info.name.startswith("../"):
                                    continue

                                dirname, basename = os.path.split(info.name)
                                if basename == ".wh..wh..opq":
                                    # Replace with empty directory
                                    parent_checkout.remove(
                                        *dirname.split("/"), recursive=True
                                    )
                                    parent_checkout.open_directory(
                                        *dirname.split("/"), create=True
                                    )
                                elif basename.startswith(".wh."):
                                    parent_checkout.remove(
                                        *dirname.split("/"),
                                        basename[4:],
                                        recursive=True,
                                    )
                                else:
                                    members.append(info)

                            t.extractall(path=parent_checkout, members=members)

        legacy_config = {}
        legacy_config.update(config)
        if legacy_parent:
            legacy_config["parent"] = legacy_parent

        if "layer" in image:
            for name in image["layer"]:
                dep = self.search(name)
                dep.stage_dependency_artifacts(sandbox, path="layer")

            layer = root.open_directory("layer")
            with self.timed_activity("Transforming into layer"):

                def create_whiteouts(parentdir, layerdir):
                    for f in parentdir:
                        if not layerdir.exists(f):
                            with layerdir.open_file(".wh." + f, mode="w"):
                                pass
                        elif parentdir.isdir(f) and layerdir.isdir(f):
                            # Recurse into subdirectory
                            create_whiteouts(
                                parentdir.open_directory(f),
                                layerdir.open_directory(f),
                            )

                create_whiteouts(parent_checkout, layer)

                if "parent" in image:

                    def remove_duplicates(parentdir, layerdir):
                        for f in list(layerdir):
                            if not parentdir.exists(f):
                                pass
                            elif parentdir.isdir(f) and layerdir.isdir(f):
                                # Recurse into subdirectory
                                remove_duplicates(
                                    parentdir.open_directory(f),
                                    layerdir.open_directory(f),
                                )
                            else:
                                old_st = parentdir.stat(f)
                                new_st = layerdir.stat(f)
                                if old_st != new_st:
                                    continue

                                if old_st.file_type == FileType.SYMLINK:
                                    if parentdir.readlink(
                                        f
                                    ) == layerdir.readlink(f):
                                        layerdir.remove(f)
                                else:
                                    if parentdir.file_digest(
                                        f
                                    ) == layerdir.file_digest(f):
                                        layerdir.remove(f)

                    remove_duplicates(parent_checkout, layer)

            with tempfile.TemporaryFile(mode="w+b") as tfile:
                with tarfile.open(fileobj=tfile, mode="w:") as t:
                    with self.timed_activity("Building layer tar"):
                        layer.export_to_tar(t, "")
                tfile.seek(0)
                tar_hash = hashlib.sha256()
                with self.timed_activity("Hashing layer"):
                    while True:
                        data = tfile.read(16 * 1024)
                        if not data:
                            break
                        tar_hash.update(data)
                tfile.seek(0)
                if self.gzip:
                    targz_blob = blob(
                        output,
                        media_type="application/vnd.oci.image.layer.v1.tar+gzip",
                        mode=self.mode,
                    )
                    with self.timed_activity("Compressing layer"):
                        with targz_blob.create() as gzipfile:
                            with gzip.GzipFile(
                                filename=tar_hash.hexdigest(),
                                fileobj=gzipfile,
                                mode="wb",
                                mtime=1320937200,
                            ) as gz:
                                shutil.copyfileobj(tfile, gz)
                    layer_descs.append(targz_blob.descriptor)
                else:
                    copied_blob = blob(
                        output,
                        media_type="application/vnd.oci.image.layer.v1.tar",
                        mode=self.mode,
                        legacy_config=legacy_config,
                    )
                    with copied_blob.create() as copiedfile:
                        shutil.copyfileobj(tfile, copiedfile)
                    layer_descs.append(copied_blob.descriptor)
                    legacy_parent = copied_blob.legacy_id

            diff_ids.append("sha256:{}".format(tar_hash.hexdigest()))

        if not history:
            history = []
        hist_entry = {}
        if "layer" not in image:
            hist_entry["empty_layer"] = True
        if "author" in image:
            hist_entry["author"] = image["author"]
        if "comment" in image:
            hist_entry["comment"] = image["comment"]
        history.append(hist_entry)

        config["rootfs"] = {"type": "layers", "diff_ids": diff_ids}
        config["history"] = history
        config_blob = blob(
            output,
            media_type="application/vnd.oci.image.config.v1+json",
            text=True,
            mode=self.mode,
        )
        with config_blob.create() as configfile:
            json.dump(config, configfile)

        if self.mode == "docker":
            manifest = {
                "Config": config_blob.descriptor,
                "Layers": layer_descs,
            }
            legacy_repositories = {}
            if "tags" in image:
                manifest["RepoTags"] = image["tags"]
                for tag in image["tags"]:
                    name, version = tag.split(":", 1)
                    if name not in legacy_repositories:
                        legacy_repositories[name] = {}
                    legacy_repositories[name][version] = legacy_parent

            return manifest, legacy_repositories
        else:
            manifest = {"schemaVersion": 2}
            manifest["layers"] = layer_descs
            manifest["config"] = config_blob.descriptor
            if "annotations" in image:
                manifest["annotations"] = image["annotations"]
            manifest_blob = blob(
                output,
                media_type="application/vnd.oci.image.manifest.v1+json",
                text=True,
            )
            with manifest_blob.create() as manifestfile:
                json.dump(manifest, manifestfile)
            platform = {
                "os": image["os"],
                "architecture": image["architecture"],
            }
            if "os.version" in image:
                platform["os.version"] = image["os.version"]
            if "os.features" in image:
                platform["os.features"] = image["os.features"]
            if "variant" in image:
                platform["variant"] = image["variant"]
            manifest_blob.descriptor["platform"] = platform
            return manifest_blob.descriptor, {}

    def assemble(self, sandbox):
        root = sandbox.get_virtual_directory()
        output = root.open_directory("output", create=True)

        manifests = []
        legacy_repositories = {}

        image_counter = 1
        for image in self.images:
            with self.timed_activity(
                "Creating image {}".format(image_counter)
            ):
                manifest, legacy_repositories_part = self._build_image(
                    sandbox, image, root, output
                )
                manifests.append(manifest)
                legacy_repositories.update(legacy_repositories_part)

            image_counter += 1

        if self.mode == "docker":
            with output.open_file("manifest.json", mode="w") as f:
                json.dump(manifests, f)
            with output.open_file("repositories", mode="w") as f:
                json.dump(legacy_repositories, f)
        else:
            index = {"schemaVersion": 2}
            index["manifests"] = manifests
            if self.annotations:
                index["annotations"] = self.annotations

            with output.open_file("index.json", mode="w") as f:
                json.dump(index, f)

            oci_layout = {"imageLayoutVersion": "1.0.0"}
            with output.open_file("oci-layout", mode="w") as f:
                json.dump(oci_layout, f)

        return "output"


def setup():
    return OciElement
