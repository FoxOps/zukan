#!/usr/bin/env bash
# Markdown changelog of COMPONENT for release COMPONENT-vVERSION: the commits touching the
# component's files since its previous release (the nearest COMPONENT-v* tag reachable
# from TARGET, default HEAD), merges left out, with a compare link. No previous release:
# every commit. Needs the full history and tags (checkout with fetch-depth: 0).
#
#   scripts/ci/changelog.sh COMPONENT VERSION [TARGET]
set -euo pipefail

component=${1:?component}
version=${2:?version}
target=${3:-HEAD}
# Longer lists are cut (release notes are limited to 125,000 characters).
max=300
case "$component" in
    server) paths=(backend web Dockerfile .dockerignore deploy docker-compose.yml .env.example) ;;
    android) paths=(android) ;;
    *) echo "::error::Unknown component '$component'." >&2; exit 1 ;;
esac
tag="$component-v$version"
repo_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-FoxOps/zukan}"

previous=$(git describe --tags --abbrev=0 --match "$component-v*" --exclude "$tag" "$target" 2>/dev/null || true)
range=${previous:+$previous..}$target
mapfile -t lines < <(git log --no-merges --format='- %s (%h)' "$range" -- "${paths[@]}")

echo "## Changes"
echo
if [ -n "$previous" ]; then
    echo "Since $previous ([full diff]($repo_url/compare/$previous...$tag)):"
else
    echo "First release of this component:"
fi
echo
if [ ${#lines[@]} -eq 0 ]; then
    echo "- No change in this component's files."
else
    printf '%s\n' "${lines[@]:0:$max}"
    if [ ${#lines[@]} -gt "$max" ]; then
        echo "- ... and $((${#lines[@]} - max)) older commits."
    fi
fi
