from buildstream._testing import register_repo_kind

from .repo import Git, OSTree, Tar, Zip


# TODO: can we get this from somewhere? pkg_resources?
package_name = "buildstream_plugins_community"


def register_sources():
    register_repo_kind("ostree", OSTree, package_name)
    register_repo_kind("git_tag", Git, package_name)
    register_repo_kind("zip", Zip, package_name)
