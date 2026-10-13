#!/usr/bin/env bash
# Create GitHub Release vVERSION on the current commit, or add to it when another
# pipeline already created it (Docker and Android prod runs share one release).
#
#   scripts/ci/release.sh VERSION NOTE [FILE...]
#
# Needs GH_TOKEN with contents: write.
set -euo pipefail

version=${1:?version}
note=${2:?note}
shift 2
tag="v$version"

if ! gh release view "$tag" >/dev/null 2>&1; then
    gh release create "$tag" --target "$(git rev-parse HEAD)" --title "Fudabako $version" \
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
