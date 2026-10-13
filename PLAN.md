# Fudabako (札箱, "card box") — Plan

Self-hosted TCG collection manager. Named Fudabako on 2026-10-13 (was "TCG MGMT").
Product name, CLI (`fudabako`), Python package and plugin entry point group
(`fudabako.games`) use the new name. Configuration identifiers keep their short `TCG`
prefix (`TCG_*` environment variables, `tcg_*` cookies, `tcg` database), so existing
`.env` files keep working.

## Context
User want one tool to manage TCG collections (MTG, Pokémon, Sorcery), with new games added later via plugins. Need card name, colors, price (Cardmarket), stock, image, set; cards have multiple printings across sets. Android app scans cards by OCR, shows info, then adds/removes stock. Greenfield: `/home/pierre/Projets/TCG_MGMT` is empty.

Decisions from Q&A:
- Self-hosted web app (Docker), multi-user, separate collection per user.
- Prices: from APIs only (Scryfall → Cardmarket EUR for MTG, TCGdex → Cardmarket for Pokémon), manual for Sorcery, manual override everywhere. No scraping.
- Stock detail: printing + finish + condition + language.
- Android: online only, continuous scan + confirm.
- Languages: EU (EN/FR/DE/IT/ES/PT), JA, ZH, KO.
- Extras: price history + collection value, CSV import/export. Start fresh (no import from other app).
- Images cached locally.
- Login: local accounts + SSO via OpenID Connect (Keycloak, Authentik, Authelia, any OIDC IdP).

## Tech stack
- **Backend**: Python 3.13, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL 17 with `pg_trgm` (fuzzy OCR name match). Background jobs: separate `worker` process with APScheduler (catalog sync, daily price snapshot, image cache). httpx for API calls.
- **Web UI**: React + TypeScript + Vite, TanStack Query/Table, typed client generated from FastAPI OpenAPI (`openapi-typescript`).
- **Styling**: Tailwind CSS v4 (`@tailwindcss/vite`), no custom CSS framework. Plugins loaded with `@plugin` in `web/src/index.css`:
  - `daisyui` (v5): components (navbar, drawer, card, table, modal, badge, stat), themes light/dark + custom theme
  - `@tailwindcss/typography`: `prose` for card rules text / docs pages
  - `@tailwindcss/forms`: form resets for filters, stock edit, CSV mapping (`strategy: "class"` to avoid clashing with daisyUI inputs)
  - `tailwindcss-animate`: enter/exit animations for modals, toasts, scan feedback
  - `tailwindcss-3d`: card flip / tilt on card detail (front/back for double-faced cards)
  - Plugins `tailwindcss-animate` and `tailwindcss-3d` are Tailwind v3 JS plugins; load via v4 `@plugin` compat. If one breaks on v4, swap to `tw-animate-css` (drop-in v4 replacement) or a few `@utility` rules for 3D — check at phase 5 start.
  - Game colors (MTG WUBRG, Pokémon energies, Sorcery elements) defined once as theme tokens (`@theme`) and rendered as daisyUI badges.
- **Android**: Kotlin, Jetpack Compose, CameraX, ML Kit Text Recognition v2 (Latin, Japanese, Chinese, Korean models), Retrofit + kotlinx.serialization, DataStore for token/server URL.
- **Deploy**: `docker compose` (postgres, api, worker, web served by Caddy). Data in bind mounts next to the compose file (`./data/postgres`, `./data/images`; dev: `./data-dev`). Remote access via Tailscale/VPN, not public exposure.

## Repo layout
```
backend/
  app/
    core/            config, db, security (app JWT + argon2), oidc (PyJWT + httpx)
    models/          game, set, card, printing, card_name, price, collection, transaction, user
    games/           plugin system
      base.py        GameProvider protocol + registry
      mtg/           Scryfall provider
      pokemon/       TCGdex provider
      sorcery/       Sorcery provider
    services/        catalog_sync, pricing, identify (OCR match), images, csv_io
    api/             routers: auth, users, games, cards, collection, scan, prices, import_export
    worker.py        scheduler entry
  alembic/
  tests/
web/                 React app
android/             Kotlin app
docker-compose.yml
```

