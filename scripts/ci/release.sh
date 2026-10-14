#!/usr/bin/env bash
# Create GitHub Release COMPONENT-vVERSION, or update its files when it already exists
# (re-run of the same prod build). The server and the Android app have their own
# versions and releases.
#
#   scripts/ci/release.sh COMPONENT VERSION NOTE [FILE...]
#   CHANNEL=dev scripts/ci/release.sh COMPONENT dev-BRANCH NOTE [FILE...]
#
# CHANNEL=dev publishes pre-release COMPONENT-dev-BRANCH, deleted and created again on
# each dev build so its tag and files follow the branch.
#
# Needs GH_TOKEN with contents: write. The tag is created on TARGET_SHA (the commit the
# build ran on), default HEAD.
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
target=${TARGET_SHA:-$(git rev-parse HEAD)}

if [ "${CHANNEL:-prod}" = dev ]; then
    tag="$component-$version"
    title="$title (${target:0:7})"
    if gh release view "$tag" >/dev/null 2>&1; then
        gh release delete "$tag" --cleanup-tag --yes
    elif git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null; then
        git push origin ":refs/tags/$tag"
    fi
    gh release create "$tag" --target "$target" --title "$title" --notes "$note" \
        --prerelease --latest=false "$@"
    exit 0
fi
tag="$component-v$version"

if ! gh release view "$tag" >/dev/null 2>&1; then
    gh release create "$tag" --target "$target" --title "$title" \
        --notes "$note" "$@"
    exit 0
fi
if [ $# -gt 0 ]; then
    gh release upload "$tag" "$@" --clobber
fi
gh release edit "$tag" --notes "$note"
