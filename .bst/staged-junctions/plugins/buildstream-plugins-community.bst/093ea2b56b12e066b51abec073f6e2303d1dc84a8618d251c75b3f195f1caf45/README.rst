BuildStream Community Plugins
********************************
A collection of community-maintained plugins for BuildStream 2. You can find the docs `here <https://buildstream.gitlab.io/buildstream-plugins-community/>`_.

This repo collects plugins which don't provide the strong API guarantees
required by the
`buildstream-plugins <https://github.com/apache/buildstream-plugins/>`_
project.

How to use this repo
====================

The plugins in this repo do not provide strong API guarantees or backwards
compatibility. You should use a specific commit in your project and update it
manually as needed.

You are recommended to import these plugins into your project using the
`junction plugins <https://docs.buildstream.build/master/format_project.html#junction-plugins>`_
feature of BuildStream 2.0 so you can control exactly what Git commit is used.
Please note that using it this way requires at least BuildStream 2.2.
This is done in several stages documented below:

Using via a junction
~~~~~~~~~~~~~~~~~~~~

First, make sure you have the ``git`` source from
`buildstream-plugins`_
available and declared in your ``project.conf`` file. If you installed
the `PyPI package <https://pypi.org/project/buildstream-plugins/>`_
then you can import it as a
`pip plugin <https://docs.buildstream.build/master/format_project.html#pip-plugins>`_::

    plugins:
    - origin: pip
      package-name: buildstream-plugins
      sources:
      - git

Now, add a
`junction element <https://docs.buildstream.build/master/elements/junction.html#module-elements.junction>`_
referencing this repo. Here's an example you could save as ``buildstream-plugins-community.bst``
in your elements directory::

    kind: junction

    sources:
    - kind: git
      url: https://gitlab.com/BuildStream/buildstream-plugins-community.git
      track: master

You can then run ``bst source track buildstream-plugins-community.bst`` to set the ``ref`` field
appropriately.

Finally you can define specific plugins you want to use in ``project.conf``::

    plugins:
    - origin: junction
      junction: buildstream-plugins-community.bst
      sources:
      - pypi
      elements:
      - pep517


Alternative methods
~~~~~~~~~~~~~~~~~~~

You can use Git's 'submodules' feature to import this repo into your project's
repo, then declare the plugins as
`local plugins <https://docs.buildstream.build/master/format_project.html#local-plugins>`_.

BuildStream also supports
`pip plugins <https://docs.buildstream.build/master/format_project.html#pip-plugins>`_
which are imported from the host Python environment. While
`buildstream-plugins-community <https://pypi.org/project/buildstream-plugins-community/>`_
is available on PyPI, the project does not provide any backwards compatibility
or "semantic versioning" guarantees. Make sure you can control exactly what of
the package version is used if you consume it via Pip.
