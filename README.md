# Fudabako (札箱)

*Fudabako* means "card box" in Japanese.

Self-hosted trading card game collection manager: Magic: The Gathering, Pokémon TCG and
Sorcery, with a plugin system for more games, and an Android scanner app.
See [PLAN.md](PLAN.md) for the full design and progress.

## Run with Docker

`docker-compose.yml` runs the images built by CI from `ghcr.io/foxops/fudabako`. The
package is private: log in once with a GitHub token that has `read:packages`.

```sh
cp .env.example .env          # set POSTGRES_PASSWORD and TCG_SECRET_KEY
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
docker compose pull && docker compose up -d
```

First start creates the administrator **`admin`** / **`changeme`**
(`TCG_DEFAULT_ADMIN_USERNAME` / `TCG_DEFAULT_ADMIN_PASSWORD` in `.env`). Sign in and change
the password from the account page. The account is only created while the database has no
user. Reset or add an administrator any time:
`docker compose exec -e TCG_ADMIN_PASSWORD=... api fudabako create-admin NAME`.

Data is stored next to the compose file, not in Docker volumes: `./data/postgres`
(database) and `./data/images` (card image cache); the dev compose uses `./data-dev`.
Back up these folders.

All configuration lives in `.env`: `.env.example` documents every variable (only the
two above are mandatory; the rest is commented out with its default). Serving the web
UI over plain HTTP (no TLS)? Set `TCG_COOKIE_SECURE=false` or web sign-in will not stick.

Update: `docker compose pull && docker compose up -d` (migrations run on start).
`FUDABAKO_TAG` in `.env` pins a version (`0.1.0`) or tries a dev build (`dev-<branch>`).
To build from this checkout instead: `docker compose -f docker-compose-dev.yml up -d --build`
(separate project `fudabako-dev`, with an optional Keycloak for SSO tests).

API docs: `http://localhost:8000/api/docs`. SSO setup: [docs/sso.md](docs/sso.md).

The `worker` service syncs catalogs weekly (`TCG_CATALOG_INTERVAL_HOURS`) and prices and
images daily (`TCG_SYNC_INTERVAL_HOURS`). Run a job now:
`docker compose exec api fudabako sync mtg [--kind catalog|prices|images]`.
The first sync of each game takes a while: MTG streams Scryfall's ~400 MB `all_cards`
file, Pokémon fetches every card from TCGdex one by one.

### Prices

Cardmarket has no public API, so prices come from the card data APIs: Scryfall for MTG
(Cardmarket trend price) and TCGdex for Pokémon (Cardmarket trend, low and average).
Sorcery has no price source: set prices by hand on collection items. Price history is
kept for cards somebody owns; other cards only keep their latest price.

### Card images

