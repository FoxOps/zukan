# Zukan (図鑑)

*Zukan* (図鑑) means "illustrated encyclopedia" in Japanese, like the Pokédex (ポケモン図鑑).

Self-hosted trading card game collection manager: Magic: The Gathering, Pokémon TCG,
Sorcery, Riftbound, Yu-Gi-Oh! and Disney Lorcana, with a plugin system for more games, and
an Android scanner app.
See [PLAN.md](PLAN.md) for the full design and progress.

## Run with Docker

`docker-compose.yml` runs the images built by CI from `ghcr.io/foxops/zukan`. The
package is private: log in once with a GitHub token that has `read:packages`.

```sh
cp .env.example .env          # set POSTGRES_PASSWORD and TCG_SECRET_KEY
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
docker compose pull && docker compose up -d
```

Coming from Fudabako (the former name, up to server 0.7.0 / app 0.6.0): data and the
`TCG_*` settings stay as they are. Use the new image `ghcr.io/foxops/zukan` (the compose
project is now `zukan`), rename `FUDABAKO_PORT` / `FUDABAKO_TAG` in `.env` to
`ZUKAN_PORT` / `ZUKAN_TAG`, and run the CLI as `zukan` instead of `fudabako`. The Android
app is now `fr.zukan.app`: it installs as a new app (sign in again, then uninstall the old
one), and SSO providers need the redirect URI `fr.zukan.app:/oauth2redirect`.

First start creates the administrator **`admin`** / **`changeme`**
(`TCG_DEFAULT_ADMIN_USERNAME` / `TCG_DEFAULT_ADMIN_PASSWORD` in `.env`). Sign in and change
the password from the account page. The account is only created while the database has no
user. Reset or add an administrator any time:
`docker compose exec -e TCG_ADMIN_PASSWORD=... api zukan create-admin NAME`.

Data is stored next to the compose file, not in Docker volumes: `./data/postgres`
(database) and `./data/images` (card image cache); the dev compose uses `./data-dev`.
Back up these folders.

All configuration lives in `.env`: `.env.example` documents every variable (only the
two above are mandatory; the rest is commented out with its default). Serving the web
UI over plain HTTP (no TLS)? Set `TCG_COOKIE_SECURE=false` or web sign-in will not stick.
Behind a reverse proxy, set `TCG_FORWARDED_ALLOW_IPS` to its address so the API sees real
client addresses (sign-in limits count failures per address).

### HTTPS with a reverse proxy

The container speaks plain HTTP on port 8000; HTTPS is the proxy's job (nginx, Nginx Proxy
Manager, Caddy, Traefik). Browsers forgive some certificate mistakes that the Android app
does not: Chrome fetches a missing intermediate certificate by itself, the app refuses it.

