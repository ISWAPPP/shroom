#!/bin/sh
set -eu
cd /srv/hermes-web
docker compose run --rm certbot renew --non-interactive --no-random-sleep-on-renew
if [ -f letsencrypt/.proxy-reload-required ]; then
 docker compose exec -T proxy nginx -t
 docker compose exec -T proxy nginx -s reload
 rm letsencrypt/.proxy-reload-required
fi
