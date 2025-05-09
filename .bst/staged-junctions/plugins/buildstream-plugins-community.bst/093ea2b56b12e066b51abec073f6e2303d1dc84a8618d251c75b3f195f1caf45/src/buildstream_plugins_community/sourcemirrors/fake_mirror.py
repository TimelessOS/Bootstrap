"""
fake_mirror - plugin for using the alias url as a mirror
========================================================

**Usage:**

.. code:: yaml

- name: my-mirror
  kind: fake_mirror
  config:
    aliases:
    - my-alias
    - another-alias

This plugin allows defining a mirror that uses the URL defined in the alias
without repeating the URL. This is useful for URLs that your project controls
and you don't need to mirror. By defining the mirror to be the same URL, you
can use the "mirrors" fetch source configuration to ensure that everything
has a mirror defined.
"""

from posixpath import join
from buildstream import SourceMirror


class FakeMirror(SourceMirror):
    BST_MIN_VERSION = "2.2"

    def configure(self, node):
        node.validate_keys(["aliases"])
        self.set_supported_aliases(node.get_str_list("aliases"))

    def translate_url(self, alias, alias_url, source_url, extra_data):
        translated_url = join(alias_url, source_url)

        return translated_url


def setup():
    return FakeMirror