- Serve the **full chain**: nginx `ssl_certificate /path/fullchain.pem;` (not `cert.pem`).
  Nginx Proxy Manager with a custom certificate: put the intermediate certificate in the
  "Intermediate Certificate" field (Let's Encrypt certificates made by NPM are fine).
- Forward the host and scheme, and redirect port 80 to 443 if you like (the app follows it):

  ```nginx
  server {
      listen 443 ssl;
      server_name cards.example.org;
      ssl_certificate     /etc/letsencrypt/live/cards.example.org/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/cards.example.org/privkey.pem;
      client_max_body_size 8m;
      location / {
          proxy_pass http://zukan-host:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }
  ```
- `.env`: `TCG_FORWARDED_ALLOW_IPS=<proxy address>`, `TCG_PUBLIC_URL=https://cards.example.org`
  (SSO redirects).
- Check what the phone sees: `openssl s_client -connect cards.example.org:443
  -servername cards.example.org -showcerts </dev/null` must list two certificates (yours
  and the intermediate) and end with `Verify return code: 0 (ok)`.
- In the app, type `cards.example.org` or `https://cards.example.org` (no `:8000`: that
  port has no TLS).

Sessions: changing a password (own or by an administrator) or disabling an account signs
it out everywhere; the browser changing its own password stays signed in. Sign-in is
limited (`TCG_LOGIN_*` in `.env.example`): past the limit the API answers 429 for the rest
of the window.

Update: `docker compose pull && docker compose up -d` (migrations run on start).
`ZUKAN_TAG` in `.env` pins a version (`0.1.0`) or tries a dev build (`dev-<branch>`).
To build from this checkout instead: `docker compose -f docker-compose-dev.yml up -d --build`
(separate project `zukan-dev`, with an optional Keycloak for SSO tests).

API docs: `http://localhost:8000/api/docs`. SSO setup: [docs/sso.md](docs/sso.md).

The `worker` service syncs catalogs weekly (`TCG_CATALOG_INTERVAL_HOURS`) and prices and
images daily (`TCG_SYNC_INTERVAL_HOURS`). Run a job now:
`docker compose exec api zukan sync mtg [--kind catalog|prices|images]`.
The first sync of each game takes a while: MTG streams Scryfall's ~400 MB `all_cards`
file, Pokémon fetches every card from TCGdex one by one.

### Prices

Prices come from Cardmarket (EUR) and TCGplayer (USD), never scraped from their websites:

- MTG: trend price from Scryfall, lowest offer and average from the daily price guide file
  Cardmarket publishes for download (matched by Scryfall's Cardmarket product id).
- Pokémon: trend, lowest offer and average from TCGdex.
- Sorcery, Riftbound and Yu-Gi-Oh!: Cardmarket's daily product list and price guide files;
  products are matched to printings by set and card name (Yu-Gi-Oh!: TCG sets only, the
  rarities of one card in a set paired in Cardmarket's order). Cards too new for a trend
  use the 7 or 30 day average, then the lowest offer.
- Lorcana: Cardmarket's price guide file, by the product id LorcanaJSON gives.
- TCGplayer: from Scryfall, TCGdex and YGOPRODeck, and for the printings they do not price
  (Sorcery, Riftbound, Lorcana) from [tcgcsv](https://tcgcsv.com)'s daily TCGplayer files.

### Card data sources

Each game has its own sources (Scryfall + MTGJSON, TCGdex + Asian
datasets, the Sorcery API, Riftbound below). Card databases covering several games only fill
what those leave empty (English pictures, rarities, artists, TCGplayer ids, finishes) for
the sets with such gaps, and report where they disagree (admin "Data checks"):
[tcgcsv](https://tcgcsv.com) (no key), [tcg-api.eu](https://tcg-api.eu) and
[apitcg.com](https://apitcg.com) (free keys, see "API keys" in `.env.example`; their
monthly or daily quotas are counted).

Riftbound: Riot's official content API with a key Riot approved for a Riftbound product
(`TCG_APITOKEN_GAMES_RFB_RIOT`), else [Riftcodex](https://riftcodex.com). Riot's official
[card gallery](https://playriftbound.com/en-us/card-gallery/) adds the cards of sets the
APIs do not have yet and the Simplified Chinese names and pictures. Pictures come from
Riot's servers only, and the web UI shows Riot's legal notice, as Riot's policy for fan
tools asks. Getting a Riot key (Riot account, developer account, Production API Key):
[docs/riftbound.md](docs/riftbound.md).

Yu-Gi-Oh!: [YGOPRODeck](https://ygoprodeck.com/api-guide/) (every TCG card, set and
printing, French, German, Italian and Portuguese names, TCGplayer prices),
[YGOJSON](https://github.com/iconmaster5326/YGOJSON) (Spanish, Japanese, Korean and Chinese
names, and the Japanese, Korean and Chinese OCG sets; no longer updated since 2026-04) and,
for newer cards, the official [Konami card database](https://www.db.yugioh-card.com/yugiohdb/)
(a few hundred pages a day at most, each card read once). A printing is a set code with one
rarity ("LOB-EN001" Ultra Rare); finishes are the editions (Unlimited, 1st Edition,
Limited Edition).

Disney Lorcana: [LorcanaJSON](https://lorcanajson.org) (Ravensburger's card data in
English, French, German and Italian, with Cardmarket and TCGplayer ids). No source has the
Japanese or Chinese Lorcana cards yet.

Each user picks the markets shown (Settings, several allowed); the first one gives values,
sorts and price ranges. Card pages show the trend and lowest offer of each printing and finish, the cheapest and
most expensive version of the card, and a link to each printing's Cardmarket page. A
manual price on a collection item always wins. Price history is kept for cards somebody
owns; other cards only keep their latest price.

An admin can reset a game's catalog (Data sync page, "Reset catalog"): everything is
deleted except the printings in collections, then synced again from scratch. Images
imported from a folder must be imported again.

### Card images

Images are cached under `./data/images`: downloaded on first view, and pre-fetched
for cards somebody owns. Cards are shown in the user's interface language when that scan
exists, else in English, else in Japanese, else in the language there is.

Sorcery images are downloaded once each (about 1600, at most 2 at a time) from the
addresses the [sorcerytcg.com card gallery](https://sorcerytcg.com/cards) uses, and served
from the local cache only. Large scans are stored as WebP. The
[public image folder](https://drive.google.com/drive/folders/17IrJkRGmIU9fDSTU2JQEU9JlFzb5liLJ)
can be imported instead: unzip it into `./import/sorcery`, then run
`docker compose exec api zukan import-images sorcery /data/import/sorcery`
(or use the admin import endpoint `POST /api/admin/images/sorcery/import`).

Game color symbols (Scryfall mana symbols, the energy types of pokemon.com's card
database, the element symbols of the sorcerytcg.com card gallery, Riftbound's domains,
YGOPRODeck's Yu-Gi-Oh! attributes, the Spell and Trap symbols of Konami's card database)
are downloaded once when the API starts. A symbol that fails to download is shown as a
colored badge and tried again on the next start. Symbols no source has (Riftbound and
Sorcery colorless, Lorcana inks, Pokémon "No type") are drawn for Zukan and shipped with it
(`scripts/draw_color_symbols.py`); drawn Spell and Trap symbols stand in while Konami's
cannot be downloaded.

Rarities are shown with their pictogram next to their name. The pictograms are the ones
Cardmarket draws, collected once and shipped with each game
(`backend/app/games/<game>/rarities/`, see `scripts/install_rarity_icons.py`), or drawn
for Zukan (`scripts/draw_rarity_icons.py`).

#### Image folders

Everything is kept per game, `<game>` being the game id (`mtg`, `pokemon`, `sorcery`,
`riftbound`, `yugioh`, `lorcana`):

```
data/images/<game>/cards/     card pictures, <set id>/<printing id>-<language>.<ext>
data/images/<game>/sets/      set icons
data/images/<game>/symbols/   color symbols
data/images/<game>/rarity/    your own rarity pictograms
data/images/default/<game>/rarity/    pictures shipped with Zukan (reference copy)
data/images/default/<game>/symbols/
data/images/cache/            source caches (Konami card pages)
```

`default/` holds a copy of every pictogram and symbol shipped with Zukan, rewritten each
time the API starts: look there for the file names, and copy one into
`data/images/<game>/...` to change it (edits made in `default/` itself are undone on the
next start).

Folders from before 0.12.0 (`<game>/<set id>/`, `sets/<game>/`, `symbols/<game>/`) are
moved by the database migration when the new version starts.

**Your own pictograms**: copy a file named after the rarity or color code
(`.svg`, `.png` or `.webp`) into `data/images/<game>/rarity/` or
`data/images/<game>/symbols/`, e.g. `data/images/yugioh/rarity/secret.png`. It replaces
the shipped one at once (no restart; reload the page). Delete it to get the shipped one
back. Codes:

| Game | Rarity codes | Color codes |
|------|--------------|-------------|
| lorcana | `common`, `uncommon`, `rare`, `super_rare`, `legendary`, `epic`, `enchanted`, `iconic`, `quest`, `promo` | `amber`, `amethyst`, `emerald`, `ruby`, `sapphire`, `steel` |
| mtg | `common`, `uncommon`, `rare`, `mythic`, `special` | `W`, `U`, `B`, `R`, `G`, `C` |
| pokemon | `common`, `uncommon`, `rare`, `holo_rare`, `double_rare`, `triple_rare`, `ace_spec`, `radiant`, `amazing`, `illustration_rare`, `character_rare`, `ultra_rare`, `character_super_rare`, `special_illustration_rare`, `shiny_rare`, `shiny_ultra_rare`, `secret_rare`, `hyper_rare`, `promo` | `grass`, `fire`, `water`, `lightning`, `psychic`, `fighting`, `darkness`, `metal`, `fairy`, `dragon`, `colorless`, `none` (Trainers, special Energies) |
| riftbound | `common`, `uncommon`, `rare`, `epic`, `showcase`, `promo` | `fury`, `calm`, `mind`, `body`, `chaos`, `order`, `colorless` |
| sorcery | `ordinary`, `exceptional`, `elite`, `unique` | `air`, `earth`, `fire`, `water`, `colorless` |
| yugioh | `common`, `rare`, `super`, `ultra`, `secret`, `ultimate`, `ghost`, `gold`, `parallel`, `prismatic`, `collectors`, `starlight`, `platinum`, `starfoil`, `millennium`, `extra_secret`, `quarter_century` | `dark`, `light`, `earth`, `water`, `fire`, `wind`, `divine`, `spell`, `trap` |

Landscape pictures (Riftbound battlefields) are turned a quarter to fit the card frame.

Cards printed only in Japanese, Korean, Chinese, Thai or Cyrillic are named in their script
with a Latin translation next to it ("ブラック・マジシャン (Dark Magician)"), and so is any
name shown in such a script. When a source gives no Latin name, the catalog sync copies the
one of a card sharing its name (Simplified and Traditional Chinese spellings match).

### Translations

The web UI uses [i18next](https://www.i18next.com/) (`react-i18next`) with the English
texts as keys: `web/src/locales/en.json` only holds plural forms, `fr.json` translates
every text. `npm run check:i18n` lists missing and unused translations (run by CI). To add
a language, add its JSON file and an entry in `LANGUAGES` (`web/src/i18n/index.ts`), and
allow it in `UiLanguage` (`backend/app/api/schemas.py`).

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
  `mobile_client_id` (public client, redirect `fr.zukan.app:/oauth2redirect`, see
  [docs/sso.md](docs/sso.md)).
- Point the camera at a card: once the text is steady, the app asks the server, shows the
  card, its printings, prices and owned copies; pick finish, condition, language and
  quantity, then Add or Remove (with Undo). Search covers cards that cannot be scanned.
- Settings: text recognition script, default condition and language.
- Plain HTTP servers are accepted for home networks (the app warns); prefer HTTPS.
- Connection errors say what is wrong: certificate for another name, certificate not
  trusted (missing intermediate in the proxy, or a private CA not installed on the phone:
  the message shows the issuer it could not verify), or an address that answers without
  encryption (`https://` sent to port 8000). See [HTTPS with a reverse proxy](#https-with-a-reverse-proxy).

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
release which follows successful builds:

| Workflow | Runs from | Does |
|---|---|---|
| Docker dev | any branch but main | ruff, smoke tests (`pytest -m smoke`), type check, container smoke test; pushes `dev-<branch>` and `dev-<branch>-<sha>` (amd64) |
| Docker prod | main, server version `X.Y.Z` | ruff + format, migrations check, all tests, web lint/build, API types check, container smoke test; pushes `latest`, `X.Y.Z`, `sha-<sha>` (amd64 + arm64) |
| Android dev | any branch but main | unit tests, "Zukan dev" debug APK |
| Android prod | main, app version `X.Y.Z` | lint, unit tests, signed R8 release APK |
| Release | after a successful build | prod: GitHub Release `server-vX.Y.Z` (Docker tag) or `android-vX.Y.Z` (APK, R8 mapping); dev: pre-release `server-dev-<branch>` (Docker tag) or `android-dev-<branch>` (dev APK), replaced by each dev build of the branch |

The branch is chosen with "Use workflow from"; dev workflows refuse main and prod
workflows refuse anything else. The server and the Android app have independent
versions: an app fix ships a new `android-v*` release without a new server version, and
the other way round. Shared steps live in `_checks.yml` and
`_docker-image.yml` (reusable workflows, not started directly).

From the command line:

```sh
gh workflow run docker-dev.yml --ref my-branch
gh workflow run docker-prod.yml --ref main -f version=0.15.0
gh workflow run android-prod.yml --ref main -f version=0.9.0
```

The dev app (`fr.zukan.app.dev`) installs next to the released one. Both are signed
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

Visual identity (Zukan v1.0): daisyUI themes `zukan` (light, default) and `zukan-dark` in
`web/src/index.css` (gold `#FFC21A`, chocolate `#402719`, cream `#FFF6E5`, leaf
`#3C7255`, night `#211A17`); Nunito 800 for titles and Inter for text, bundled as Latin
woff2 subsets with their SIL OFL licences in `web/src/assets/fonts/`; logos in
`web/src/assets/brand/`, icons and `manifest.webmanifest` in `web/public/`. Gold is a
fill colour: text on cream uses chocolate or green (`text-secondary`). The Android app
uses the same palette and fonts (`ui/Theme.kt`, `res/font/`).

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
`pyproject.toml` under `[project.entry-points."zukan.games"]` (or in your own
package). No other code changes: web and mobile read game metadata from `/api/games`.
