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
- Prices: from APIs only (Scryfall → Cardmarket EUR for MTG, TCGdex → Cardmarket for Pokémon), Cardmarket's public price guide files for Sorcery (since 2026-10-13), manual override everywhere. No scraping.
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
- [x] Languages and UX batch (2026-10-13). 86 backend tests pass; checked in a browser on a
  live Sorcery sync (1601 printings, 2710 Cardmarket price snapshots).
  - Web UI in English (default) and French with i18next + react-i18next (natural
    language keys, `web/src/locales/*.json`, browser language detector, `check:i18n`
    script in CI), language menu in the header and on the login page, saved on the user
    (`PATCH /api/auth/me`), dates/money/language names follow it.
  - Images per language: `printing.image_urls` / `image_paths` (JSONB, lang -> url/path),
    replacing `image_url` / `image_path`. Shown in the user's language, else English, else
    Japanese, else any. Scryfall placeholder scans skipped; TCGdex translated listings add
    their scans. Image links carry `?lang=` so a language change is not hidden by caches.
  - Name search ignores case and accents: generated `card_name.search_name`
    (`lower(f_unaccent(name))`, IMMUTABLE wrapper of `unaccent`) with a trigram index.
  - User settings: `language`, `catalog_games` (null = all) filter the catalog.
  - Card detail: owned printings first, set filter box; Sorcery set list uses "-".
  - Sorcery images: URLs the sorcerytcg.com gallery uses (`{slug}.png`), downloaded once
    by the image job for every printing (`cache_all_images`, 2 at a time), scans > 1 MB
    stored as WebP (Pillow). The API's rule is not to serve images from its CDN; clients
    only get the local copy.
  - Sorcery prices: Cardmarket's public daily `products_singles_25.json` and
    `price_guide_25.json` (game 25); matched by expansion (known ids, unknown ones by
    shared names) and normalized card name; trend falls back to avg7/avg30/avg/low.
    ~97 % of printings priced (tokens and box toppers named differently are not).
  - Color symbols (`ColorDef.icon_url` / `icon_box`), downloaded once on API start to
    `images/symbols/`: Scryfall mana SVGs, pokemon.com energy sprite (cut with Pillow),
    Sorcery element PNGs of the sorcerytcg.com gallery (build-hashed names: on a 404 the
    UI shows badges and the next start retries). `GET /api/games/{game}/colors/{code}/icon`.
  - Cardmarket everywhere (`app/games/cardmarket.py`): lowest offer (`low`) shown next to
    the trend; MTG gets low/avg from Cardmarket's `price_guide_1.json` by Scryfall's
    `cardmarket_id`. Card summaries carry `price_min` / `price_max`, card detail shows the
    cheapest / most expensive version and lowest offer. Printings expose `cardmarket_id`
    (Sorcery: from the product match), games `cardmarket` (URL segment): links go to
    `cardmarket.com/{lang}/{game}/Products?idProduct=`, which redirects to the product.
  - Scan name matching uses `search_name` too (accent and case free).
  - Conditions use Cardmarket's badge colors; special finishes (foil, holo, reverse,
    etched, rainbow, 1st edition) get their own badge styles; no images in the
    collection list.
  - Pokémon: TCGdex set ids are URL-encoded (`SM1+` returned 404).
