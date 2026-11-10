#!/usr/bin/env bash
# Markdown changelog of COMPONENT for release COMPONENT-vVERSION: the commits touching the
# component's files since its previous release (the nearest COMPONENT-v* tag reachable
# from TARGET, default HEAD), merges left out, each with its full message (title, then
# its body indented below; trailers such as Co-Authored-By dropped), with a compare
# link. No previous release: every commit. Needs the full history and tags (checkout
# with fetch-depth: 0).
#
#   scripts/ci/changelog.sh COMPONENT VERSION [TARGET]
set -euo pipefail

component=${1:?component}
version=${2:?version}
target=${3:-HEAD}
# Longer lists are cut (release notes are limited to 125,000 characters, the release
# header included).
max=300
max_chars=120000
case "$component" in
    server) paths=(backend web Dockerfile .dockerignore deploy docker-compose.yml .env.example) ;;
    android) paths=(android) ;;
    *) echo "::error::Unknown component '$component'." >&2; exit 1 ;;
esac
tag="$component-v$version"
repo_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-FoxOps/zukan}"

previous=$(git describe --tags --abbrev=0 --match "$component-v*" --exclude "$tag" "$target" 2>/dev/null || true)
range=${previous:+$previous..}$target
mapfile -t commits < <(git log --no-merges --format='%H' "$range" -- "${paths[@]}")

# One commit: "- title (hash)" then its body, trailers and blank lines dropped, indented
# so its own bullets nest under the title.
entry() {
    git log -1 --format='- %s (%h)' "$1"
    git log -1 --format='%b' "$1" \
        | sed -E '/^[A-Za-z-]+: .+<[^>]+>$/d; /^[[:space:]]*$/d; s/^/  /'
}

echo "## Changes"
echo
if [ -n "$previous" ]; then
    echo "Since $previous ([full diff]($repo_url/compare/$previous...$tag)):"
else
    echo "First release of this component:"
fi
echo
if [ ${#commits[@]} -eq 0 ]; then
    echo "- No change in this component's files."
else
    for commit in "${commits[@]:0:$max}"; do
        entry "$commit"
    done | awk -v max="$max_chars" '
        { size += length($0) + 1 }
        size > max { if (!cut) print "- ... cut, see the full diff."; cut = 1; next }
        { print }'
    if [ ${#commits[@]} -gt "$max" ]; then
        echo "- ... and $((${#commits[@]} - max)) older commits."
    fi
fi