## Game plugin system (modularity core)
`backend/app/games/base.py`:
```python
class GameProvider(Protocol):
    id: str                      # "mtg", "pokemon", "sorcery"
    name: str
    color_vocab: list[ColorDef]  # MTG WUBRG/C, Pokémon energy types, Sorcery elements
    finishes: list[str]          # nonfoil/foil/etched | normal/holo/reverse | standard/foil/rainbow
    languages: list[str]
    async def sync_catalog(self, session) -> SyncReport       # sets, cards, printings, localized names
    async def fetch_prices(self, session) -> list[PriceQuote]  # empty for sorcery
    def image_url(self, printing) -> str | None
    def parse_ocr(self, lines: list[str]) -> OcrHints          # name, set code, collector number, lang
```
Registry via Python entry points (`fudabako.games`), so new game = new package implementing protocol, no core change. Web/Android read game metadata (colors, finishes, languages) from `GET /games` — no hardcoded game logic in clients.

## Data model (generic + JSONB for game-specific)
- `game` (id, name)
- `set` (game, code, name, release_date, total, icon)
- `card` — oracle-level (game, canonical_name, colors[] normalized, attributes JSONB: types, cost, elements, HP...)
- `printing` — card in a set (set, collector_number, rarity, artist, available finishes[], available languages[], external ids JSONB, image_path)
- `card_name` (card/printing, lang, name) + trigram index — multilingual OCR lookup
- `price_snapshot` (printing, finish, date, source, currency, trend, low, avg) — daily; history + value chart
- `user` (username, email, password hash nullable, role admin/user, disabled)
- `user_identity` (user, issuer, subject) unique on (issuer, subject) — links SSO accounts
- `collection_item` (user, printing, finish, condition, language, quantity, manual_price nullable, notes) unique on (user, printing, finish, condition, language)
- `stock_transaction` (user, item, delta, source web/scan/import, timestamp) — audit + undo

Price resolution for an item: manual_price > latest snapshot for (printing, finish) > none. API prices are not per condition/language — UI shows that explicitly.

## Authentication (local + SSO)
Standard OpenID Connect only, so Keycloak, Authentik, Authelia, Zitadel, Google etc. all work with no IdP-specific code.
- **Config** (`.env` only): `TCG_LOCAL_LOGIN_ENABLED`, `TCG_OIDC_PROVIDERS` (JSON list of names), each provider set by `TCG_OIDC_<NAME>_*`: `name`, `display_name`, `issuer` (discovery via `/.well-known/openid-configuration`), `client_id`, `client_secret`, `scopes` (`openid profile email groups`), `groups_claim`, `admin_groups`, `allowed_groups`, `auto_create_users`.
- **Web flow**: backend is confidential client. `GET /auth/oidc/{provider}/login` → IdP (authorization code + PKCE + state + nonce) → `GET /auth/oidc/{provider}/callback` → validate ID token (JWKS, iss, aud, nonce, exp) → find/create user by (issuer, sub) → issue app session (httpOnly secure cookie with short-lived access JWT + rotating refresh token).
- **Android flow**: AppAuth-Android, public client, authorization code + PKCE, redirect via app custom scheme / app link. App sends IdP ID token to `POST /auth/oidc/{provider}/exchange`; backend validates same way and returns app access + refresh token. App never holds client secret. `GET /auth/providers` tells app/web which login buttons to show.
- **Provisioning**: first SSO login auto-creates user if allowed (username from `preferred_username`, email). Role from group claim on each login (admin group → admin). Not in `allowed_groups` → refused. Existing local user can link SSO identity from settings (no auto-link by email — avoids account takeover).
- **Logout**: revoke app refresh token; optional RP-initiated logout via IdP `end_session_endpoint`.
- Local accounts stay available (bootstrap admin, fallback if IdP down); admin can disable local login once SSO works.
- Docs: setup notes for Keycloak, Authentik, Authelia client config (redirect URIs, group claim mapping).

## Providers
- **MTG / Scryfall**: daily bulk `all_cards` (all languages, large; stream-parse with `ijson`) for printings + localized `printed_name`; prices from `prices.eur`/`eur_foil` (Cardmarket trend). Respect 50–100 ms between requests and User-Agent header.
- **Pokémon / TCGdex**: per-language endpoints (`/v2/{lang}/sets`, `/cards`); EN and JA set lists differ — treat JA sets as own sets, linked by name when possible. Prices from `pricing.cardmarket` (trend, avg, low, holo variants).
- **Sorcery**: `GET /api/cards` (30 req/min, one call is enough), printings with finishes Standard/Foil/Rainbow; images from public image folder; English only; no prices (manual).

