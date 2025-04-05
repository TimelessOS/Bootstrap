kind: autotools

sources:
- kind: git_tag
  url: github:pkgconf/pkgconf

build-depends:
- tools/toolchain.bst

variables:
  pconf-dirs: "%{libdir}/pkgconfig:%{datadir}/pkgconfig"
  system-pconf-dirs: "/usr/lib/pkgconfig:/usr/share/pkgconfig"
  conf-local: >-
    --with-pkg-config-dir=%{system-pconf-dirs}:%{pconf-dirs}

config:
  install-commands:
    (>):
    - ln -sv pkgconf %{install-root}%{bindir}/pkg-config
