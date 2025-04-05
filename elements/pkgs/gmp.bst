kind: autotools

sources:
- kind: gnu
  name: gmp

build-depends:
- tools/import-fdo.bst
- pkgs/gcc-cross.bst
- pkgs/binutils-cross.bst
- pkgs/glibc.bst
- pkgs/linux-api-headers.bst
- tools/sysroot-setup.bst

environment:
  CC: "%{triplet}-gcc"
  AR: "%{triplet}-ar"
  RANLIB: "%{triplet}-ranlib"

variables:
  build-dir: build
