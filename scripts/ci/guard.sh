#!/usr/bin/env bash
# Check that a manual build runs from the right branch and compute shared values.
#
#   scripts/ci/guard.sh CHANNEL BRANCH [VERSION]
#
# dev  : any branch except main (quick checks)
# prod : main only, VERSION X.Y.Z required; tag vX.Y.Z must not point at another commit.
# Writes version, version_code, slug and short_sha to $GITHUB_OUTPUT when set.
set -euo pipefail

channel=${1:?channel}
branch=${2:?branch}
version=${3:-}
sha=$(git rev-parse HEAD)
short_sha=${sha:0:7}
fail() { echo "::error::$*"; exit 1; }

case "$channel" in
    dev)
        [ "$branch" != main ] || fail "Dev builds run from a development branch: pick one in 'Use workflow from'."
        version=""
        version_code=""
        ;;
    prod)
        [ "$branch" = main ] || fail "Prod builds run from main only (selected: $branch)."
        [[ "$version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || fail "Prod needs a version X.Y.Z (got '$version')."
        major=${BASH_REMATCH[1]} minor=${BASH_REMATCH[2]} patch=${BASH_REMATCH[3]}
        (( minor < 100 && patch < 100 )) || fail "Minor and patch must be below 100 (Android version code)."
        version_code=$(( major * 10000 + minor * 100 + patch ))
        existing=$(git ls-remote --tags origin "refs/tags/v$version" | cut -f1)
        if [ -n "$existing" ] && [ "$existing" != "$sha" ]; then
            fail "Tag v$version already exists on another commit ($existing)."
        fi
        ;;
    *) fail "Unknown channel '$channel'." ;;
esac

slug=$(echo "$branch" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-40)
echo "channel=$channel branch=$branch slug=$slug sha=$short_sha version=${version:-none}"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
        echo "version=$version"
        echo "version_code=$version_code"
        echo "slug=$slug"
        echo "short_sha=$short_sha"
    } >> "$GITHUB_OUTPUT"
fi
