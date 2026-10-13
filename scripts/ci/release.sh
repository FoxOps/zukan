#!/usr/bin/env bash
# Create GitHub Release COMPONENT-vVERSION, or update its files when it already exists
# (re-run of the same prod build). The server and the Android app have their own
# versions and releases.
#
#   scripts/ci/release.sh COMPONENT VERSION NOTE [FILE...]
#
# Needs GH_TOKEN with contents: write. The tag is created on TARGET_SHA (the commit the
# prod build ran on), default HEAD.
set -euo pipefail

component=${1:?component}
version=${2:?version}
note=${3:?note}
shift 3
case "$component" in
    server) title="Fudabako server $version" ;;
    android) title="Fudabako Android $version" ;;
    *) echo "::error::Unknown component '$component'."; exit 1 ;;
esac
tag="$component-v$version"

if ! gh release view "$tag" >/dev/null 2>&1; then
    gh release create "$tag" --target "${TARGET_SHA:-$(git rev-parse HEAD)}" --title "$title" \
        --notes "$note" "$@"
    exit 0
fi
if [ $# -gt 0 ]; then
    gh release upload "$tag" "$@" --clobber
fi
gh release edit "$tag" --notes "$note"
