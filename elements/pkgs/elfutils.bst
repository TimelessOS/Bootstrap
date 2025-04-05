kind: autotools

sources:
- kind: git
  url: sourceware:elfutils.git
  track: elfutils-0.192

depends:
- pkgs/glibc.bst
- pkgs/zlib.bst
- pkgs/flex.bst

build-depends:
- tools/toolchain.bst

variables:
  conf-local: >-
    --disable-debuginfod
    --disable-libdebuginfod
    --enable-maintainer-mode
