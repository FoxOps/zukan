#!/usr/bin/env bash
# Create GitHub Release vVERSION, or add to it when another prod build already created
# it (Docker and Android prod builds share one release).
#
#   scripts/ci/release.sh VERSION NOTE [FILE...]
#
# Needs GH_TOKEN with contents: write. The tag is created on TARGET_SHA (the commit the
# prod build ran on), default HEAD.
set -euo pipefail

version=${1:?version}
note=${2:?note}
shift 2
tag="v$version"

if ! gh release view "$tag" >/dev/null 2>&1; then
    gh release create "$tag" --target "${TARGET_SHA:-$(git rev-parse HEAD)}" --title "Fudabako $version" \
        --notes "$note" "$@"
    exit 0
fi
if [ $# -gt 0 ]; then
    gh release upload "$tag" "$@" --clobber
fi
body=$(gh release view "$tag" --json body --jq .body)
if ! grep -qF -- "$note" <<<"$body"; then
    gh release edit "$tag" --notes "$body"$'\n\n'"$note"
fi
