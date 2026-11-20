# Upgrading

Steps needed by some releases, on top of the usual
`docker compose pull && docker compose up -d`. See also the wiki page
[Updates and migrations](https://github.com/FoxOps/zukan/wiki/Updates-and-migrations).

## Server 0.28.0

This release follows a security audit. It changes the reference `docker-compose.yml`:

- The API and the worker no longer use the PostgreSQL owner role `tcg`. That role is a
  superuser. They now use `zukan_app`, a role that can only read and write data.
- A one-shot `migrate` service runs the database migrations and creates or updates
  `zukan_app`. It is the only service that uses the owner role.
- The port is published on `127.0.0.1` by default instead of every address.

The PostgreSQL image creates roles only when its data folder is empty. An existing
`./data/postgres` is not changed by editing the compose file. The `migrate` service
handles this: it signs in as `tcg` and creates `zukan_app` in the existing database. No
SQL needs to be run by hand.

### Steps

1. **Back up the database.**

   ```sh
   docker compose exec db pg_dump -U tcg tcg > zukan-backup-$(date +%F).sql
   ```

2. **Add the runtime role's password** to `.env`. Use URL-safe characters:

   ```sh
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   ```ini
   TCG_DB_APP_PASSWORD=<the generated value>
   ```

3. **Update `docker-compose.yml`.** Take the new file from the release, or merge these
   changes into your own:
   - the `migrate` service (command `alembic upgrade head && zukan db-roles`, database URL
     with `tcg` and `POSTGRES_PASSWORD`);
   - `api` and `worker`: `TCG_DATABASE_URL` set to
     `postgresql+asyncpg://zukan_app:${TCG_DB_APP_PASSWORD}@db:5432/tcg`;
   - `api`: `depends_on: migrate: condition: service_completed_successfully`;
   - `api` ports: `"${ZUKAN_BIND:-127.0.0.1}:${ZUKAN_PORT:-8000}:8000"`.

4. **Check how the reverse proxy reaches Zukan.**
   - If Caddy runs on the same host, the default `127.0.0.1` binding works.
   - If Caddy runs in a container, attach it to Zukan's network and proxy to `api:8000`.
     The published port can then be removed. Proxying to the host address also works
     with `ZUKAN_BIND=0.0.0.0`.
   - If Caddy runs on another machine, set `ZUKAN_BIND=0.0.0.0` in `.env` and allow only
     the proxy's address through the firewall. Docker's published ports bypass UFW.

5. **SSO with Authentik: let Zukan check sessions again.** Add `offline_access` to the
   provider's scopes in `.env`:

   ```ini
   TCG_OIDC_<NAME>_SCOPES=["openid","profile","email","offline_access"]
   ```

   Then add the `offline_access` scope mapping to the Zukan OAuth2 provider in Authentik.
   Every 15 minutes, web sessions then ask Authentik whether the account is still active
   and in the allowed groups. Groups and the administrator role are synced again at the
   same time. Without it, SSO sessions still end 30 days after sign-in
   (`TCG_SSO_SESSION_MAX_AGE_SECONDS`), but removals in Authentik only apply at that
   point or at the next sign-in.

6. **Start the new version.**

   ```sh
   docker compose pull && docker compose up -d
   docker compose logs migrate   # ends with: Database role 'zukan_app' ready
   ```

7. **Verify.**

   - The runtime role is not a superuser (expected: `rolsuper = f`):

     ```sh
     docker compose exec db psql -U zukan_app -d tcg -c \
       "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user;"
     ```

   - The port is bound to the loopback address only (expected: `127.0.0.1:8000`):
     `docker compose port api 8000`.
   - API answers and exports are not cached: `curl -s -D - -o /dev/null
     https://<your site>/api/health` shows `cache-control: private, no-store`.
   - The web UI has its full policy: `curl -s -D - -o /dev/null https://<your site>/`
     shows `content-security-policy: default-src 'self'; script-src 'self'; ...`.

8. **If a page of the web UI breaks** (blocked script, picture or style), set
   `TCG_CSP_MODE=report` in `.env`, run `docker compose up -d`, and report what the
   browser console lists.

9. **Manual fallback.** If the `migrate` service cannot be used, print the SQL and run it
   once as the owner:

   ```sh
   docker compose run --rm --no-deps -e TCG_DB_APP_PASSWORD=<password> api zukan db-roles --print-sql > roles.sql
   docker compose exec -T db psql -U tcg -d tcg < roles.sql
   ```

   Then point `api` and `worker` at `zukan_app` as in step 3, and run `zukan db-roles`
   again after each upgrade so that tables added later are granted.

### What else changes

- **Sessions.** Open SSO sessions keep working after the upgrade. Each session's start
  time comes from its first sign-in. Sessions that started more than 30 days ago end at
  their next refresh, and the user signs in through the identity provider again. A
  session started before the upgrade is checked again at the provider only after its
  next sign-in. Local accounts are not affected.
- **Android SSO.** An ID token sent by the app gives one session only. The app is
  unchanged.
- **First start on an empty database.** The default administrator `admin` gets a random
  password, written once in the API log, unless `TCG_DEFAULT_ADMIN_PASSWORD` is set. No
  default administrator is created when `TCG_LOCAL_LOGIN_ENABLED=false`.
- **Referrer policy.** Zukan sends `Referrer-Policy: same-origin`. A reverse proxy that
  sets its own header replaces it. For example, a Caddy `header Referrer-Policy
  strict-origin-when-cross-origin` line overrides it. Remove that line to keep Zukan's
  policy.