- [x] Feedback batch 2 (2026-10-14), branch `feedback-batch-2`: server 0.4.0, Android 0.3.0.
  93 backend tests, 15 Android JVM tests; checked in a browser on a live Sorcery sync and
  a live Pokémon ja + ko sync (SV4K 078 = ドゴーム, one Japanese set, Korean name and
  languages added, 0 cards without printings); Android driven on the API 36 emulator.
  - Sorcery images missing after the 0.3 upgrade: the image job only picks printings with
    an image URL, which came with the next (weekly) catalog sync. Providers now have a
    `catalog_version`; the worker syncs a catalog at once when the stored one is older,
    and images when the catalog is newer than the last image run. Printings without
    any image source are reported as `missing`.
  - Catalog syncs delete cards left without printings; search skips them.
  - Pokémon: TCGdex lists the same set ids in Japanese, Korean and Chinese. Each was
    fetched in full and the last language took the printings (mixed image/title/text,
    1163 empty cards). Now one base language per set id (en, eu languages, ja, ko,
    zh-tw, zh-cn); other listings add names and images only.
  - Pokémon species names (PokeAPI, bundled `species_names.json`, regenerate with
    `scripts/pokemon_species.py`) name cards made of species names + suffixes in every
    language ("ルギアV" = "Lugia V"); Asian printings join the English card.
  - Card names follow the interface language, else English, else Japanese, else the
    canonical name (`services/names.py`). Whole-catalog listings (> 5000 cards) are
    sorted by canonical name: the per-card name lookup costs ~0.5 s for 40k cards.
  - Catalog search by code: `[game] set [number]` (`pkm ssp 181`, `mtg j25 158`,
    `sorcery ALP`); providers' `short_names`, Sorcery `set_aliases`.
  - Base finish named "Standard" everywhere; collection sort by price (manual price, else
    latest trend).
  - Web: flag icons (`flag-icons`, 11 SVGs bundled) for languages; add dialog offers the
    printing's languages only; pagination with page numbers and go-to-page.
  - Catalog search by printed language (`lang`). Code search uses card id subqueries
    (an OR of correlated EXISTS took 43 s on 50k Pokémon cards; now ~35 ms).
  - OCR: MTG old frames (number at the end of the copyright line or on the right, years
    ignored), Pokémon labels touching Japanese names, set code box on its own line,
    number matches ordered by detected language.
  - Dropped: condition of the lowest offer (Cardmarket's public price guide has a single
    `low` per product, no condition, seller or country).
  - Android: Collection tab (value, search, game/condition/language filters, sorts incl.
    price, quick +1/-1 with undo); search with game chips, set picker, color and
    printed-language filters, load more; card sheet is a `ModalBottomSheet` (swipe
    down to just look) with OCR reading (name, flag, set/number), prices + lowest offer,
    Cardmarket link, owned badges, searchable printing picker; Cardmarket condition colors
    and emoji flags (same maps as the web); "After adding copies: stay / scan next".
  - Android OCR "Automatic" (new default, new DataStore key `ocr_script`): Latin reads
    every frame; the frame sent is also read by the Japanese, Korean and Chinese models
    and the one that found its own script wins (`ScriptPicker`). Needs a real phone
    check with Japanese and old-frame cards.