## OCR identification (`services/identify.py`, `POST /scan/identify`)
Phone sends OCR text lines + bounding boxes + chosen game (or auto). Server:
1. Provider `parse_ocr` extracts collector number + set code (bottom line, language-independent — key for JA/ZH/KO) and name (top line).
2. Exact match on (set code, collector number) → printing.
3. Fallback: trigram fuzzy match on `card_name` across languages, rank candidates.
4. Return top candidates with image, set, colors, price, and user's current owned quantity per finish/condition/lang.
Phone shows best match; user can swipe other printings, choose finish/condition/language, tap Add / Remove. Endpoint `POST /collection/adjust` (delta), returns new quantity; undo via transaction.

## Android app
Package `fr.fudabako.app`, app name "Fudabako", SSO redirect `fr.fudabako.app:/oauth2redirect`.
Screens: Login (server URL, then local credentials or SSO buttons from `/auth/providers` via AppAuth), Scan (CameraX preview + ML Kit analyzer, throttle, stability check: same parse over N frames before query), Result sheet (candidates, info, price, owned, Add/Remove, quantity stepper), Collection search (read-only light view), Settings (game, default condition/lang/finish, scan model language). ML Kit script models bundled for Latin + JA + ZH + KO; pick per user setting or run Latin + selected script.

## Web UI
Collection browser per game (filters: set, color, finish, condition, lang, owned/missing), card detail with all printings + price history chart, stock edit, collection value dashboard (total + over time), manual price entry, CSV import/export (generic format: game, set_code, collector_number, lang, finish, condition, quantity, price), admin: users, sync status, trigger sync.

## Progress
- [x] Phase 0 — plan copied, git init (2026-10-12)
- [x] Phase 1 — backend skeleton, local auth + OIDC SSO, plugin registry, compose (2026-10-12).
  34 tests pass; verified live against Keycloak dev realm (`deploy/keycloak`).
  Deviations: OIDC done with PyJWT + httpx instead of Authlib (fewer deps, easy JWKS mocking);
  single `TCG_PUBLIC_URL`, API mounted under `/api`, web UI same origin;
  Keycloak groups claim via client mapper (no `groups` scope). SSO setup notes in `docs/sso.md`.
- [x] Phase 2 — Sorcery provider, catalog sync, image cache (2026-10-12). 45 tests pass;
  live sync: 6 sets, 1100 cards, 1601 printings in ~3 s, idempotent.
  Changes to the design:
  - Providers no longer touch the DB: `fetch_catalog(http)` yields normalized
    `CatalogBatch` data, `services/catalog.py` does all upserts (arrays of finishes and
    languages are merged). `fetch_prices(http)` yields `PriceQuote` keyed by external ids.
  - Sorcery API lists one printing per finish; grouped per set + card + product.
    Images are not available from the API (CDN use forbidden): import the public Google
    Drive folder (files named after printing slugs) via `fudabako import-images` or admin endpoint.
  - Images cached on demand (`/api/printings/{id}/image`) plus worker pre-fetch of owned
    printings; caching every MTG printing would be ~10 GB.
  - Worker is a plain asyncio loop (no APScheduler); `sync_run` table records job history and
    a partial unique index blocks overlapping runs. Admin endpoints: `/api/admin/jobs`.
  - Catalog read API added: `/api/cards` (multilingual name search, set, colors), `/api/cards/{id}`,
    `/api/games/{game}/sets`.
- [x] Phase 3 — MTG + Pokémon providers, multilingual names, price snapshots (2026-10-13).
  53 tests pass (tests now refuse real network access). Live runs:
  MTG 997 sets, 37.9k cards, 109k printings, ~450k localized names, 7 min (idempotent);
  Pokémon EN+FR 223 sets, 37k printings, 2.5 min; MTG daily price job 48 s.
  Changes to the design:
  - MTG uses Scryfall `all_cards` gzipped JSON Lines (streamed, no ijson). One printing per
    set + collector number; English objects are full data, other languages partial.
    Prices: `default_cards` (smaller) for the daily job. `TCG_MTG_CATALOG_BULK` switch.
  - Pokémon: TCGdex has no bulk export and its GraphQL lacks prices/pagination; REST card
    details fetched with 8 concurrent requests. Translations of international sets are
    partial data; JA/KO/ZH-only sets are separate sets with their own cards (cards grouped
    by name per language). `TCG_POKEMON_LANGUAGES` limits languages.
  - `CardData.partial`: secondary sources only fill missing fields (merge-safe in any order).
  - `CatalogBatch.prices`: catalog syncs also store a price snapshot. Daily price job
    (`fetch_prices(http, owned)`): MTG all printings, Pokémon only owned printings.
  - History kept only for printings in a collection; others keep their latest snapshot.
  - Catalog refresh weekly (`TCG_CATALOG_INTERVAL_HOURS`), prices/images daily.
