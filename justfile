_default: help

# Build the bootstrap module (alias: b)
@build:
    bst build adjusted.bst

[private]
alias b := build

@_untrack:
    [ -f ./project.refs ] && rm ./project.refs || true
    [ -f ./junction.refs ] && rm ./junction.refs || true

# Manually update packages, then track everything (alias: up)
@update: _untrack && track
    tools/manual-updates

[private]
alias up := update

# Track all packages
@track: _untrack
    bst source track bst-plugins.bst
    bst source track bst-plugins-experimental.bst
    bst source track freedesktop-sdk.bst
    bst source track -d all all.bst

# Check out a built bst element
@checkout ELEMENT:
    [ -d result ] && rm -rf result/
    bst --no-strict artifact checkout -d none --no-integrate {{ELEMENT}} --directory result/

# Show this help document
@help:
    echo "carbonOS Bootstrap Build System"
    echo "USAGE: just RECIPE [ARGS...]"    
    echo
    just -lu