- [ ] Feedback batch 3 (started 2026-10-14), branch `feedback-batch-3`: server 0.5.0,
  Android 0.4.0. Plan below; phases ticked as they land.
  - [x] A quick fixes: version (`FUDABAKO_VERSION` build arg in images, else package
    version) in `/api/health`, web sidebar, Android settings; `Select` component
    (searchable from 11 options); card page printings sort; catalog image follows set;
    scroll to top on page change; FR "versions".
  - [x] B jobs: progress heartbeat (HTTP answers + stored batches), 15 min stall and
    per-kind time limits, restart reaping by owner, manual takes over auto (cancel flag
    polled every 5 s), worker schedule from auto runs only, complete job reports.
  - [x] C last_seen_at on card/printing, `services/refresh.py` stale rule (missed by last
    successful catalog sync + 24 h, or no image source / no attributes; prices left
    out: many printings are legitimately unpriced), provider `fetch_cards` (Scryfall
    `oracleid:` search, TCGdex per printing + missing-image languages, Sorcery cached
    catalog), refresh on card view (BackgroundTasks, once an hour), `refresh` job (48 h).
  - [x] D price sources: `fudabako.prices` plugins (`app/prices`: Cardmarket EUR,
    TCGplayer USD from Scryfall `usd*` and TCGdex `pricing.tcgplayer`), quotes tagged with
    `source`, `attributes.market_ids`, sources with their own API (`fetch`, called by the
    prices job after the provider). Deviation: one prices job per game (not per source):
    provider data carries several sources in one download. User `price_source` (fallback:
    game's first source); per-currency values, never added up; card page shows every
    source + links; `TCG_APITOKEN_*` helper (`api_token`). Docs: `docs/price-sources.md`.

## Feedback batch 3 plan

### Context
User feedback list (server + Android). Every item studied for feasibility. All can be done
except **CardNexus** (API keys need manual approval by CardNexus) — **dropped by user**, may come
back later; the price source plugin system below makes it a drop-in addition.
Decisions from Q&A:
- Secondary catalog sources: **MTGJSON** (MTG), **pokemontcg.io** (Pokémon). Sorcery: none exists.
  Secondaries fill missing fields; disagreements logged for admins; primary wins.
- Manual sync **cancels** a running auto run of same game + kind, starts at once; manual runs never shift worker schedule.
- Preferred price source: **per-user setting** (default Cardmarket); card page shows all sources.
- Stale = card missed by last successful full catalog sync (checked once that sync finished + 24 h), or missing image / price / attributes.

Second price source (proves modularity without CardNexus): **TCGplayer (USD)**, already present
in data we download (Scryfall `prices.usd*` + `tcgplayer_id`, TCGdex `pricing.tcgplayer`,
pokemontcg.io `tcgplayer`). No new API.

Branch `feedback-batch-3` off `main`. Keep `PLAN.md` progress section updated (memory rule).

### Phase A — quick fixes (web + small server)
1. **Catalog page change scrolls to top**: `web/src/lib/hooks.ts` `useUrlState.set` — add scroll
   option; Catalog.tsx:95 and Collection.tsx:158 pass it (`window.scrollTo({top:0})`, check
   drawer scroll container in browser).
2. **i18n FR "Versions"**: `web/src/locales/fr.json` every "impression(s)" meaning printing →
   "version(s)" (`{{count}} printings_*`, Jobs image import message, ImportExport text, any other
   hit from `grep -i impression`); same in `android/app/src/main/res/values-fr/strings.xml`.
3. **App version**: single source = `backend/pyproject.toml`. `app/__init__.py`
   `__version__ = importlib.metadata.version("fudabako")`; `user_agent` default built from it
   (`core/config.py:43`); `FastAPI(version=...)`; `/api/health` returns `{"status","version"}`.
   Web: `useHealth()` query, Layout.tsx aside becomes `flex flex-col`, version `mt-auto` bottom-left
   (`v0.5.0`, small muted text). Android: `BuildConfig.VERSION_NAME` line in SettingsScreen.kt
   (+ server version from `/api/health` beneath).
4. **Searchable selects, n = 10**: >10 options is where scanning a list gets slow (Hick's law,
   common combobox threshold); all small lists here (conditions 7, sorts, roles, ≤10 languages)
   stay native. New `web/src/components/Select.tsx`: same props as a select (`value, onChange,
   options[{value,label}]`); ≤10 → daisyUI `<select>`; >10 → daisyUI dropdown with filter input
   (accent-insensitive, reuse `normalize()` from CardDetail.tsx:40), keyboard ↑↓/Enter/Esc. Replace
   all selects in pages (list in exploration: Filters.tsx `SetSelect`, Collection, Dashboard,
   ImportExport, Settings, admin) so the rule applies everywhere automatically.
5. **Card page printings sort**: CardDetail.tsx — select (uses `Select`) next to set filter box,
   client-side on `c.printings`: Owned first (default, current order), Newest, Oldest, Set name,
   Collector number, Price high→low, Price low→high. In URL `?sort=`. New labels added to
   `DYNAMIC` in `web/scripts/check-i18n.mjs` + fr.json.
6. **Catalog images follow selected set**: `api/catalog.py:279-293` — when `set_id` given, prefer
   printings of that set in image choice. Web: `useQuery` with `placeholderData: keepPreviousData`
   so grid stays and only images swap.

### Phase B — jobs: timeout, manual vs auto, empty reports
Migration on `sync_run`: `trigger` (`auto`|`manual`), `heartbeat_at`, `cancel_requested bool`.
1. **Heartbeat + timeout** (`services/jobs.py`): job runner passes a `JobContext` to services;
   `services/catalog.py`, `prices.py`, `images.py` call `ctx.tick()` per batch → updates
   `heartbeat_at`, raises `JobCancelled` if `cancel_requested`. Watchdog: run with no heartbeat
   for 15 min → `failed`, error "Stuck: no progress for 15 min". Hard limit per kind via
   `asyncio.timeout` (catalog 6 h, prices 2 h, images 6 h, refresh 2 h) → `failed` "Timed out".
   Watchdog runs on API start, worker start, each worker tick and in `start_job` (replaces lazy
   6 h `STALE_AFTER`).
2. **Manual cancels auto**: `POST /api/admin/jobs/{game}/{kind}` → if an `auto` run is running,
   set `cancel_requested`, wait ≤ 60 s for it to stop (poll), else mark it failed "Cancelled by
   manual run"; then start manual run. Manual vs manual still 409. Worker `is_due`/`RETRY_AFTER`
   (`worker.py:53-80`) read only `trigger='auto'` runs; manual runs ignore intervals and retry
   delay (already true), only provider rate limits apply. Cancelled auto run status `cancelled`
   (new enum value), retried at next tick.
3. **"failed 0 · stored 0 · missing 0"**: from images job when nothing to do (cached printings not
   counted, `images.py:190-194`) and prices job edge cases. Fix: `ImageReport` adds `cached`,
   `refused`; `PriceReport` adds `targets`, `unmatched`; admin endpoint refuses price job for a game
   without price source (400). Web Jobs.tsx: translated labels per key, "Nothing to do" when
   all counters 0.

### Phase C — last seen, staleness, on-demand + periodic refresh
1. Migration: `card.last_seen_at`, `printing.last_seen_at`, `card.refresh_attempted_at`
   (timestamptz, indexed on `(game_id, last_seen_at)`). Catalog upsert (`services/catalog.py`
   all `ON CONFLICT` sets) writes `now()` — every row a sync touches gets it, changed or not.
   Backfill: set to last successful catalog run start.
2. `services/staleness.py`: `stale_cards(game)` query = `last_seen_at < start of last successful
   full catalog sync` AND now > that sync's `finished_at + 24 h`, OR no printing with an image
   URL, OR empty card attributes, OR (game has prices) no price snapshot. Internal only, not in
   API schemas.
3. Provider protocol (`games/base.py`): optional `fetch_cards(http, refs) -> AsyncIterator[CatalogBatch]`
   (refs = card + printing external ids/attributes). MTG: Scryfall `POST /cards/collection` by
   `scryfall_id`, 75 per call, 100 ms spacing. Pokémon: TCGdex `/{lang}/cards/{id}` (existing
   `_cards`). Sorcery: whole `/api/cards` (single call, cached in memory 1 h) filtered.
4. **Card page refresh**: `GET /api/cards/{id}` — if card stale and `refresh_attempted_at` older
   than 1 h, set it and schedule refresh in `BackgroundTasks`; response gets `refreshing: true`;
   web refetches once after ~5 s.
5. **Stale job every 48 h**: new job kind `refresh` in worker (`TCG_REFRESH_INTERVAL_HOURS=48`),
   chunks of stale cards through `fetch_cards`; report `checked, updated, not_found`. Admin page
   gets the button too.

### Phase D — modular price sources
1. New plugin type, entry point group `fudabako.prices` (pyproject.toml). `app/prices/base.py`:
   `PriceSource` protocol: `id`, `name`, `currency`, `games: set[str]`, `link(printing) -> str|None`,
   `fetch(http, game_id, targets) -> AsyncIterator[list[PriceQuote]]`; optional `token` via
   helper below. Same features as Cardmarket today: trend, low, avg, history, min/max, links.
2. `app/prices/cardmarket.py`: move `games/cardmarket.py` + per-game Cardmarket code out of
   providers (MTG guide by `cardmarket_id`, Pokémon TCGdex `pricing.cardmarket`, Sorcery product
   matching). `app/prices/tcgplayer.py`: Scryfall `usd/usd_foil/usd_etched`, TCGdex/pokemontcg.io
   `tcgplayer` (market/low/mid → trend/low/avg). Providers keep yielding raw source data in
   `CatalogBatch.prices` tagged with source id.
3. Generic market ids: `printing.attributes["market_ids"] = {"cardmarket": id, "tcgplayer": id}`
   (migration moves `cardmarket_id`). API: `PrintingOut.links[{source,name,url}]`,
   `PriceOut.source, currency`; `GameOut.price_sources[]` replaces `cardmarket`/`has_prices`.
4. Price data: snapshot `source` values normalized to `cardmarket` / `tcgplayer` (migration).
   `services/collection.py:169` `latest_prices` filters by source (fixes arbitrary pick between
   sources). Jobs: `sync_run.source` column, price jobs per (game, source).
5. User setting `price_source` (default `cardmarket`, `PATCH /api/auth/me`, Settings page,
   Android settings). Values, min/max, sort and collection totals use it; no currency mixing —
   items without a price in that source count as unpriced. Card detail shows every source
   (table per source with currency). Web `format.ts` money uses price currency; Android same.
6. **API tokens**: `core/config.py` helper `api_token(kind, name, category=None)` reading
   `TCG_APITOKEN_{KIND}_[{CATEGORY}_]{NAME}` (e.g. `TCG_APITOKEN_GAMES_PKM_POKEMONTCG`,
   `TCG_APITOKEN_PRICES_CARDNEXUS` later). Category for games = short game code (MTG, PKM, SOR).
   `.env.example` new "API keys" section documenting the rule and each used variable. Token sent
   only by the source that owns it.

### Phase E — secondary catalog sources + cross-check
1. Protocol: game package exposes optional `secondary_sources: list[CatalogSource]`
   (`id`, `fetch(http, ids) -> AsyncIterator[CatalogBatch]` with `partial=True` data keyed on
   primary external ids). Catalog job runs primary, then each secondary (report per source).
   Existing partial merge (`services/catalog.py:65-134`) fills gaps only.
2. **MTGJSON** (`games/mtg/mtgjson.py`): `AllPrintingsCSVFiles` (cards.csv, cardIdentifiers.csv,
   cardForeignData.csv, sets.csv) streamed; join on `scryfallId`. Fills foreign names, missing
   `cardmarket`/`tcgplayer` ids, rarity, artist.
3. **pokemontcg.io** (`games/pokemon/pokemontcg.py`): `/v2/sets`, `/v2/cards?pageSize=250`,
   optional key `TCG_APITOKEN_GAMES_PKM_POKEMONTCG` (header `X-Api-Key`; without key lower limits).
   Set mapping to TCGdex by `ptcgoCode`/name + release date, card by collector number. Fills
   images (EN), rarity, artist, tcgplayer prices/ids.
4. **Cross-check**: table `catalog_discrepancy` (game, printing/card/set id, field, primary value,
   secondary value, source, first_seen, last_seen; unique per entity+field+source). Compared:
   name, rarity, collector number, set total, release date. Admin page "Data checks" (list + filter
   by game/source). Primary value kept.
5. Recorded fixtures for both sources (tests refuse network).

### Phase F — advanced catalog search per game
1. Provider declares `filters: list[FilterDef(key, label, field)]`, `field` = `rarity` (printing
   column) or card attribute key (string or list).
   - MTG: `types` (new card attribute parsed from `type_line`: supertypes + types, e.g.
     Legendary, Creature), `subtypes`, rarity. `catalog_version` 2 → resync at once.
   - Pokémon: `category`, `trainerType`, rarity. Sorcery: `type`, `subtypes`, rarity.
2. `GET /api/games/{id}/filters` → distinct values per filter (cached in memory, cleared after
   catalog sync). `/api/cards` accepts `attr=key:value` (repeatable, AND) and `rarity`; GIN
   `jsonb_path_ops` index on `card.attributes`.
3. Web Catalog: "Advanced" collapsible panel under game tabs (colors + these filters with
   `Select`), state in URL, cleared on game change. Labels translated.

### Phase G — local visual assets
Card front images already proxied + cached. Remaining external:
- MTG back face (`attributes.back_image_url`, loaded directly by CardDetail.tsx:103): served by
  `/api/printings/{id}/image?face=back`, cached same way (`images.py`).
- Set icons (`CardSet.icon_url`, Scryfall SVG / TCGdex PNG): cached by images job into
  `images/sets/`, served `/api/sets/{id}/icon`; `SetOut.icon` local link (raw URL removed from API).
  Shown next to set names on card page and set select.
- Color symbols: already local. Flags: bundled.

### Phase H — Android
1. **Printing search beyond 30**: identify response gains `printing_count`. New
   `GET /api/cards/{id}/printings?q=&limit=50` (server-side filter on set name/code, number,
   year; reuse `_escape_like`, `f_unaccent` from catalog.py:105-116; same printing shape).
   PrintingPicker.kt: local filter first; when `printing_count > loaded` and query ≥ 2 chars,
   debounced (300 ms) server query, results merged. Counter shows "x / 870".
2. **Unknown card fallback** (server side; app holds no external keys): identify with no
   candidates but recognized hints → optional provider `lookup(http, hints)`:
   MTG Scryfall `/cards/{set}/{number}/{lang}` else `/cards/named?fuzzy=`; Pokémon TCGdex
   `/v2/{lang}/sets/{set}/{number}` else name search; Sorcery cached full catalog + name match.
   Found → upsert via catalog service, re-run identify, response `fetched: true`. Negative
   results cached 1 h per hint set (no API hammering). App: toast "Card added from {source}".
3. **App version** in settings (Phase A3).
4. **OCR JA/KO/ZH** (Pokémon tested, all CJK affected):
   - `ScanStabilizer.words()`: CJK runs split into character bigrams so one misread glyph does
     not break stability (today whole line = one token).
   - AUTO mode: today CJK models run only after Latin model is stable — never on CJK cards.
     Add second stabilizer fed every 3rd frame by the CJK model last picked by `ScriptPicker`
     (round-robin JA/KO/ZH until one finds its script); first stabilizer to fire wins.
   - `TextAnalyzer.kt:72`: log exceptions instead of swallowing.
   - Server `pokemon/provider.py` `_SKIP`: Asian trainer/energy labels (サポート, グッズ,
     トレーナーズ, スタジアム, エネルギー, 서포트, 아이템, 支援者, 物品…).
   - `identify.py` CJK names: pg_trgm weak on 2-5 glyph names → for CJK queries add substring
     match (`search_name LIKE`) and `word_similarity`, lower threshold. Check prod `SHOW lc_ctype`.
   - Fixtures: KO + ZH Pokémon cards, JA name-only test.
   Needs real-phone check by user (emulator camera can't).

### Order and versions
A → B → C → D → E → F → G → H (H1/H3 can go early). Server 0.5.0 (pyproject), Android 0.4.0
(build.gradle.kts default). After each phase: tests, PLAN.md progress line, commit.

### Verification
- `cd backend && pytest` (new tests: heartbeat/watchdog/timeout, manual cancels auto, reports,
  last_seen + stale query, fetch_cards per provider with fixtures, price sources + user
  preference + no currency mixing, MTGJSON/pokemontcg.io merge + discrepancies, attribute
  filters, set icon cache, printings endpoint, identify lookup fallback, CJK name matching).
- `cd web && npm run gen:api && npm run build && npm run lint && npm run check:i18n`.
- Browser (dev compose, Playwright): catalog scroll on page change, set → images swap, advanced
  filters per game, searchable set select (>10) vs native (≤10), card page sort, FR "Versions",
  version bottom-left, admin jobs: manual during auto run, report labels, Data checks page,
  price source switch in Settings.
- Live syncs: MTG + MTGJSON, Pokémon + pokemontcg.io; check discrepancy counts sane, refresh job.
- Android: `./gradlew testDebugUnitTest lint assembleDebug`; emulator: settings version, picker
  server search ("eigh" on Forest finds Eighth Edition). Real phone (user): JA/KO/ZH Pokémon scan.


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