- [x] Phase 4 — Collection API (items, adjust, transactions, value), CSV import/export
  (2026-10-13). 61 tests pass. Live check on full MTG data: card with 870 printings in 0.2 s.
  - `POST /api/collection/adjust` (delta, source web|scan): atomic upsert for additions,
    guarded UPDATE for removals (Postgres checks CHECK constraints on the proposed insert
    row, so `ON CONFLICT` cannot be used for negative deltas). Concurrent scans tested.
  - Items list with filters/sort and resolved prices, `PATCH` (quantity recorded as a
    transaction, manual price, notes), `DELETE`, transactions list + undo.
  - `/api/collection/value` per game, `/value/history` (current holdings priced per day).
  - Card detail returns latest prices per finish and the user's owned copies;
    `/api/printings/{id}/prices` for history charts. Name search ranks exact > prefix.
  - CSV: generic format, all-or-nothing validation, add/set modes, dry run, `,`/`;`/tab.
- [x] Phase 5 — Web UI (Tailwind v4 + daisyUI + plugins) (2026-10-13). 63 backend tests
  pass; UI checked in a browser on live data (login, catalog, card detail with 3D flip,
  add/undo, collection, dashboard, admin sync, dark mode, 400 px width).
  - React 19 + Vite 8 + TypeScript 5.9, react-router 7 (lazy routes), TanStack Query,
    openapi-fetch with types generated from FastAPI (`npm run gen:api`), recharts.
  - `tailwindcss-3d` fails on Tailwind v4 (`addDefaults` v3 API): dropped, v4 core 3D
    utilities (`transform-3d`, `rotate-y-180`, `backface-hidden`, `perspective-*`) used.
    `tailwindcss-animate` works through `@plugin`. daisyUI 5 classes (`fieldset`, `tabs-box`).
  - Cookie session with silent refresh on 401 and CSRF header on every request.
  - Game colors, finishes, languages and card attributes rendered from plugin metadata
    (no per-game UI code).
  - FastAPI serves the built SPA (`TCG_WEB_DIR`) with index fallback; one root
    multi-stage `Dockerfile` builds web + backend; compose builds from repo root.
    No Caddy needed.
- [x] Phase 6 — Identify endpoint + OCR parsers per game (2026-10-13). 71 tests pass
  (OCR dumps for EN/FR/JA MTG, FR/JA/SV-era Pokémon, Sorcery). Live on the full catalog:
  50–180 ms per scan without a game filter, ~50 ms with one.
  - `POST /api/scan/identify` {game?, lines[{text, left?, top?, width?, height?}]}:
    candidates {score, match: set_number | number_name | name, card, printings[]} with
    prices and owned copies (same printing shape as card detail).
  - `parse_ocr(lines: list[OcrLine]) -> OcrHints(name, other_names, set_code,
    collector_number, lang, recognized)`. MTG: "DOM • FR" + "168/269" or new "0280 L";
    power/toughness ignored (set size ≥ 20, left side). Pokémon: "136/189", "TG05/TG30",
    "G PAL EN 063/193", Asian "SV1a 001/073", stage/HP labels stripped in 6+ languages,
    FR/DE from "PV"/"KP". Sorcery: name only.
  - Matching: set code + number (zero padding ignored), else number + name similarity,
    else pg_trgm similarity over all localized names (each face of "A // B" names).
    Games whose markers appear in the text (copyright lines) are tried first and win
    ties; a printing-level match there stops the search.
