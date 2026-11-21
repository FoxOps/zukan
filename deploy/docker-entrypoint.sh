#!/bin/sh
# Data folders are bind mounts next to the compose file. Docker creates missing ones
# owned by root: hand them to the unprivileged user, then drop root. /data/init holds
# what the first start generates (the first administrator's password).
set -e
if [ "$(id -u)" = 0 ]; then
    mkdir -p /data/images /data/init
    chown tcg:tcg /data/images /data/init
    export HOME=/home/tcg
    exec setpriv --reuid=tcg --regid=tcg --init-groups "$@"
fi
exec "$@"