Images are cached under `./data/images`: downloaded on first view, and pre-fetched
for cards somebody owns. Sorcery images are not downloadable from its API; download the
[public image folder](https://drive.google.com/drive/folders/17IrJkRGmIU9fDSTU2JQEU9JlFzb5liLJ)
from Google Drive, unzip it into `./import/sorcery`, then run
`docker compose exec api fudabako import-images sorcery /data/import/sorcery`
(or use the admin import endpoint `POST /api/admin/images/sorcery/import`).

### Collection and CSV

Stock is tracked per printing, finish, condition and language (`/api/collection`). Every
change is recorded and can be undone. Unit price: manual price when set, else the latest
API price of the printing and finish.

CSV export/import (`/api/collection/export.csv`, `POST /api/collection/import`) uses:

```
game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes
mtg,DOM,168,Llanowar Elves,fr,foil,NM,2,,
```

`collector_number` is the provider printing id for games without numbers (Sorcery, e.g.
`abundance-b`). Commas, semicolons or tabs work as separators. Imports are all or nothing:
any invalid row is reported and nothing is imported. `mode=add` (default) adds the
quantities, `mode=set` makes stored quantities equal to the file; `dry_run=true` only checks.

### Card scanning API

The Android app sends the text it recognizes on a card to `POST /api/scan/identify`:

```json
{"game": "mtg", "lines": [{"text": "Elfes de Llanowar"}, {"text": "168/269 C"},
                          {"text": "DOM • FR Chris Rahn", "left": 0.05, "top": 0.95}]}
```

`game` is optional (all games are tried) and line boxes are optional fractions of the
card size. Each game plugin reads the name, set code, collector number and language
(`parse_ocr`); the server matches set code + number first (works for Japanese, Korean
and Chinese cards), then number + similar name, then fuzzy names in every language.
Candidates come back with their printings (most likely first), prices and the user's
copies, ready for "add" or "remove".

## Android app

`android/` is the scanner app (Kotlin, Jetpack Compose, CameraX, ML Kit text
recognition with bundled Latin, Japanese, Chinese and Korean models, AppAuth for SSO).

- Log in with the server address and a local account, or an SSO provider that has a
  `mobile_client_id` (public client, redirect `fr.fudabako.app:/oauth2redirect`, see
  [docs/sso.md](docs/sso.md)).
- Point the camera at a card: once the text is steady, the app asks the server, shows the
  card, its printings, prices and owned copies; pick finish, condition, language and
  quantity, then Add or Remove (with Undo). Search covers cards that cannot be scanned.
- Settings: text recognition script, default condition and language.
- Plain HTTP servers are accepted for home networks (the app warns); prefer HTTPS.

Build (JDK 21 and the Android SDK, platform 37):

```sh
cd android
echo "sdk.dir=$HOME/Android/Sdk" > local.properties
./gradlew testDebugUnitTest assembleDebug   # app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

For a release build, create a signing key and add a `signingConfigs` block (or sign
`app-release-unsigned.apk` with `apksigner`).

## CI and releases

GitHub Actions workflows, all started by hand (Actions tab, "Run workflow"), except the
release which follows successful prod builds:

| Workflow | Runs from | Does |
|---|---|---|
| Docker dev | any branch but main | ruff, smoke tests (`pytest -m smoke`), type check, container smoke test; pushes `dev-<branch>` and `dev-<branch>-<sha>` (amd64) |
| Docker prod | main, server version `X.Y.Z` | ruff + format, migrations check, all tests, web lint/build, API types check, container smoke test; pushes `latest`, `X.Y.Z`, `sha-<sha>` (amd64 + arm64) |
| Android dev | any branch but main | unit tests, "Fudabako dev" debug APK as artifact |
| Android prod | main, app version `X.Y.Z` | lint, unit tests, signed R8 release APK |
| Release | after a successful prod build | publishes GitHub Release `server-vX.Y.Z` (Docker tag) or `android-vX.Y.Z` (APK, R8 mapping) |

The branch is chosen with "Use workflow from"; dev workflows refuse main and prod
workflows refuse anything else. The server and the Android app have independent
versions: an app fix ships a new `android-v*` release without a new server version, and
the other way round. Shared steps live in `_checks.yml` and
`_docker-image.yml` (reusable workflows, not started directly).

From the command line:

```sh
gh workflow run docker-dev.yml --ref my-branch
gh workflow run docker-prod.yml --ref main -f version=0.3.0
gh workflow run android-prod.yml --ref main -f version=0.2.1
```

The dev app (`fr.fudabako.app.dev`) installs next to the released one. Both are signed
with the release key stored in the `ANDROID_KEYSTORE_*` secrets, so updates install over
each other. Keep a backup of that keystore: without it the app cannot be updated.

## Backend development

```sh
cd backend
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
docker run -d --name tcg-pg-dev -e POSTGRES_USER=tcg -e POSTGRES_PASSWORD=tcg \
  -e POSTGRES_DB=tcg -p 5432:5432 postgres:17
docker exec tcg-pg-dev psql -U tcg -c "CREATE DATABASE tcg_test"
.venv/bin/alembic upgrade head
.venv/bin/pytest
TCG_SECRET_KEY=$(openssl rand -hex 32) TCG_COOKIE_SECURE=false .venv/bin/uvicorn app.main:app --reload
```

## Web UI development

React + TypeScript + Vite, Tailwind CSS v4 with daisyUI 5, `@tailwindcss/typography`,
`@tailwindcss/forms` (class strategy) and `tailwindcss-animate`. 3D card flips use
Tailwind v4's built-in 3D utilities (`tailwindcss-3d` only supports Tailwind 3).

```sh
cd web
npm install
npm run dev        # http://localhost:5173, proxies /api to the backend on :8000
npm run gen:api    # regenerate src/api/schema.d.ts after backend API changes
npm run build      # dist/ is served by the backend at / (TCG_WEB_DIR)
```

Run the backend with `TCG_PUBLIC_URL=http://localhost:5173` during UI development so
SSO redirects come back to the Vite server.

### Adding a game

Implement `app.games.base.GameProvider` in a package and register it in
`pyproject.toml` under `[project.entry-points."fudabako.games"]` (or in your own
package). No other code changes: web and mobile read game metadata from `/api/games`.