- [x] Phase 7 — Android app (2026-10-13). 8 JVM unit tests (server URL rules, scan
  stabilizer, token refresh with MockWebServer); debug and R8 release builds; Android lint
  clean. Driven on an API 36 emulator against the dev server: connect, local login,
  multilingual search, card panel with authenticated images, Add, Undo, settings.
  The camera scan itself needs a real phone (emulator camera shows a test pattern).
  - AGP 9.4 (built-in Kotlin), Kotlin 2.4, compileSdk/targetSdk 37, minSdk 26, Compose
    BOM 2026.09, CameraX 1.6 (TextureView preview), ML Kit 16 bundled models (Latin,
    Japanese, Chinese, Korean), Retrofit 3 + kotlinx.serialization, OkHttp 5, AppAuth
    0.11, Coil 3 (images through the authenticated OkHttp client), DataStore.
  - Token mode auth: bearer interceptor + OkHttp Authenticator rotating the refresh
    token once (not for login/refresh/exchange endpoints); expired session -> login.
  - SSO: AppAuth discovery + code/PKCE with `mobile_client_id`, ID token + nonce sent to
    `/api/auth/oidc/{provider}/exchange`; HTTP identity providers allowed.
  - Scan: ML Kit lines normalized to the text bounding box (approximates the card), sent
    once the word set is stable over 3 frames and different from the last card sent.
  - Found while testing: kotlinx.serialization skipped default values (scan source was
    recorded as "web") -> `encodeDefaults`; TCGdex includes the digital Pokémon TCG Pocket
    sets (series `tcgp`) -> skipped by the Pokémon provider.
- [x] CI pipelines (2026-10-13): manual GitHub Actions `docker-dev`, `docker-prod`,
  `android-dev`, `android-prod` (dev: chosen non-main branch, smoke checks, dev image/APK;
  prod: main + version, full lint/tests, multi-arch image, signed APK). `release.yml`
  runs on successful prod builds (workflow_run) and publishes GitHub Release
  `server-vX.Y.Z` or `android-vX.Y.Z` from the files the prod build handed over (server
  and app versioned independently). Shared: `_checks.yml`, `_docker-image.yml`.
  `docker-compose.yml` now runs GHCR images; `docker-compose-dev.yml` builds locally.
  `pytest -m smoke` marks 15 critical-path tests. Dev Android build = separate app
  `fr.fudabako.app.dev` (own SSO redirect). Release keystore kept outside the repo,
  stored in `ANDROID_KEYSTORE_*` secrets.
- [x] First start (2026-10-13): nobody could sign in on a fresh deployment. The API now
  creates the administrator `admin` / `changeme` on start while the user table is empty
  (`TCG_DEFAULT_ADMIN_USERNAME` / `TCG_DEFAULT_ADMIN_PASSWORD`, empty password disables).
  Compose data moved from named volumes to `./data` (dev `./data-dev`); the image
  entrypoint starts as root, chowns `/data/images` (Docker creates missing bind mount
  folders as root) and drops to `tcg` with `setpriv`.
  `.env` is now the only configuration entry point: `auth.yaml` dropped, SSO providers
  come from `TCG_OIDC_PROVIDERS` + `TCG_OIDC_<NAME>_*`, host port from `FUDABAKO_PORT`.
  `.env.example` documents every variable; only `POSTGRES_PASSWORD` and `TCG_SECRET_KEY`
  are left uncommented.

## Build phases
0. Copy this plan to `/home/pierre/Projets/TCG_MGMT/PLAN.md`; `git init`; keep PLAN.md updated as phases complete.
1. Backend skeleton: config, DB, Alembic, local auth + OIDC SSO, users, plugin registry, docker-compose.
2. Sorcery provider (smallest) + catalog sync + image cache — validates plugin design.
3. MTG + Pokémon providers, multilingual names, price snapshots.
4. Collection API (items, adjust, transactions, value), CSV import/export.
5. Web UI (Tailwind v4 + daisyUI + plugins).
6. Identify endpoint + OCR parsers per game (test with fixture OCR text).
7. Android app.

## Verification
- `pytest` backend: provider parsers with recorded API fixtures (no live calls), OCR `parse_ocr` on sample text dumps (EN/FR/JA cards), identify ranking, collection adjust/unique constraint, CSV round-trip.
- Auth tests: OIDC callback/exchange against mocked IdP (signed test JWKS): bad nonce/aud/iss rejected, group → role mapping, disallowed group refused, (issuer, sub) linking.
- Manual SSO check: dev compose profile with Keycloak container; log in on web and Android. Then repeat with Authentik/Authelia config.
- `docker compose up`, run sync for each game, check card/printings counts and images on disk.
- Web: add/remove items, check value + history chart after two snapshot runs.
- Android: run on device against LAN server, scan real cards in EN/FR/JA for each game, confirm correct printing and stock change visible in web UI.
