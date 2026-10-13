#!/bin/sh
# Data folders are bind mounts next to the compose file. Docker creates missing ones
# owned by root: hand them to the unprivileged user, then drop root.
set -e
if [ "$(id -u)" = 0 ]; then
    chown tcg:tcg /data/images
    export HOME=/home/tcg
    exec setpriv --reuid=tcg --regid=tcg --init-groups "$@"
fi
exec "$@"
