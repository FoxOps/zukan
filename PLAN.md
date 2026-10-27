# Zukan (図鑑, "illustrated encyclopedia") — Plan

Self-hosted TCG collection manager. Named Zukan on 2026-10-13 (was "TCG MGMT").
Product name, CLI (`zukan`), Python package and plugin entry point group
(`zukan.games`) use the new name. Configuration identifiers keep their short `TCG`
prefix (`TCG_*` environment variables, `tcg_*` cookies, `tcg` database), so existing
`.env` files keep working.

## Context
User want one tool to manage TCG collections (MTG, Pokémon, Sorcery), with new games added later via plugins. Need card name, colors, price (Cardmarket), stock, image, set; cards have multiple printings across sets. Android app scans cards by OCR, shows info, then adds/removes stock. Greenfield: `/home/pierre/Projets/TCG_MGMT` is empty.

Decisions from Q&A:
- Self-hosted web app (Docker), multi-user, separate collection per user.
- Prices: from APIs only (Scryfall → Cardmarket EUR for MTG, TCGdex → Cardmarket for Pokémon), Cardmarket's public price guide files for Sorcery (since 2026-10-13), manual override everywhere. No scraping (agreed exceptions: Konami card database for Yu-Gi-Oh!, pokemon-card.com for Japanese Pokémon pictures).
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
  - `daisyui` (v5): components (navbar, drawer, card, table, modal, badge, stat), custom themes `zukan` (light) / `zukan-dark` from the Zukan identity (since 0.15.0)
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
Registry via Python entry points (`zukan.games`), so new game = new package implementing protocol, no core change. Web/Android read game metadata (colors, finishes, languages) from `GET /games` — no hardcoded game logic in clients.

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
- **Provisioning**: first SSO login auto-creates user if allowed (username from `preferred_username`, email). Role from group claim on each login (admin group → admin). Not in `allowed_groups` → refused. Local and SSO accounts are separate (since 0.19.0; linking from settings removed), never matched by email (avoids account takeover); the IdP manages SSO users' email and password.
- **Logout**: revoke app refresh token; optional RP-initiated logout via IdP `end_session_endpoint`.
- Local accounts stay available (bootstrap admin, fallback if IdP down); admin can disable local login once SSO works.
- Docs: setup notes for Keycloak, Authentik, Authelia client config (redirect URIs, group claim mapping).

## Providers
- **MTG / Scryfall**: daily bulk `all_cards` (all languages, large; stream-parse with `ijson`) for printings + localized `printed_name`; prices from `prices.eur`/`eur_foil` (Cardmarket trend). Respect 50–100 ms between requests and User-Agent header.
- **Pokémon / TCGdex**: per-language endpoints (`/v2/{lang}/sets`, `/cards`); EN and JA set lists differ — treat JA sets as own sets, linked by name when possible. Prices from `pricing.cardmarket` (trend, avg, low, holo variants).
- **Sorcery**: `GET /api/cards` (30 req/min, one call is enough), printings with finishes Standard/Foil/Rainbow; images from public image folder; English only; no prices (manual).
- **Riftbound** (since 0.9.0): Riot content API (approved key) or Riftcodex, plus Riot's card gallery (newest set, Simplified Chinese); Cardmarket game 22 and TCGplayer (tcgcsv) prices.
- **Gap sources** (since 0.9.0, `app/sources/`): tcgcsv, tcg-api.eu, apitcg fill what the game's own sources lack, for every game they cover.
- **Yu-Gi-Oh!** (since 0.10.0): YGOPRODeck (TCG cards, sets, printings per code + rarity, EU names, TCGplayer prices), YGOJSON (Asian names, OCG sets), Konami database (newer cards, budgeted); Cardmarket game 3.
- **Lorcana** (since 0.10.0): LorcanaJSON (en/fr/de/it, Cardmarket + TCGplayer ids); Cardmarket game 19, TCGplayer via tcgcsv 71.

## OCR identification (`services/identify.py`, `POST /scan/identify`)
Phone sends OCR text lines + bounding boxes + chosen game (or auto). Server:
1. Provider `parse_ocr` extracts collector number + set code (bottom line, language-independent — key for JA/ZH/KO) and name (top line).
2. Exact match on (set code, collector number) → printing.
3. Fallback: trigram fuzzy match on `card_name` across languages, rank candidates.
4. Return top candidates with image, set, colors, price, and user's current owned quantity per finish/condition/lang.
Phone shows best match; user can swipe other printings, choose finish/condition/language, tap Add / Remove. Endpoint `POST /collection/adjust` (delta), returns new quantity; undo via transaction.

## Android app
Package `fr.zukan.app`, app name "Zukan", SSO redirect `fr.zukan.app:/oauth2redirect`.
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
    Drive folder (files named after printing slugs) via `zukan import-images` or admin endpoint.
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
  `fr.zukan.app.dev` (own SSO redirect). Release keystore kept outside the repo,
  stored in `ANDROID_KEYSTORE_*` secrets.
- [x] First start (2026-10-13): nobody could sign in on a fresh deployment. The API now
  creates the administrator `admin` / `changeme` on start while the user table is empty
  (`TCG_DEFAULT_ADMIN_USERNAME` / `TCG_DEFAULT_ADMIN_PASSWORD`, empty password disables).
  Compose data moved from named volumes to `./data` (dev `./data-dev`); the image
  entrypoint starts as root, chowns `/data/images` (Docker creates missing bind mount
  folders as root) and drops to `tcg` with `setpriv`.
  `.env` is now the only configuration entry point: `auth.yaml` dropped, SSO providers
  come from `TCG_OIDC_PROVIDERS` + `TCG_OIDC_<NAME>_*`, host port from `ZUKAN_PORT`.
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

- [x] Feedback batch 3 (2026-10-14), branch `feedback-batch-3`: server 0.5.0,
  Android 0.4.0. Plan below; phases ticked as they land.
  - [x] A quick fixes: version (`ZUKAN_VERSION` build arg in images, else package
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
  - [x] D price sources: `zukan.prices` plugins (`app/prices`: Cardmarket EUR,
    TCGplayer USD from Scryfall `usd*` and TCGdex `pricing.tcgplayer`), quotes tagged with
    `source`, `attributes.market_ids`, sources with their own API (`fetch`, called by the
    prices job after the provider). Deviation: one prices job per game (not per source):
    provider data carries several sources in one download. User `price_source` (fallback:
    game's first source); per-currency values, never added up; card page shows every
    source + links; `TCG_APITOKEN_*` helper (`api_token`). Docs: `docs/price-sources.md`.
  - [x] E secondary catalog sources (`secondary_sources` on providers, `CatalogSource`
    protocol, `services/crosscheck.py` run by the catalog job after the primary):
    MTGJSON CSV files (market ids, rarity/artist gaps; name, rarity, set name, release
    date compared) and the Pokémon TCG API **data files on GitHub** (the pokemontcg.io API
    answered 500, it is being replaced by the paid Scrydex; same data, no key): English
    images, rarity/artist gaps; set matched by id/ptcgoCode/name+date. Secondary writes
    do not touch `last_seen_at`; market ids merge key by key. `catalog_discrepancy`
    table, `GET /api/admin/discrepancies`, web "Data checks" page. A failing secondary
    never fails the catalog job.
  - [x] F advanced search: provider `filters` (`FilterDef`: card attribute or printing
    rarity). MTG `types`/`subtypes` parsed from the type line (catalog_version 2), Pokémon
    category / trainer type / stage, Sorcery category / type / subtypes, rarity
    everywhere. `GET /api/games/{id}/filters` (distinct values, 1 h cache),
    `/api/cards?attr=key:value` (`@>` on a GIN `jsonb_path_ops` index), catalog
    "Advanced search" panel.
  - [x] G local assets: `images.cached_asset` (download once to `stem.<ext>`, SVG allowed,
    failures retried after an hour), MTG back faces `/api/printings/{id}/image?face=back`
    (`PrintingOut.back_image`), set icons `/api/sets/{id}/icon` (`SetOut.icon`, raw URL no
    longer in the API), both prefetched by the images job; SVG served with
    `Content-Security-Policy: default-src 'none'` (color icons too).
  - [x] H scan + Android 0.4.0: server `printing_count` on candidates,
    `GET /api/cards/{id}/printings?q=`, unknown-card lookup (`services/lookup.py`,
    provider `lookup`: Scryfall set/number or fuzzy name, TCGdex set/number with English
    listing first, Sorcery exact name; misses cached 1 h; `IdentifyOut.fetched`), CJK
    name containment scoring + Asian label skipping. App: picker searches the server past
    the 30 loaded printings, version in settings, price source setting, prices per
    market with currency (`Format.kt`), market links, OCR: CJK character pairs in the
    stabilizer, AUTO mode reads every 3rd frame with one Asian model (own stabilizer),
    recognition errors logged. Real-phone check of JA/KO/ZH cards still needed.
  - Live check (2026-10-14, API from the venv on port 8010, fresh database): Sorcery 1601
    printings + 1516 images; Pokémon EN 21k printings, pokemontcg data 165/176 sets
    matched, 20k printings cross-checked; MTG 530k printings, MTGJSON 103k cross-checked.
    Discrepancies after spelling-insensitive comparison: MTG 2, Pokémon 1126 (mostly
    rarity vocabularies: "Secret Rare" vs "Rare Rainbow"; real finds such as BLK 060).
    Browser: version, searchable selects, advanced search, scroll on page change, FR
    "versions", printings sort, jobs reports, data checks. "eigh" on Forest (870
    printings) finds the 8 Eighth Edition ones in 51 ms. Links from the server open only
    when http(s) (web and app).

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
   `__version__ = importlib.metadata.version("zukan")`; `user_agent` default built from it
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
1. New plugin type, entry point group `zukan.prices` (pyproject.toml). `app/prices/base.py`:
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


## Catalog GUI rework (script-aware names and images, one page per printing)
Mockups approved by the user 2026-10-14 (long catalog names wrap, never truncated).
- [x] Server (`services/scripts.py`, `services/display.py`, `api/catalog.py`):
  - Non-Latin = ja, ko, zh-*, th, ru, uk, el, ar, he… A card is non-Latin only if every
    printing is in a non-Latin set (set lang; sets without a lang, e.g. MTG: every printing
    language non-Latin). First available language order: en fr de it es pt ja ko zh-hant
    zh-hans th ru, then alphabetical.
  - Latin/mixed: image lang UI > en > first available; name UI > en > first available.
  - Non-Latin: image lang UI if non-Latin > set lang > first non-Latin > en > first available;
    name "Name (Translation)": name UI if non-Latin > set lang > first non-Latin, translation
    UI if Latin > en > first Latin (dropped when missing or identical).
  - Language first, then printing: latest set > first > any (undated last); refused
    downloads (empty path) skipped; no image: placeholder.
  - Set filter / code search: the card is shown as printed in that set (script, set lang,
    images); falls back to all printings when that set has no image.
  - Printings are named as printed in their own set. New fields (additive):
    `CardSummaryOut.translation/printing_id`, `CardOut.translation/default_printing_id`,
    `PrintingOut.name/translation`.
- [x] Web: `/cards/:cardId/:printingId` (one page per printing; `/cards/:cardId` redirects to
  `default_printing_id`), table rows navigate (sort kept), finish selector (`?finish=`,
  default cheapest) drives "This version" stat and price history chart; catalog tiles link
  to their printing and wrap long names; collection links open the printing.
- [x] Same naming everywhere: collection items, stock transactions (dashboard) and scan
  candidates are named as printed in their own set (`show_printing`/`show_card`), with
  `translation`; item images use the chosen language. Web shows it through `ShownName`.
- [x] Android 0.5.0 (no card screen: the scan sheet `ResultPanel` is the card view):
  Search and Collection rows show Name (Translation); Search opens the catalog's printing
  (`printing_id`, else `default_printing_id`); sheet title is the printing's name; finish
  chips drive This version, plus Cheapest / Most expensive / Lowest offer when every
  printing is loaded (`PriceStats.kt`). No price chart. New fields optional (old servers OK).
- [x] Versions: server 0.6.0 (`pyproject.toml`, README, `.env.example`), Android 0.5.0
  (`build.gradle.kts`, README). 119 backend tests, 23 Android unit tests, debug build and
  lint pass (JDK 27 locally).
- [ ] Check on the real catalog: done by the user (Pokémon has 205 sets without a language,
  MTG has no set languages: the printing's languages decide; Russian MTG printings).


## Backlog 2026-10-14 (server 0.7.0, Android 0.6.0)
User list from the 0.6.0 test deployment. Root causes found on its data (read-only).
- [x] Sync / data quality: TCGdex reuses set ids across language families (JA `neo2`
  遺跡をこえて is not EN `neo2` Neo Discovery) so JA cards landed in EN sets and got English
  images through pokemontcg.io number matching ("030" = "30"). Asian sets colliding with a
  European id become `asia:<id>`; pokemontcg only touches printings with `en`; bad TCGdex JA
  names ("a", "Smeargle") fixed from `dexId` species names; names replaced on full data;
  changed image URLs re-downloaded; pokemontcg task cleanup + transport retries; TCGdex set
  symbols from the language path (`/univ/` returns 400). Admin "Reset catalog" per game keeps
  owned printings.
- [x] MTG lowest offer: catalog job overwrote the prices job's `low`/`avg` with NULL
  (`store_quotes`): keep existing values.
- [x] Several price sources per user (`price_sources`, first = primary for totals); card page,
  price history, links and Android show only the selected ones.
- [x] Catalog: set select width bug (`Select.tsx` regex ate `sm:` prefix); advanced filters
  always shown.
- [x] Jobs page: live chrono, server-computed elapsed time.
- [x] HTTP errors: JSON 500s, translated client messages, themed error / 404 pages.
- [x] Android: identify `status` (`not_found` / `not_a_card`), shown in the scan pill.
- [x] CI: dev builds publish pre-releases `server-dev-<branch>` / `android-dev-<branch>`.
- [x] Versions server 0.7.0, Android 0.6.0. 124 backend tests, 26 Android unit tests, lint, builds.
- [x] Live check on a separate 0.7.0 stack (fresh data, Pokémon en+ja): neo1-4 Japanese sets stored as
  `asia:neo*`, Unown A named アンノーンA without English image, Japanese Smeargle joined the English card,
  pokemontcg cross-checked 20 265 printings (no failure), 128 set icons cached (21 missing upstream).
  Playwright: catalog row layout, filters shown, live job chrono, one / two price sources on card page, 404.
- [ ] To do by the user: Reset catalog on the 8000 test service (Pokémon), MTG lowest offer after a prices
  job, real-phone scan check.


## Backlog 2026-10-15 (server 0.8.0, Android 0.7.0)
Branch `2026-10-15-000-feedback-batch-4` (branch names from now on: `DATE-NUMBER-NAME`).
Progress (plan below):
- [x] Versions: server 0.8.0, Android 0.7.0.
- [x] A session: `/api/auth/me` refreshes like any request (only login/refresh/logout/oidc are
  excluded), rotated refresh tokens accepted again for 60 s while the family is alive
  (`refresh_token.rotated_at`), access 1 h / refresh 90 days sliding, login loads `me` before
  leaving the page and older requests can no longer end the new session (`markSignedIn`).
- [x] B catalog GUI: grayed images = Chrome keeping the dimmed paint of `backface-hidden`
  layers after the grid's `opacity-60` was removed (computed opacity was 1, a hover repainted):
  no more grid dimming (spinner next to the count), no per-tile fade-in, `backface-hidden`
  only on double-faced cards. Search ✕ button + Esc (and follows the URL). Sort by card number
  or name inside a set (`sort`, `order`; natural number key `number_sort_key`, also used by the
  collection). Set, sort, colors and advanced filters in one box; `color_mode=exact`. Flip
  button (`FlipIcon`) on every double-faced picture, catalog tiles flip in place
  (`CardSummaryOut.back_image`, `ItemOut.back_image`), back loaded on first flip.
- [x] C account email: `POST /api/auth/email` (current password when the account has one,
  `null` removes), Settings "Change" form; admin Users "Set email".
- [x] D stock dialog: "Version" select (searchable over 10) listing every printing of the card,
  newest first, default the page's printing; finish/language kept when the new version has them.
- [x] E collection: `ItemOut.trends` (`d1/d7/d30` direction + change, ±2 % = stable, from the
  user's price source history, `services/collection.price_trends`), Trend column between Qty
  and Unit (`TrendIcons`: arrow in a circle). Views registry `web/src/pages/collection/views.tsx`
  (List default, Images grid with flip/qty/trend), `?view=` + localStorage; colors "exactly" too.
- [x] F admin: worker schedule moved to `services/schedule.py` (`next_run`), `GET
  /api/admin/schedule`, Jobs page "Next run: in 3 hours (date)". Data checks tabs: Source
  differences (Open / Arbitrated, per row Keep main / Use second / Edit, Reopen; per field rule
  "always main / always second", `catalog_field_rule`) and Stale cards (`GET /api/admin/stale`
  with reasons, `POST /api/admin/cards/{id}/refresh`, Refresh all = refresh job). Chosen values
  are written at once and again after every catalog sync and card refresh
  (`crosscheck.apply_resolutions`).
- [x] G Pokémon (`catalog_version` 4): TCGdex `th` and `id` (Asian family; default languages
  en fr de it es pt ja zh-tw th id). Korean from type-null/PTCG-database `data_ko` (repo
  archive, ~33 MB, 20k cards) and Simplified Chinese from duanxr/PTCG-CHS-Datasets (~10 MB,
  232 products) in `games/pokemon/asia.py`: a set id TCGdex has (Korean M2 = Japanese M2) gets
  names/images by collector number, others become sets (`lang` ko / zh-hans); Pokémon join the
  English card through species names (Chinese: species found in the name, `find_species`).
  Chinese foil versions ("C★", "C★★") = reverse / holo finishes of one printing; Korean decks
  reusing a number get `number~ko_id`. Downloaded at every catalog sync (cards must be seen;
  deviation from the plan's "skip when unchanged"). Empty sets pruned after each sync.
  Live data parsed: KO 263 sets / 20 029 cards (13 731 named in English), CN 232 / 14 162
  (9 888). Existing deployments: Reset catalog (Pokémon) drops the old TCGdex ko/zh-cn data.
- [x] H OCR. Server: `status: other_game` + `detected_game` when a game is chosen and another
  game's markers are read (`identify.other_game`); name-only reads of 4+ lines count as
  `not_found` (Sorcery prints no set code); Simplified/Traditional variants of Chinese names
  (`opencc-python-reimplemented`, `ocr.chinese_variants`), `script_language` by conversion;
  Pokémon `1阶进化` / `进化自` labels. App 0.7.0: `CardTurn` — sideways lines (ML Kit `angle`)
  or 6 weak frames: the frame is read at 0/90/270° and the best turn kept (landscape cards);
  pill "This is a {game} card" + Switch; AUTO: a model that found its script reads every frame
  (3 misses to stop), the Japanese model reading only Han hands over to the Chinese one.
  Real-phone check by the user: Sorcery sites, MTG card with Pokémon chosen, Chinese cards.
- [x] Tests: 134 backend, 29 Android unit tests, Android lint + debug build, web build/lint/i18n
  (351 texts), migration on a fresh database + `alembic check` (no drift).
- [x] Live check (2026-10-15, API from the venv on port 8010, fresh database, access token 60 s):
  - Session: access expired, two tabs reloading at once both refreshed (second through the
    grace period) and stayed signed in.
  - Sorcery 1601 printings; MTG (default_cards) 109 505 printings, MTGJSON 103k cross-checked.
  - Pokémon en+ja+th + datasets: 787 sets, 71 408 printings (en 21 290, ja 13 006,
    ko 20 029, zh-hans 14 162, th 2 921), 54 empty sets pruned, pokemontcg 1 126 differences.
    Korean M2 001 is the `ko` language of the Japanese M2 printing; Chinese 151C Pikachu joined
    the English Pikachu card. Found and fixed: a 330-character illustrator list (promo
    collage) failed the insert; boxes reusing a number for other cards were merged as foils;
    mainland Chinese set codes ("151C", "CS5aC", "CS4.5C") were not read by the OCR parser.
  - Browser: flip button on catalog tile (fixed: the hover lift moved the button under the
    pointer and the click opened the card page) and card page; stock dialog switched INR 457 to
    DBL 47; trend column (+24.6 % / 0 % / −33.5 % from test history) and image view; sort by name
    and number in a set; "exactly these colors" 241 → 201 Sorcery water cards; clear search;
    email change; Jobs next run; arbitration ("Use second" renamed Imposter Professor Oak,
    card count rule resolved 20) ; identify: MTG card with Pokémon chosen = `other_game`,
    噴火龍 finds 喷火龙V, 151C 025 exact.
  - Known TCGdex data issue (not ours): some Thai listings number cards differently from the
    Japanese set, so a few Thai names land on another card (SV2a Pikachu got "วาไนเดอร์").
- [ ] User: real-phone OCR checks; Reset catalog (Pokémon) on deployments to drop the old
  TCGdex ko / zh-cn data; check `TCG_POKEMON_LANGUAGES` in `.env` (old lists keep ko/zh-cn).

### Context
User backlog after 0.7.0 / 0.6.0: 13 server items (session, email, collection trend + views,
catalog GUI, admin jobs/checks/arbitration, Pokémon Asian sync) and 3 Android OCR items.
Exploration found root causes for the session complaints and the Pokémon gaps (below).

Decisions (Q&A 2026-10-15):
- Mainland China Pokémon: TCGdex is unusable (every `…C` zh-cn set has `cards: []`, no 151C,
  zh-cn cards with data are copies of zh-tw sets without images). Use GitHub dataset
  **duanxr/PTCG-CHS-Datasets** (`ptcg_chs_infos.json`, 232 products incl. 151C/CSV9C, images
  in `img/<id>/<n>.png`, updated monthly; licence non-commercial/no redistribution — the
  self-hosted server downloads it itself, we ship nothing).
- Korean: type-null/PTCG-database `data_ko` (MIT). Thai / Indonesian: TCGdex only, no scraping.
- Arbitration: per row + bulk (field × source), **sticky** (stored, re-applied after syncs).

Branch `2026-10-15-000-feedback-batch-4` off `main` (format DATE-NUMBER-NAME). Versions: server
0.7.0 → **0.8.0** (`backend/pyproject.toml`, README, `.env.example`), Android 0.6.0 → **0.7.0**
(`android/app/build.gradle.kts` default `versionName`, README `gh workflow run` lines). PLAN.md:
new section "Backlog 2026-10-15 (server 0.8.0, Android 0.7.0)" with this plan, ticked per phase;
commit per phase.

### Phase A — session (bugs first)
Root causes:
1. `web/src/api/client.ts:47-60` never refreshes for `/api/auth/*`, so `/api/auth/me` 401 after
   the 15 min access token = sent to login although the 30-day refresh cookie is valid.
2. `security.py:rotate_refresh_token`: a refresh token presented again after rotation revokes the
   whole family. Two tabs (or a reload during a refresh) both refreshing → family revoked → logout.
3. Login race: `Login.tsx:26-39` only invalidates `['me']`; a request that started before login
   can fail its refresh afterwards and fire `onSessionExpired` (`Layout.tsx:46-53`) → back to login.

Fixes:
- client.ts: refresh on 401 for every path except `/api/auth/login|refresh|logout|oidc/*`.
- Refresh grace: `refresh_token.replaced_at`; reuse within 60 s of rotation issues another token in
  the same family instead of revoking it (migration adds column). Revocation still on later reuse.
- Lifetimes: access 15 min → 1 h, refresh 30 → 90 days, sliding (each rotation renews). Env vars
  `TCG_ACCESS_TOKEN_TTL_SECONDS` / `TCG_REFRESH_TOKEN_TTL_SECONDS` documented in `.env.example`.
- Login: `client.setQueryData(['me'], user)` from the login response, then navigate. client.ts keeps a
  `sessionEpoch` bumped on login; `onSessionExpired` ignored for requests started in an older epoch;
  Layout listener does nothing when already on `/login`.
- Tests: refresh reuse within grace OK / after grace revokes family; web build.

### Phase B — catalog GUI (`web/src/pages/Catalog.tsx`, `web/src/components/Filters.tsx`)
1. **Grayed images**: suspects `opacity-60` on `isPlaceholderData` (:77) + `animate-in fade-in` tiles
   (:82) leaving a stale composited layer (hover transform repaints it). Reproduce with Playwright
   first (systematic debugging), then fix: drop per-tile `animate-in`, dim with a `transition-opacity`
   only while fetching, never on settled data.
2. **Clear search**: `SearchInput` gets an ✕ button (daisyUI `input` with `join`) + Esc, clears URL `q`
   at once; local state re-syncs when URL `q` changes (current bug: init once).
3. **Sort when game + set selected**: `/api/cards` `sort=name|number` + `order=asc|desc` (only honoured
   with `set_id`; natural collector-number order — reuse collection set sort expression in
   `api/collection.py:289-296`). Select next to the set, in URL.
4. **Sets + colors in the advanced box**: `SetSelect` and `ColorFilter` move into the `bg-base-200`
   panel (shown when a game is selected). Color mode select: "Including these colors" (default,
   today's `colors @> sel`) / "Exactly these colors" (`@>` and `<@`). `/api/cards?color_mode=include|exact`
   (`api/catalog.py:398`), same param on `/api/collection` for free.

5. **Double-faced cards made visible** (added 2026-10-15): today `CardImage.tsx` flips on a click
   anywhere with only a hover `title` and pointer cursor, so the feature is invisible (and
   impossible on touch / keyboard). Fix:
   - Flip **button** overlaid bottom-right of the image (`btn btn-circle btn-sm` on a translucent
     `bg-base-100/80` backdrop, shadow): inline SVG "flip" icon (two circular arrows around a card,
     like the user's reference; lucide `refresh-cw`-style arrows + card outline). `aria-label`
     and tooltip "Show back" / "Show front", keyboard focusable, icon rotates 180° with the card.
     Shown whenever `back` exists, on every `CardImage`.
   - Card page: clicking the image still flips too.
   - **Catalog tiles and collection image view flip as well**: same button on the tile; its click
     does `preventDefault` + `stopPropagation` so it flips in place instead of following the tile
     link (clicking the rest of the tile still opens the card page). Server adds
     `back_image: str | None` (local link `/api/printings/{printing_id}/image?face=back`, as
     `PrintingOut.back_image`) to `CardSummaryOut` and `ItemOut` when the shown printing has
     `attributes.back_image_url`. Back image `loading="lazy"`, fetched only after the first flip
     (no extra downloads for a page of tiles).
   - i18n EN/FR.

### Phase C — account email
- `SettingsIn` (`api/schemas.py:45`) gains `email` (+ `current_password`, required when the user has a
  password). Validate format (pydantic `EmailStr` if `email-validator` present, else regex), `null`
  clears. Handler `api/auth.py:187`. SSO: `services/sso.py` keeps not overwriting an edited email.
- Settings.tsx account card: editable email field + password confirm. Admin Users page: edit email in
  the row (endpoint already supports it). i18n EN/FR.

### Phase D — card page stock dialog printing switch
`web/src/components/StockDialog.tsx`: optional `printings` prop (CardDetail passes `c.printings`) →
`Select` (searchable > 10) "Version" at top, default the page's printing; switching updates finishes
and languages and keeps quantity/condition. Over the loaded list: `GET /api/cards/{id}/printings?q=`.

### Phase E — collection trend column + views
1. **Trend**: `services/collection.py` `price_trends(keys, source)`: latest trend vs the snapshot
   nearest on/before today − 1/7/30 days (`DISTINCT ON`), per (printing, finish) of the page.
   Direction with ±2 % neutral band (constant). `ItemOut.trends: {d1,d7,d30: {dir, pct} | null}`
   (null = no history; manual price items still show the market trend).
   Web column between Qty and Unit: `24h ◔ | 7d ◔ | 30d ◔`; new `TrendIcon` (inline SVG, circle with
   zig-zag arrow up / flat line / arrow down — lucide `trending-up/-down/minus` shapes, `text-success /
   text-base-content/50 / text-error`), tooltip with %.
2. **Views**: `web/src/pages/collection/views.tsx` registry `{id, label, icon, component}`;
   `ListView` = current table (default), `ImageView` = grid like Catalog (`CardImage`, qty badge,
   −/+ buttons, trend, total). Toggle in the toolbar, `?view=` in URL + localStorage. New view = one
   entry. Collection.tsx keeps data/filters, views receive items + handlers.

### Phase F — admin
1. **Next run on Jobs page**: `worker.py` pure `next_run(game, kind, now)` reusing `interval`,
   `_outdated`, `RETRY_AFTER` (due now → next tick, ≤ 5 min). `GET /api/admin/jobs` adds
   `schedule[{game, kind, next_run_at, enabled}]` (refresh only when `can_refresh`). Jobs.tsx shows
   "Next run: in 3 h (15:20)" per kind.
2. **Stale cards** (Data checks tab): `GET /api/admin/stale?game&page` from `services/refresh.py`
   `stale_condition` with reason (not seen / no image / no attributes); `POST /api/admin/cards/{id}/refresh`
   runs `_refresh_card` now (timeout 60 s) and returns the result; "Refresh all" starts the `refresh` job.
3. **Arbitration** (sticky):
   - Migration: `catalog_discrepancy.resolution` (`primary|secondary|custom`), `resolved_value`,
     `resolved_by`, `resolved_at`; table `catalog_field_rule (game, source, field, prefer)` for bulk.
   - `POST /api/admin/discrepancies/{id}/resolve {choice, value?}`; `POST /api/admin/discrepancies/rules`
     `{game, source, field, prefer}` (+ DELETE) resolves every open row of that field and future ones.
   - `services/crosscheck.py`: after primary + secondaries, apply `secondary`/`custom` resolutions to the
     entity (name/rarity/number/set name/total/release date/artist), rule-matched new discrepancies
     resolved automatically. Primary sync no longer undoes them.
   - Checks.tsx: filter Open / Resolved, per-row "Keep / Use second / Edit", bulk on the counts table.

### Phase G — Pokémon Asian data (`backend/app/games/pokemon/`)
Root causes: `th` and `id` absent from `LANGUAGES`/`BASE_ORDER`/`ASIAN` (provider.py:61-76;
`fetch_catalog` ignores others, env can't enable them); zh-cn and ko = TCGdex gaps (ko: 239 cards,
no image); empty sets never pruned.
Sources per language (decided 2026-10-15): ja/zh-tw/th/id = TCGdex; zh-hans = PTCG-CHS-Datasets;
ko = **type-null/PTCG-database** `data_ko` (MIT, 20 323 cards / 264 sets, read from Pokémon Korea's
official site, official image URLs, `pokedex_number`); th/id = **TCGdex only** (no scraping; gaps
stay until TCGdex fills them — documented).
1. Add `th`, `id` (Asian family; TCGdex reuses ja ids → names/images join existing Asian sets; Thai-only
   ids SV7s… become own sets). `services/scripts.py` order gets `id`. `.env.example` list.
1b. **Korean** `ko_data.py`: drop TCGdex `ko` from defaults. Skip when the last commit touching
   `data_ko` (`GET /repos/type-null/PTCG-database/commits?path=data_ko&per_page=1`) is unchanged;
   else stream the repo tarball (`codeload.github.com/.../tar.gz/<sha>`) and read only
   `data_ko/<set>/<n>.json` (no full checkout on disk). Set `set_name` (M2…) = Asian set id: joins the
   existing ja set as language `ko` by number (name, `img` image URL), Korean-only ids become sets
   with `lang=ko`, `set_full_name`, `set_total`, `set_img` icon. Card join via `pokedex_number` +
   species names (as ja `dexId`); rarity, `author`, hp, stage, types attributes. Images downloaded by
   the image job from `cards.image.pokemonkorea.co.kr` (served locally as always). `TCG_POKEMON_KO_DATA`
   (default on). Recorded fixture tarball with 3 cards.
2. Drop TCGdex `zh-cn` from defaults. New `ptcg_chs.py`: download `ptcg_chs_infos.json` (skip when the
   GitHub commit sha is unchanged), each product → set `zh-hans` lang (Asian family, `asia:` collision
   rule), cards → printings (number from `collectionNumber`, rarityText, illustrator, hp/type/evolve
   attributes), images `raw.githubusercontent.com/.../img/<id>/<n>.png` via image job. Cards join the
   English card through `species_names.json` zh-hans names (same as Asian TCGdex). `TCG_POKEMON_CHS`
   (default on). `catalog_version` bump → resync. Recorded fixture subset for tests.
3. Catalog sync prunes sets left with 0 printings (not owned).

### Phase H — Android OCR (`android/app/src/main/java/fr/zukan/app/scan/`) + identify
1. **Landscape cards**: `TextAnalyzer.kt:71` — when ML Kit lines have median `angle` near ±90° (or the
   Latin read is weak for 6 frames), read the frame again with `rotationDegrees ± 90` and keep the
   orientation that wins (remembered until it stops working). Sorcery Site fixture on the server.
2. **Other-game card**: `services/identify.py:189` — with a game selected and no candidate, run the
   other providers' `parse_ocr`; recognized → `status: "other_game"`, `detected_game`. Also Sorcery
   name-only reads count as `not_found` (`api/scan.py:119-124`). App pill: "Looks like a {game} card"
   + "Switch" action; strings EN/FR.
3. **Chinese**: server `opencc-python-reimplemented` — identify tries simplified + traditional variants of
   CJK queries; `script_language` (`games/ocr.py:24`) uses conversion difference instead of 6 chars;
   Pokémon `_SKIP`/`_STAGE` add `进化`/`進化` forms. App AUTO: when the Latin read is weak (few Latin
   letters), Asian model every frame and stick to the last winning one. zh-hans data from Phase G helps.

### Verification
- `cd backend && pytest` (new: refresh grace/reuse, email change, color_mode exact, number sort,
  trends, next_run, stale list + refresh endpoint, resolve/rules re-applied after sync, th/id grouping,
  CHS fixture import + empty set prune, other_game status, zh variants).
- `cd web && npm run gen:api && npm run build && npm run lint && npm run check:i18n`.
- Playwright on dev stack: login → wait access expiry (set TTL 60 s in dev) → no logout, two tabs;
  catalog clear ✕, sort, advanced box + exact colors, grayed image repro gone, MTG double-faced
  card (e.g. Delver of Secrets): flip button on card page and on its catalog tile (flips without
  navigating; tile body still opens the card page); collection trend column +
  image view; stock dialog version switch; email change; Jobs next run; Data checks stale + arbitration.
- Live Pokémon sync (separate stack): Thai names on SV2a, Thai-only sets, Indonesian names, Korean M2
  printings with images, CHS 151C / CSV9C with images.
- Android: `./gradlew testDebugUnitTest lint assembleDebug`; real phone by user: Sorcery Site, MTG card
  with Pokémon selected, Chinese cards.


## Backlog 2026-10-16 (server 0.9.0, Android unchanged 0.7.0)
Branch `2026-10-16-000-riftbound-new-sources`. User list: MTG art series shown as
double-faced; new sources apitcg.com, tcg-api.eu, tcgcsv.com (English, texts + USD prices);
new game Riftbound (Riot API, card gallery), then Riftcodex added. Android: nothing.
API keys given for tests are only used from the environment, never committed.

Decisions (Q&A 2026-10-16):
- Riftbound main source: Riot content API when `TCG_APITOKEN_GAMES_RFB_RIOT` is set, else
  Riftcodex (open API, added by the user after the Q&A). The given Riot key is a
  development key: valid (LoL status 200) but refused on `riftbound/content/v1` (403, every
  region) — Riftbound needs a product key approved by Riot. The Riot parser follows the
  published schema, untested live. Riot's official card gallery (`__NEXT_DATA__` JSON of
  `playriftbound.com/{en-us,zh-cn}/card-gallery/`, one page each per sync: exception to "no
  scraping", Riot's own published data) adds cards the APIs lack (Radiance, not in
  Riftcodex yet) and Simplified Chinese names/pictures (other locales show English cards).
- apitcg, tcg-api.eu, tcgcsv: every game each one covers, **only to fill missing data**,
  current games first, generic so a future game is one mapping entry.

Probed data (2026-10-16): Riftcodex 1451 cards / 8 sets (ids not unique: Metal prints share
the plain card's id, Vendetta listed twice with and without TCGplayer id, some Vendetta
legends named by title only); gallery 1408 cards (`-star-` = `*` in ids); Cardmarket
Riftbound = game 22; tcgcsv categories Magic 1, Pokémon 3, Sorcery 77, Riftbound 89 (Sorcery
products have no number); apitcg 16 games (TCGplayer data, 1000 requests/month); tcg-api.eu
Pokémon / Magic / Lorcana / One Piece (10k/day, 100/min, no prices).

Progress:
- [x] MTG `art_series`: no `back_image_url` (two fronts), migration drops stored ones.
- [x] Riftbound (`games/riftbound/`): card = name + subtitle ("Ahri, Alluring"), printing =
  Riftbound id (`ogn-066a-298`; shared ids get `~variant`), variants (Alternate Art,
  Signature, Metal...) as printing attributes, domains as colors (Riot CDN symbols, plus
  colorless), finishes guessed from rarity (common/uncommon normal + foil, others foil) until
  TCGplayer's versions confirm them (`finishes_confirmed`), `zh-hans` names and pictures,
  Riot symbol codes spelled out in rules text (`:rb_energy_2::rb_rune_chaos:` = "2 Chaos"),
  OCR of the collector line (`OGN • 066a/298`), `lookup` / `fetch_cards` from the cached
  catalog, `legal_notice` (Riot §6 text, `GameOut.legal_notice`, web footer).
- [x] Cardmarket name matching shared by Sorcery and Riftbound (`cardmarket.match_products`):
  expansions known from Riftcodex (promo expansions spanning PR / JDG / OPP), others by the
  largest name overlap first (a starter deck no longer takes a set from its expansion).
- [x] Gap sources (`app/sources/`, entry points `zukan.sources`): `printing_gaps` (English
  picture, rarity, artist, TCGplayer id, guessed finishes) per set; set matching by code
  ("sv01" = "sv1", aliases), name + date, name; printing pairing by TCGplayer id, number,
  name (Sorcery). Partial fills only; differences on name, rarity (words) and rules text
  (`text_attribute`: MTG `oracle_text`, Sorcery `rules`, Riftbound `text`; reminder text
  in parentheses ignored, same words = same text). A gap source only clears earlier
  differences of the sets it checked (`SecondaryBatch.checked_sets`). The index is rebuilt
  before each source. Order: tcgcsv (free), tcg-api.eu, apitcg (smallest quota last).
- [x] Quotas: `api_usage` (requests per source and day / month, counted before sending),
  `RequestBudget` (+ pace per minute), `gap_check` (a quota source skips a set whose gap
  count did not change for 30 days). `TCG_APITCG_MONTHLY_REQUESTS=900`,
  `TCG_TCGAPI_EU_DAILY_REQUESTS=9000`; keys `TCG_APITOKEN_GAMES_APITCG` /
  `_TCGAPIEU`, skipped without.
- [x] TCGplayer prices from tcgcsv for printings no other source priced today
  (`MarketTarget.quoted`), only the groups of those sets. Sorcery and Riftbound now list
  TCGplayer as a price source.
- [x] Web: legal notice footer, Data checks source names, Riftbound texts in French.
- [x] Versions: server 0.9.0. Tests: 147 backend (Riftbound fixtures trimmed from real data,
  no keys), web build / lint / i18n (361 texts), migration on a fresh database + `alembic
  check`.
- [x] Live check (2026-10-16, fresh database, CLI jobs from the venv, API on port 8011,
  keys from the environment only):
  - Riftbound: Riot key refused (403, logged) → Riftcodex; 9 sets / 1114 cards / 1593
    printings (Radiance 219 from the gallery, 1416 with Simplified Chinese), 45 s. Cardmarket
    matched 1468 printings (Ahri Alluring €0.55, alternate art €5.59), TCGplayer from tcgcsv
    1487 ($0.76 / $5.95). tcgcsv confirmed finishes; apitcg filled what was left (15
    requests), next run 0 requests (sets with unchanged gaps skipped).
  - Sorcery: tcgcsv gave 1474 / 1601 printings their TCGplayer id by name, 1469 USD prices.
  - Pokémon: tcg-api.eu 141 requests (10 231 printings checked), apitcg 161; tcgcsv priced 39
    groups of printings TCGdex had no TCGplayer price for. MTG (all_cards, 17 min): tcgcsv 70
    sets with gaps, tcg-api.eu 89 requests, apitcg 146. Month total apitcg 322 / 900.
  - Found and fixed on live data: differences cleared for sets a gap source did not
    re-check; discrepancy rows dated before the run start (transaction began with the
    index) deleted at once; noise (MTG: 38 258 differences on 25 138 printings → 113):
    TCGplayer rarity letters (C/U/R/M/L) and categories (promo, token, Unconfirmed — never
    filled), MTG oracle vs printed text (MTG text not compared), names of double-faced cards
    and Universes Beyond ("Bag End - Horizon Canopy"), tokens sharing a card's number
    (pairing by number now needs a matching name), Riftcodex plain text without line
    breaks (rich text used), Riot symbol codes. Left as real differences: Riftbound
    "Showcase" vs "Rare" on alternate arts, TCGplayer typos ("DEATKNELL"), Pokémon rarity
    vocabularies ("Holo Rare V" / "Ultra Rare": a field rule silences them).
  - MTG art series: 2655 printings, none with a back face; the migration SQL removed
    injected ones. Transform cards keep theirs.
  - Browser: Riftbound catalog (domain symbols, Type / Supertype / Tag / Rarity filters,
    prices), card page (3 printings, Cardmarket links, price history), Riot notice in the
    footer; internal attributes (`finishes_guessed`, `finishes_confirmed`, `domains`) hidden.
- [ ] User: a Riot product key for Riftbound (developer portal application), then check the
  Riot path; keys for tcg-api.eu / apitcg in `.env` on deployments.


## Backlog 2026-10-16 #2 (server 0.10.0, Android 0.8.0)
Branch `2026-10-16-001-ygo-lorcana-rarity-icons`. User list: rarity pictograms for every
game (Cardmarket's or other sources) next to the rarity text; Riftbound landscape pictures
turned to fit; own Riftbound colorless symbol; Catalog list view (images stay default);
"Name (Translation)" for every non-Latin script, not only Japanese; new games Yu-Gi-Oh!
(YGOPRODeck, Konami database) and Lorcana (best of lorcana-api.com, api-lorcana.com,
Lorcast, LorcanaJSON); Android on par with the server (games, visual cues); `.env.example`
up to date. API keys given for tests: environment only, never committed.

Decisions (Q&A 2026-10-16):
- Rarity pictograms: Cardmarket's inline SVGs (product lists, "Rarity" column), collected
  once from a browser and shipped in `backend/app/games/<game>/rarities/<code>.svg`
  (`scripts/install_rarity_icons.py`); own SVG only where Cardmarket has none. Cloudflare
  refuses scripted requests (403) and rate-limits browsers hard (429 after ~3 pages, blocks
  of 10+ minutes): pages were opened one at a time, minutes apart.
- Yu-Gi-Oh!: YGOPRODeck main; YGOJSON (MIT, frozen 2026-04) for translations and OCG sets;
  Konami database (scraping agreed: the publisher's own data) only for newer cards,
  budgeted. Printing = set code + rarity; finishes = editions (Unlimited / 1st / Limited).
- Rotation: Riftbound only (printing attribute `orientation`).
- Lorcana: LorcanaJSON (official Ravensburger data in 4 languages with Cardmarket and
  TCGplayer ids; Lorcast is English only, the others have less). No Japanese/Chinese data
  anywhere yet.

Probed (2026-10-16): YGOPRODeck `cardinfo.php` 21 MB, 14 615 cards, 44 667 TCG printings,
142 set codes reused by several sets (tins) → sets keyed on their name (migration widens
`card_set.external_id` to 128, `printing.rarity` to 64, rarities up to 39 characters);
YGOJSON `individual.zip` 57 MB, read entry by entry (3.4 s, 146 MB peak), 2080 OCG sets /
82 878 printings; Konami card pages give the Japanese/Korean name and every pack line
(date, `YAC1-JP071`, pack, rarity code). Cardmarket Yu-Gi-Oh! = game 3 (87 390 products,
no numbers), Lorcana = 19; tcgcsv Yu-Gi-Oh! 2, Lorcana 71.
Translation gaps (test service DB): 2 387 Japanese and 1 131 Simplified Chinese Pokémon
cards without any Latin name: Trainers/Energies (no source pairs them with English names),
regional / Mega / Radiant forms, owner forms ("ナツメのゴース"), fan names in old TCGdex
Japanese listings.

Progress:
- [x] Display: any name shown in a non-Latin script gets its Latin translation, whatever
  chose it (UI language zh/ja/ko on a Latin card, Riftbound Simplified Chinese).
- [x] Pokémon names: form words derived to English (Galarian/Alolan/Hisuian/Paldean, Mega
  X/Y ex, Radiant, Shining, Dark, Single/Rapid Strike, δ), species found without dex id;
  after every catalog sync (any game) a card without Latin name copies those of the only
  card of the same category sharing one of its names (zh-hans ↔ zh-hant via opencc), report
  `translations`. Owner forms and Trainers without a paired card stay untranslated.
- [x] Riftbound: `orientation` on `PrintingOut` / `CardSummaryOut` / `ItemOut`, web
  `CardImage landscape` (picture turned a quarter, not cropped); colorless = gray diamond
  SVG shipped (`ColorDef.icon_file`).
- [x] Rarities: `RarityDef` per game (code, name, aliases of every source's spelling),
  `rarity_of`, `GameOut.rarities` with icon links, `GET /api/games/{id}/rarities/{code}/icon`,
  `rarity_code` on printings, summaries and items, rarity filter ordered by rarity. Web
  `RarityBadge` (pictogram + text): card page header and printings table, collection list
  and images, item dialog, catalog tiles and list.
- [x] Catalog list view (`pages/catalog/`: images default, list with picture, name, version,
  rarity, colors, price), shared `ViewToggle` / `useView` (`lib/views.tsx`) with Collection;
  `CardSummaryOut.set` / `collector_number` of the shown printing.
- [x] Yu-Gi-Oh! (`games/yugioh/`): colors = attributes (YGOPRODeck icons) + Spell / Trap;
  Cardmarket matched by expansion name overlap (97 % of TCG printings, 4.5 s), several
  rarities of a name paired in rarity order; TCGplayer from `set_price`; OCR of the set
  code (region letters give the language, European codes stored under the English one).
- [x] Lorcana (`games/lorcana/`): card = full name, printing = LorcanaJSON id, promos in a
  set per promo group, variants a/b/c, finishes from foil types, symbols written out in texts
  (⬡ Ink, ◊ Lore, ⟳ [Exert]...), OCR of the collector line.
- [x] Android 0.8.0: rarity pictogram + text, color symbols (SVG via `coil-svg`), landscape
  pictures turned, flip button for double-faced cards, collection price trends (24h/7d/30d);
  games come from the server (Yu-Gi-Oh!, Lorcana need no app change).
- [x] `.env.example`: `TCG_YUGIOH_LANGUAGES`, `TCG_YUGIOH_KONAMI_DAILY_REQUESTS`, source notes.
- [x] Rarity pictograms: Cardmarket's for Lorcana (8) and Riftbound (5); Cloudflare then
  blocked this address for hours, so the others are drawn for Zukan
  (`scripts/draw_rarity_icons.py`, only where no file exists): Pokémon's printed shapes
  (● ◆ ★, black / silver / gold, one to three stars), colored gems per tier for MTG, Sorcery,
  Yu-Gi-Oh!, Lorcana Special and Riftbound Promo; dark shapes have a light outline for the
  dark theme. Collecting Cardmarket's later: `install_rarity_icons.py` overwrites them.
- [x] Gap sources: a code's several rarities pair by rarity (`rarity_in_printing` for
  Yu-Gi-Oh!), rarity spellings of one game rarity are no difference ("Short Print" = Common),
  TCGplayer editions map to Yu-Gi-Oh! finishes; Yu-Gi-Oh! texts not compared (errata).
- [x] Web: card page keeps its picture column when the price stats are wide; Yu-Gi-Oh!
  `konami_id` / `frame` hidden; French texts of the new games (383 texts).
- [x] Tests: 161 backend, web build / lint / i18n, Android 32 unit tests + lint + debug APK,
  migration on a fresh database + `alembic check`.
- [x] Live check (2026-10-16, fresh database `zukan_live`, CLI jobs, API on port 8011):
  - Lorcana: 20 s, 28 sets / 2785 cards / 3556 printings, 5893 Cardmarket prices; tcgcsv
    differences 57 → 18 after writing symbols out (left: TCGplayer typos, "Quest" rarity).
  - Yu-Gi-Oh!: 6–9 min, 2577 sets (1036 TCG, 885 ja, 518 ko, 120 zh-hans, 18 zh-hant) /
    14 869 cards / 124 625 printings / 84 995 prices (Cardmarket + TCGplayer); Konami pages
    added newer packs (LPST-JP / LPST-KR); 1420 pages wanted at first (≈5 days at 300 a day).
    tcgcsv differences 11 045 → 1 045 (texts no longer compared, rarity pairing).
  - Riftbound: battlefields upright in the frame, colorless diamond; browser: Lorcana catalog
    images + list views with rarity pictograms, Dark Magician page (10 languages, OCG sets).
- [ ] User: Chinese UI check on real Pokémon data after the next catalog sync (translations
  copied are counted in the job report); Cardmarket pictograms for Pokémon, MTG, Sorcery,
  Yu-Gi-Oh! if wanted (browser, a page every few minutes).


## Backlog 2026-10-17 (server 0.11.0, Android unchanged 0.8.0)
Branch `2026-10-17-000-ygo-tcg-ocg-languages`. User list: Yu-Gi-Oh! catalog job "Stuck: no
progress for 15 min"; languages missing on Magic and Yu-Gi-Oh! (priority); Lorcana ink,
Sorcery colorless, Yu-Gi-Oh! Spell / Trap pictograms; trademark notices on an "À propos"
page; a richer dashboard; Yu-Gi-Oh! TCG / OCG sets. Android: nothing.

Findings:
- Stuck job: from the worker container every Konami database request timed out in the TLS
  handshake (30 s). Timeouts never reach the response hook that reports progress, so 30 of
  them made the 15 minutes; failed requests also used the day's budget and were asked
  again every run. Cause: the host goes through WireGuard (MTU 1420), Docker's bridge
  used 1500 and Imperva's large handshake packets were lost (same request: 30 s timeout
  on the default bridge, 200 in 1.4 s on a 1420 network).
- Languages: no stored data was lost. Card pages opened on the newest printing with a
  picture in the UI language, often an English-only Secret Lair / promo (≈ 6 000 Magic
  cards, 1 500 Yu-Gi-Oh!), and the header listed that printing's names only. Yu-Gi-Oh!
  had a real bug since 0.10.0: YGOJSON rarity slugs (starlight, platinumsecret...) never
  equalled YGOPRODeck's names, so 2 300 printings kept English only.

Decisions (Q&A 2026-10-17):
- Magic (every game): a card shows a printing sold in several languages before a newer
  single-language one; the header lists the card's names over every printing.
- Yu-Gi-Oh!: one rule for every region. A TCG set ("Burst of Destiny (TCG)") holds every
  language printed with its code: BETB-EN/FR/DE/IT/PT/SP/KR/SC/TC024 are languages of
  BETB-EN024 when it is the same card and rarity, else their own printing in that set.
  Japanese sets are the OCG ones, named in Japanese ("… (OCG)"). A code no TCG set has
  (Korean-only products) keeps a set of its own, original name + " (TCG)".
- Dashboard: value by game, most valuable cards, price movers, data sync status (admins).
- Notices: one short line on every page + "À propos" page with each publisher's notice.

Progress:
- [x] Stuck job: `konami.fill` reports progress after every attempt, gives the budget back
  on network errors (`RequestBudget.refund`), stops after 5 network errors in a row; YGOJSON
  download reports progress per MB. Compose networks on `TCG_NETWORK_MTU` (default 1420).
- [x] Yu-Gi-Oh! languages: `yugioh/codes.py` (`rarity_key`, `number_key` without region,
  "LOB-001" = "LOB-EN001", old one-letter regions E / F / G / I / P / S / K),
  `YgoJson.european_of` (code + rarity, or code alone when YGOJSON has one rarity).
- [x] `display.pick_image`: multi-language printings first. `CardOut.names`: every name.
- [x] Yu-Gi-Oh! TCG / OCG (`catalog_version` 2): `_Placer` puts Korean / Chinese printings
  (YGOJSON, Konami) in the TCG set of their code; printing attribute `numbers` (printed
  code per language, shown under the collector number). Generic `CatalogBatch.moved`
  (`PrintingMove`): owned copies move to the new printing (merged with an existing line,
  history kept), the old printing is deleted (report `moved`). Cardmarket matching skips
  printings with no European language. Gap sources also match sets on their external id
  (plain YGOPRODeck name).
- [x] Printed codes of any region: provider `code_lookup` used by the catalog search
  ("BETB-FR024", "BETB-KR024") and scan identification.
- [x] Pictograms drawn for Zukan (`scripts/draw_color_symbols.py`): Lorcana ink hexagons,
  Sorcery colorless (cards without element, `catalog_version` 3), Yu-Gi-Oh! Spell / Trap.
- [x] Notices for Magic (Wizards Fan Content Policy), Pokémon, Sorcery; Riftbound data
  credit. Web `/about` page, footer line + link on every page, sidebar link.
- [x] Dashboard: `GET /api/collection/movers` (value change × quantity), `GET
  /api/admin/overview` (latest run per game and kind, quotas); widgets value by game,
  most valuable cards, movers 24h / 7d / 30d, data sync (admins).
- [x] Yu-Gi-Oh! sets YGOJSON (frozen 2026-04) lists in no English / European locale
  (BETB, MAMO, RA05...): their TCG printings get the six European languages, flagged
  `languages_guessed` (hidden in the web UI). Sets YGOJSON lists in English only (North
  America "na" locale) stay English. Set names unescaped ("Legendary 5D's Decks").
- [x] Versions: server 0.11.0. Tests: 169 backend, web build / lint / i18n (401 texts),
  `alembic check` (no schema change).
- [x] Live check (2026-10-17, copy of the 0.10.0 database `zukan_live` as `zukan_check`,
  CLI from the worktree, API on port 8011):
  - Konami from a 1420-MTU Docker network: 200 in 1.4 s (default bridge: 30 s timeout).
  - Yu-Gi-Oh! sync 13 min (5 min without new data): 15 207 Korean / Chinese printings
    moved into TCG sets; owned copies followed (DUNE-KR001 → Duelist Nexus (TCG)
    DUNE-EN001 with ko + zh-hans, MRD-K001 → Metal Raiders MRD-001, BP2-KR001 kept in its
    Korean set "비기너즈팩2 (TCG)"). Sets: 1031 TCG, 885 OCG (Japanese names), 464
    Korean / Chinese-only. English-only TCG printings 5 717 → 4 267; Mosaic 0, Platinum
    Secret 1, Starfoil 9 left English-only. No card lost (`pruned_cards` 400 as in 0.10.0).
  - Search: DUNE-EN001 / -FR001 / -KR001 / MRD-K001 / BETB-DE024 find the TCG card,
    DUNE-JP001 the OCG printing.
  - Browser: dashboard widgets, About page, footer, card page (regional codes under the
    collector number, every language's name in the header).
- [ ] User: keep `TCG_NETWORK_MTU` at 1420 (lower for tunnels with less room), then
  `docker compose down && docker compose up -d` so the network is recreated; check the
  stock dialog languages on Magic cards after deploying.


## Backlog 2026-10-18 (server 0.12.0, Android unchanged 0.8.0)
Branch `2026-10-18-000-image-folders` (on top of 0.11.0's branch, not merged yet). User
asked where to put their own rarity pictograms (they were only shipped inside the app, so
not possible), and for the image folder reorganized per game.

Progress:
- [x] Layout (`services/layout.py`): `data/images/<game>/cards/<set id>/`,
  `<game>/sets/`, `<game>/symbols/`, `<game>/rarity/` (`<game>` = game id); `cache/`
  stays at the root (source caches).
- [x] Own pictures: `<game>/rarity/<code>.<svg|png|webp>` and `<game>/symbols/<code>...`
  win over the shipped ones (`rarity_icon_file`, `symbol_file`; `shipped_rarity_icon` for
  the scripts). Icon links carry `?v=<file time>`, so a replaced file shows at once
  (browsers keep icons a month). README lists the rarity and color codes per game.
- [x] Migration `e4a7c2d9b815`: moves the old folders (`<game>/<set id>/`,
  `sets/<game>/`, `symbols/<game>/`, idempotent, an interrupted move is finished) and
  rewrites `printing.image_paths`; downgrade moves them back. Runs before the API starts
  (`alembic upgrade head` in the image command).
- [x] Tests: 172 backend (move and back, stored paths, own rarity / symbol served with
  their own type). Live: `zukan_check` + its image folder upgraded (42 files, 50 stored
  paths), downgraded and upgraded again, `alembic check` clean.
- [x] Yu-Gi-Oh! Spell / Trap: the official 魔 / 罠 symbols (the ones the user pointed to
  on the Yu-Gi-Oh! Fandom wiki, whose pages and CDN answer 403 to scripts and browsers
  here) downloaded from Konami's card database
  (`…/external/image/parts/attribute/attribute_icon_{spell,trap}.png`) like the other
  attributes; the drawn ones stay as fallback. A downloaded symbol now wins over a shipped
  one (`ensure_symbols` downloads whenever the game folder has none).
- [ ] User: after deploying, check `data/images` has one folder per game; put own
  rarity pictograms in `data/images/<game>/rarity/`.


## Backlog 2026-10-19 (server 0.13.0, Android unchanged 0.8.0)
Branch `2026-10-19-000-lorcana-quest-promo` (on top of 0.12.0's branch). User list:
Lorcana's "Special" rarity mixes Illumineer's Quest cards and promos; Pokémon needs a
symbol for cards without type.

Progress:
- [x] Lorcana (`catalog_version` 2): LorcanaJSON's "Special" split by `_rarity`: sets of
  type "quest" (Q1–Q3) → Quest, a `promoGrouping` → Promo (every Special card is one of
  them: 104 Quest, 215 Promo). Rarities `quest` ("Illumineer's Quest") and `promo`
  replace `special`. Pictograms: the official promo symbol (link given by the user,
  shipped as `rarities/promo.png`; shipped pictograms may now be PNG / WebP), a drawn
  lantern for Quest (the Illumineer's Quest logo is on Fandom, which answers 403 to
  every request from here: the user can drop it in `data/images/lorcana/rarity/quest.*`).
- [x] Pokémon (`catalog_version` 5): color `none` ("No type", drawn: gray disc with ∅,
  Colorless being a type) for Trainers and Energies without type, in TCGdex, Korean and
  Chinese data (`pokemon/types.card_colors`); a Pokémon without type stays without (data
  gap).
- [x] Tests: 173 backend, i18n 402 texts. Live (`zukan_check`): Abu - Cheeky Phantasm
  (Palace Heist 15) Quest, Baymax - Armored Companion (Promos C1) Promo, no Special left.
- [ ] User: Illumineer's Quest logo into `data/images/lorcana/rarity/quest.webp` if wanted.

Release note (2026-10-19): the 0.11.0, 0.12.0 and 0.13.0 images were all built from
a14bbae (main after #11 only: #12 and #13 had been merged into their base branches, then
brought to main by #14 / #15), so their images were deleted and their tags still point at
a14bbae. Server 0.13.1 is the first release with everything (same code as 0.13.0 on
main); Android unchanged 0.8.0.


## Backlog 2026-10-21 (server 0.14.0, Android unchanged 0.8.0)
Branch `2026-10-21-000-security-audit-dashboard-ptcg-removal` (from main after 0.13.1).
User report on 0.13.x + fixes from `docs/security-audit-2026-10-19.md`. Android: no
change (tokens are opaque to it, it already refreshes on 401).

Progress:
- [x] MTU comment shortened (`.env.example`, `docker-compose.yml`): "VPN tunnel".
- [x] Shipped pictures copied to `data/images/default/<game>/rarity|symbols/` on every API
  start (`layout.install_defaults`, `games.base.shipped_folders`): changed files rewritten,
  files no longer shipped removed. Lookup: own / downloaded file in `<game>/...` → copy in
  `default/` → package file. `default/` is skipped by the folder migrations. README.
- [x] Pokémon TCG API removed (`games/pokemon/pokemontcg.py`): Pokémon has no own secondary
  source left (gap sources still fill). Migration `f1c8d3a5b207` deletes its catalog
  checks and field rules and the `images.pokemontcg.io` picture URLs with their cached
  files; `catalog_version` 6 makes the worker resync Pokémon so TCGdex / gap sources refill.
  Live: 1 185 checks and 641 picture URLs removed on the test instance; after the resync
  614 came back from other sources (751 English printings without picture, 724 in 0.13.1).
- [x] Dashboard: value by game back as stat tiles in the top bar; most valuable cards
  (6) on one line (`sm:grid-cols-6`); price movers and data sync each on their own line.
- [x] Collection and Catalog: visible "Sort by" label before the sort list.
- [x] Audit S01: `user.auth_version` (migration `a6e2b9d4c713`); access tokens carry `ver` and
  `sid` (refresh family). `current_user` refuses a token whose version changed or whose
  session is logged out / expired. Password change (own: the browser gets a new session),
  admin reset, disable and `zukan create-admin` reset end every session
  (`security.end_all_sessions`). Pre-0.14.0 access tokens are refused once, clients refresh.
- [x] Audit S02: in-memory sliding windows (`core/ratelimit.py`, one API process): failed
  password sign-ins per account name (10) and per address (50) within 15 min → 429 +
  Retry-After; refresh / SSO requests 60 a minute per address. `TCG_LOGIN_*`,
  `TCG_AUTH_REQUESTS_PER_MINUTE`. Login fields length-limited.
- [x] Audit S03: CSV export puts `'` before text starting with = + - @ (after blanks) or
  tab / CR; import removes it (exact round trip).
- [x] Audit B01: CSV prices must be finite, 0 ≤ price < 10¹⁰, 2 decimals; quantity ≤ 100 000,
  notes ≤ 1000, no NUL (also refused by the item edit API, was a 500), malformed CSV is an
  import error. Found on the way: the sniffed CSV dialect lost doubled quotes, so exported
  notes with `"` could not be imported back; only the delimiter is guessed now.
- [x] Audit D01: npm override `postcss-selector-parser` ^7.1.6 (typography 0.5.20 is the
  latest and pins 6.0.10); prose CSS identical; `npm audit` in CI.
- [x] Hardening: `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'` (added to the SVG
  routes' own policy), `nosniff`, `Referrer-Policy: same-origin` on every answer
  (`core/middleware.SecurityHeaders`); request bodies over `TCG_MAX_REQUEST_BYTES` (6 MB)
  refused with 413 before parsing (`BodyLimit`); forwarded headers only from
  `TCG_FORWARDED_ALLOW_IPS` (default 127.0.0.1, was `*`); card / asset downloads streamed
  and cut at 15 MB (`http.get_limited`).
- [x] Tests: 192 backend. Live (test instance on 0.14.0): password change / admin reset /
  logout end old tokens, 12 bad sign-ins → 10×401 then 429, CSV `NaN` → row error, 7 MB
  upload → 413, headers on `/login`. Browser: dashboard and sort labels.
- Deferred: S04 (bootstrap `admin` / `changeme`) until just before 1.0, by user decision;
  Android cleartext / Keystore tokens; Python lockfile and image digest pinning.
- [ ] User: behind a reverse proxy, set `TCG_FORWARDED_ALLOW_IPS`; drop own pictures in
  `data/images/<game>/...`, not in `default/`.


## Backlog 2026-10-23 (server 0.15.0, Android 0.9.0)
Branch `2026-10-23-000-visual-identity-android-tls` (from main after 0.14.0).
User report on 0.14.0: move the GUI to the new Zukan visual identity (pack "Zukan
Identité visuelle v1.0": owl logo, palette, Nunito / Inter); Android cannot connect to an
FQDN, only error "certificate?" (nginx / NPM on 443 with TLS, 80 → 301; works in Chrome).

Android connection:
- Cause in the app: every `SSLException` became `error_ssl` and the real reason was dropped.
  With the user's setup the likely cause is a proxy sending the leaf without its
  intermediate: Chrome fetches it (AIA), OkHttp refuses.
- [x] `data/Tls.kt`: `SSLException.sslKind()` → HOSTNAME (`SSLPeerUnverifiedException`),
  UNTRUSTED (`CertPathValidatorException` / `CertificateException` in the cause chain),
  PLAIN (TLS sent to a plain HTTP port), OTHER; `sslDetail()` = issuer of the last
  certificate sent (shows the missing intermediate) or the innermost message.
  `userMessage` maps each to its own EN / FR string, detail in brackets.
- [x] `connect()`: `ApiClient.redirectedBaseUrl()` follows a proxy redirect on
  `api/health` (http → https) and keeps the final base URL, so POSTs are not turned into
  GETs by a 301; https → http redirects are ignored (`ServerUrl.redirectedBase`).
- [x] `ServerUrl.normalize`: typed scheme case-insensitive (`HTTPS://x` → `https://x/`).
- [x] Tests (`TlsTest`, `okhttp-tls` test dependency): real local TLS servers — full chain
  works, missing intermediate → UNTRUSTED, other name → HOSTNAME, plain port → PLAIN,
  301 to another base followed. `ServerUrlTest` scheme case + redirect rules.
- [x] README "HTTPS with a reverse proxy": full chain, NPM intermediate field, nginx
  example, `openssl s_client` check, no `:8000` with https.
- [ ] User: install the 0.9.0 APK, connect; the message now names the cause. Most likely
  fix on the proxy: serve `fullchain.pem`.

Visual identity:
- [x] Web: daisyUI themes `zukan` / `zukan-dark` (replace built-in light / dark; stored
  `tcg.theme` values unchanged, `lib/theme.ts` maps them and applies the saved theme before
  the first render so the login page follows it). Radii 12 / 16 px, no depth / noise.
  Gold is a fill (buttons, active menu item); text on cream uses chocolate or green: the
  dashboard total, card page links and catalog tile hover no longer use `text-primary`.
- [x] Web: Nunito 800 headings (unlayered rule, beats `font-semibold`), Inter body; Latin
  woff2 subsets (Inter `opsz` pinned at 14: 132 KB, Nunito 64 KB) + OFL licences in
  `web/src/assets/fonts/`.
- [x] Web: chocolate sidebar with the cream-lettering logo and gold active item, mascot +
  "Zukan" in the mobile navbar, logo on the login page (light / dark variant, `Logo`
  component), mascot on About. Favicons (ico, 16 / 32 / 48), apple-touch-icon,
  `manifest.webmanifest` (192 / 512), `theme-color`; old `favicon.svg` removed.
- [x] Android: `ui/Theme.kt` palette (light `primary` chocolate so text buttons stay
  readable, gold `primaryContainer`; dark `primary` gold), Nunito / Inter variable fonts
  (`res/font/`), shapes 12 / 16 / 20; gold call-to-action buttons (`ctaColors()`); login
  logo (`drawable-nodpi` / `drawable-night-nodpi/zukan_logo.webp`); window background
  cream / night; adaptive launcher icon: gold background, mascot foreground and
  monochrome (themed icons) per density; OFL licences in `assets/licenses/`.
- Domain colours unchanged: rarity gradients, conditions, game colours, price trend.
- [x] Versions: server 0.15.0 (`pyproject.toml`, README, `.env.example` comment), Android
  0.9.0. No new variable.
- [x] Checks: web build, oxlint, i18n; Android `testDebugUnitTest lint assembleDebug`
  (39 unit tests); browser (Vite against the 0.14.0 test API): login, dashboard, catalog,
  card page, light / dark, 390 px width, no console errors, manifest / icons served.

## Backlog 2026-10-23 (server 0.16.0, Android 0.10.0)
Branch `2026-10-23-001-search-finance-cardnexus-pokecardex` (from main after 0.15.0).
User report on 0.15.0 / 0.9.0: card pages need a catalog search to add cards; typing on a
page with a search bar should go to it; a Finance page (whole collection and per game);
CardNexus API as a source (key given for tests only, never committed); Pokémon pictures
and rarity pictograms from Pokécardex (EN FR DE ES JP ZH) and pokemon-card.com, polite
scraping allowed; Android: Mega Pokémon ex not scanned (MEG 22 / 94 / 100, CRI 48); no
confirmation after adding a scanned card (or hidden under the card tray).
Decisions (Q&A): Finance = market value only (no purchase price); card search = typeahead
list; CardNexus = prices + gap source (pictures, missing printings); rarity pictograms per
language.

Scanner:
- Server found these cards on clean text; noisy OCR broke it. `games/pokemon/provider.py`:
  - [x] O / I / l read for 0 / 1 in the number ("O22/132", "1O0/l32"); letter prefixes
    ("TG05") kept.
  - [x] Regulation mark glued to the set code ("IMEG EN" → MEG) or to code and language
    ("ICRIEN 048/122" → CRI, en).
  - [x] "Mega" read as a line of its own joined to the next one.
- [x] `services/identify.py`: number + name similarity ≥ 0.5 scores 0.9 + 0.09 × sim, above
  any name-only match ("M Camerupt ex" + 022 is Mega Camerupt ex, not old M Camerupt-EX).
- [x] Lookup of a card missing from the catalog: `OcrHints.set_external_id` from the stored
  set with the printed code, so TCGdex is asked `/sets/me01`, not `/sets/MEG` (404).
- [x] Android `ScanStabilizer`: the same collector number in two frames counts as the same
  card (holo glare changes the other words), also against the card just sent.
- Checked against the live test catalog: 8 noisy variants of MEG 022 / 094 / 100 and CRI
  048 (EN, FR, split "Mega", glued marks, O for 0) all give the right card first.

Android, add confirmation:
- Cause: the card tray is a `ModalBottomSheet`, a window of its own above the screen's
  snackbar ("Added …", Undo, errors).
- [x] `ScanScreen` gets the app's `SnackbarHostState` and shows a `SnackbarHost` inside the
  tray too (bottom of the sheet).

Web:
- [x] `CatalogSearch` (card page, next to the breadcrumbs): typeahead of 10 cards of the
  card's game (toggle "All games"), picture, set + number, price; ↑ / ↓ / Enter opens,
  Shift+Enter or "+" opens the stock dialog for that card (its versions listed).
- [x] Type to search (`lib/typeToSearch.ts`, in `Layout`): a printable key with no field
  focused and no dialog open goes to the page's search field (`data-type-to-search`:
  Collection, Catalog, card page); "/" only focuses.
- [x] Finance page `/finance` (menu after Catalog): game tabs; value, cards / versions,
  average and median card, priced share; change over 1 / 7 / 30 / 90 / 365 days (amount,
  %, arrow, "no history that far back"); value over time (30 / 90 / 365 d); shares by game,
  card price band, set (top 15), rarity, condition, language, finish (bars + amounts, one
  hue); 10 most valuable cards and their share; movers. Games priced in another currency
  are left out of "All games" and named.
- [x] API `GET /api/collection/finance?game=` (`services/collection.finance`, reuses
  `user_prices`, `value_history`, `unit_price`); test `test_finance`.

CardNexus (`sources/cardnexus.py`, `prices/cardnexus.py`):
- API checked with the key: `GET /v1/feeds/{game}` (bearer, 60 / min) gives presigned
  gzip NDJSON files: catalog (Cardmarket / TCGplayer ids per finish), expansions, prices
  (Cardmarket EUR, TCGplayer USD, CardNexus listings). Checksum = SHA-256 of the
  uncompressed file. Games: mtg, pokemon + pokemon-japan, ygo, sorcery, lorcana, riftbound.
- [x] `Feeds`: one API request per game and run (`RequestBudget`, 50 / min,
  `TCG_CARDNEXUS_DAILY_REQUESTS` 1000), files kept in `<image dir>/cache/cardnexus/`,
  downloaded again only when their checksum changes (400 MB cap).
- [x] Price source `cardnexus` (EUR, lowest listing; link `cardnexus.com/<lang>/explore/…`):
  matched by CardNexus id, else Cardmarket / TCGplayer id; also yields `cardmarket` /
  `tcgplayer` quotes for printings no source priced today; prices over 30 days old skipped.
  Live dry run: Pokémon 35k Cardmarket + 35k TCGplayer + 25k CardNexus quotes, Sorcery,
  Riftbound, Lorcana all priced.
- [x] Gap source (order 15): fills pictures, rarities, artists, TCGplayer / Cardmarket /
  CardNexus ids; adds printings a set lacks (card of that name already stored, set keyed
  on collector numbers, number written like the set's, ≥ 80 % of the set paired — "SV"
  promos vs Supreme Victors otherwise matched wrongly).
- [x] Key `TCG_APITOKEN_PRICES_CARDNEXUS` (skipped without); tests `test_cardnexus.py`
  (respx, no key).

Pokémon pictures and pictograms:
- Pokécardex: page data is encrypted (`__INITIAL_DATA_ENCRYPTED__`) and card scans answer
  403 to scripts (hotlink protection): not used for pictures (no circumvention). Its
  rarity pictograms are plain files of its pages.
- [x] `scripts/install_pokecardex_rarity_icons.py` (ids read from its set pages per zone):
  international pictograms replace Zukan's drawn SVGs (`<code>.png`), Japanese and Chinese
  letter pictograms ("RR", "SAR", "CHR") as `<code>.ja.png` / `<code>.zh.png`; 37 files.
- [x] `rarity_icon_file(game, code, lang)`: `<code>.<lang>`, `<code>.<base lang>`, then
  `<code>` (own folder, then shipped); `RarityOut.icons` {lang: url}, `…/icon?lang=`. Web
  `RarityBadge lang=` (set language, or the copy's), black pictograms inverted on the dark
  theme; Android `RarityBadge(lang =)` tinted with the text colour.
- [x] `games/pokemon/official_jp.py`: pokemon-card.com (official, JSON `resultAPI.php`,
  robots allows) for Japanese printings without a Japanese picture (9 124 of 13 006 on the
  test catalog: every M-era set). Card list kept in `cache/pokemon-card-jp.json` (603
  pages, read once, then only new pages a day), matched by set code (= picture folder) +
  name; same-name cards by the number on their card page (read once). One request a
  second, `TCG_POKEMON_OFFICIAL_JP_DAILY_REQUESTS` 300; `TCG_POKEMON_OFFICIAL_JP`.
  Live run: 388 pictures from the first 20 pages.
- [ ] User: after the next catalog sync, check M-era Japanese printings get pictures over
  a few days (first fill of the list takes ~3 days at 300 requests).

- [x] Versions: server 0.16.0 (`pyproject.toml`, README, `.env.example` comment), Android
  0.10.0. New variables: `TCG_APITOKEN_PRICES_CARDNEXUS`, `TCG_CARDNEXUS_DAILY_REQUESTS`,
  `TCG_POKEMON_OFFICIAL_JP`, `TCG_POKEMON_OFFICIAL_JP_DAILY_REQUESTS`.
- [x] Checks: backend 202 tests (10 new), ruff; web build, oxlint, i18n (428 texts);
  Android `testDebugUnitTest compileDebugKotlin lintDebug`; browser (this branch on :8100
  against the test database): type-to-search on a card page, typeahead, Shift+Enter →
  stock dialog → added, Finance page (light, dark, 390 px, no overflow), Japanese "UR"
  pictogram on a M1L printing in dark mode, no console errors. Key not in the tree.
- [ ] User: put the CardNexus key in `.env` (`TCG_APITOKEN_PRICES_CARDNEXUS`), install the
  0.10.0 APK, scan MEG 22 / 94 / 100, CRI 48, add one: "Added …" shows on the tray.


## Regional sub-games (server 0.17.0, Android unchanged 0.10.0)
Branch `2026-10-23-002-regional-sub-games`. User report (server 0.15.0 / app 0.9.0): one
Pokémon and one Yu-Gi-Oh! game mixing Western and Asian products confused users. Split by
publisher and market, separate in catalog and collection:
- `pokemon` Pokémon TCG (TPCi): en, fr, de, it, es, pt
- `pokemon-asia` Pokémon TCG Asia (TPC Japan): ja, ko, zh-hant, th, id
- `pokemon-china` Pokémon TCG China (TPC China): zh-hans
- `yugioh` Yu-Gi-Oh! TCG: en, fr, de, it, es, pt
- `yugioh-ocg` Yu-Gi-Oh! OCG: ja, ko, zh-hans, zh-hant, en (Asian English, "-AE" codes)

GUI (five mockups shown, user chose option 2, 2026-10-23): game tabs unchanged per family,
a market control under the Pokémon / Yu-Gi-Oh! tab (International | Asia | China, TCG |
OCG), names only (no language codes, no flags: user request).

- [x] Providers: one game id each (entry points), shared code. `PokemonProvider(region)`
  (`REGIONS`), `games/pokemon/shared.py` memoizes the international set ids (Asian sets
  reusing one keep `asia:<id>`) and English card keys; China = mainland dataset only,
  never merged into Japanese sets; `official_jp` on the Asia game. `YugiohProvider(region)`:
  `build_tcg` (European languages only, `_Placer` gone) and `build_ocg` (every Asian and
  "-AE" printing in the set of its prefix, id `<code>~<rarity>`); `games/yugioh/shared.py`
  downloads YGOPRODeck cards and YGOJSON once for both (1 h); Konami feeds the OCG game,
  one daily budget. "(TCG)"/"(OCG)" set name suffixes dropped. `catalog_version` pokemon 7,
  yugioh 3.
- [x] Prices: Asia keeps Cardmarket + TCGplayer from TCGdex (Japanese cards have Cardmarket
  prices there) and CardNexus "pokemon-japan"; China and OCG have none.
- [x] Scan: `parse_ocr.recognized` per market (Pokémon: "…C" China set codes, writing;
  Yu-Gi-Oh!: printed region), so `other_game` points to the right sibling. Thai script
  detected. Search shortcuts: pkmasia/pkmjp, pkmcn, ocg/ygocg.
- [x] Migration `b3d5e7f9a124` (`services/split.py`, no download): Asian / Chinese sets move
  to their game with their printings (ids kept: copies, prices, history, manual prices
  stay); cards follow (copied when printed in both); languages of another market on a
  printing (zh-hans on Japanese printings, ko/zh on YGO TCG printings) become a printing
  of the other game with their copies; pictures move; discrepancies, gap checks, field
  rules, `catalog_games` follow. Not reversible. Safety net `catalog.adopt_orphans`:
  after a sync, owned printings not seen move to the seen printing of the same set code,
  number (and rarity for Yu-Gi-Oh!).
- [x] API: `GameOut.group`, `group_name`, `region`, `region_label`. Symbols and rarity
  pictures per group folder (`picture_game`). Worker: `TCG_WORKER_GAMES` "pokemon" alone
  means the family. CSV import: an old `pokemon` / `yugioh` row found in a sibling game.
- [x] Settings: `TCG_POKEMON_ASIA_LANGUAGES`, `TCG_YUGIOH_OCG_LANGUAGES` (fallback: Asian
  languages of the old single lists).
- [x] Web: `GameTabs` groups + market `join` (last market remembered per family), Settings
  games grouped, Import/Export lists game column values. Android: no change (games list
  from the server, new fields ignored).
- [x] Versions: server 0.17.0, Android unchanged.
- [x] Checks: backend 209 tests, ruff; web build, oxlint, i18n; migration on a copy of the
  test database (2 min 38 s, 1 707 sets moved, 15 131 printings split, owned copies equal
  before/after, no empty printing left), then real YGOPRODeck / YGOJSON syncs of both
  Yu-Gi-Oh! games on it: every TCG printing seen again (ids predicted right), OCG unseen
  only the Konami ones (Konami off for the test); browser on :8010 against that copy
  (Catalog, Collection, Settings, 390 px, no overflow).
- [ ] User: after upgrading, let the worker sync the new games (or run their catalog jobs);
  check Collection under each market.

## Pokémon Asia official sources (server 0.18.0, Android unchanged 0.10.0)
Branch `2026-10-24-000-pokemon-asia-sources-flags-i18n` (from main after 0.17.0). User report
(server 0.17.0 / app 0.9.0): CardNexus and Cardmarket prices for Pokémon China and the
other Asian languages; long Finance lists; Korean cards filling the first "All games"
catalog page; Thai flag missing; official Asian card searches as sources; translated
names "()" for every Asian language; disambiguation flags only on language-exclusive
sets; collection pictures in the copy's language; German and Spanish interface; a better
card placeholder (user chose the "card back frame" mockup, 2026-10-24).

- [x] Prices: CardNexus has no Pokémon China, Korean, Thai or Indonesian game (checked
  with the user's key, test only: `/v1/games`, `feeds/pokemon-china` empty,
  `pokemon-japan` = 33.6k cards all `ja`). Cardmarket's price guide is per product, not
  per language: Asian-language printings share their product's price. New: Cardmarket
  price source `fetch` for providers with `cardmarket_guide` (Pokémon, Pokémon Asia:
  game 6) prices printings with a Cardmarket id TCGdex left unpriced
  (`cardmarket_suffixes`, shared with TCGdex prices). China: no source.
- [x] Sources (`games/pokemon/official_asia.py`): asia.pokemon-card.com (th, id, tw →
  zh-hant: product list, 20-card list pages, card pages with name, number, Pokédex number,
  HP, type, illustrator) and pokemoncard.co.kr (`/v2/ajax2_dev2` list, 30 a page, needs
  `X-Requested-With`; picture path holds the Japanese code and number, so listed cards
  join before their page is read; card pages give the name). One request a second,
  `TCG_POKEMON_OFFICIAL_ASIA_DAILY_REQUESTS` (500) a day per language, cache
  `<image dir>/cache/pokemon-official-<lang>.json` (product lists again after 14 days;
  each product's cards read right after its list). Read in the Asia game's catalog sync
  after TCGdex and the datasets, through `join_asian_set`: zh-hant and ko join the
  Japanese printing of the same code and number (language, name, picture, so the card
  keeps its English translation); th and id never join a set of another language with
  their code (own numbering) but share one set (`sea:<code>` when a Japanese set has the
  code). English names: Pokédex number + species names (Thai: species, known form words
  and suffixes only; Indonesian prints English species names). `catalog_version` 8.
- [x] Flags: `SetOut.exclusive_lang` = the one language of a regional set's printings
  (none for international sets or sets printed in several languages); card page printing
  rows and the set filter use it. Thai and Indonesian flags added (web).
- [x] Finance: By set / By rarity no longer cut at 15; every breakdown shows 10 rows a page
  with the shared `Pagination` (bars keep the whole list's scale).
- [x] Collection pictures: in the copy's language, else the game's `image_fallback`
  (international games English, Pokémon Asia and Yu-Gi-Oh! OCG Japanese), else the
  card's usual picture; Pokémon China: placeholder.
- [x] Placeholder: `CardPlaceholder`, card back in the game family's color, Zukan mark,
  name, set · number, "No picture" (text hidden on small thumbnails, right-aligned
  clear of the quantity badge).
- [x] Interface: German and Spanish (`locales/de.json`, `es.json`, 447 texts each), API
  `UiLanguage` en/fr/de/es.
- [ ] Later (user): "All games" catalog order (raw `Card.name` sort above 5 000 rows,
  Hangul before Latin in `en_US.utf8`).
- [ ] Found, not done: CardNexus has a `ygo-ocg` game (37k cards, Cardmarket ids) that
  could price Yu-Gi-Oh! OCG (needs set code `LOCR-JP` ↔ `LOCR`, number `LOCR-JP023` ↔
  `LOCR-023` mapping); Android flags lack Thai and Indonesian too (`ui/Badges.kt`).
- [x] Versions: server 0.18.0, Android unchanged.
- [x] Checks: backend 221 tests, ruff; web tsc, oxlint, i18n, build, gen:api; live crawl
  (40 requests per language: zh-hant M6a, th/id MA6, ko 1 200 cards listed); browser on
  :8018 against a copy of the test database (Finance pages, Korean / China copies with
  the placeholder, German interface, 390 px no overflow).
- [ ] User: after upgrading, the worker re-syncs Pokémon Asia (catalog version 8); the
  official searches take a few days to fill (about 500 requests a day per language).

## Asian card names translated (server 0.18.1, Android unchanged 0.10.0)
Branch `2026-10-25-000-pokemon-korean-names` (from main after 0.18.0). User report
(server 0.18.0 / app 0.9.0): many Pokémon Korean cards still untranslated; names should
read "Korean (interface language)". `pick_name` already shows that, but Asian cards only
had Latin names from species names: Trainers, Energies and Pokémon named with other words
("로켓단의 뮤츠 ex", "찬란한 개굴닌자", "오거폰 벽록의 가면 ex") had none, and Korean printings
joined to a Japanese printing took the Japanese card's (untranslated) names. Measured on
type-null/PTCG-database `data_ko` (20 800 cards): 72.7% translated before. User chose a
Bulbapedia-built table for Trainers and real interface-language names from TCGdex
(fingerprint matching by illustrator + effect numbers was tried: ~25% wrong, rejected).

- [x] `card_names.json` (`games/pokemon/`, ja 1 217 / ko 1 122 / zh-hant 720 names, only
  names species cannot translate), regenerated by `scripts/pokemon_card_names.py` (run
  from `backend/` with `uv run python ../scripts/pokemon_card_names.py`, ~200 requests at
  one a second; `DEBUG=<n>` lists ambiguous names). Sources, by vote (a name kept when one
  English name has ≥ 80% of its printings):
  - Bulbapedia (MediaWiki API, CC BY-NC-SA; official English names): Japanese expansion
    list → set pages (`Setlist/header|entry`, older `nmheader|nmentry`; pages of sets
    merged into an English set hold one list per set, paired sets share a row/page), joined
    to the dataset's `print_key` (`asia:<code>-<n>`). A set list is used for a language
    when ≥ 90% of its species-translatable names agree (merged English numberings out).
  - Korean / Traditional Chinese printings take the English name of the Japanese printing
    of the same code and number when their signature matches (illustrators, HP, Pokédex
    number, numbers of the rules text without "1", Trainers: text length within ×1.35 of
    the language's usual proportion). Korean sets with codes of their own (bw1b, sm7...)
    are aligned to the Japanese set whose Pokémon match; Korean Trainers ordered their own
    way pair with the one Japanese Trainer of the set with the same signature.
  - Dataset `card_key` (Pokémon fingerprint shared with `data_en`) when it names one
    English card; PokeAPI item names for Item cards left ("きずぐすり" = Potion, kana folded).
  - English spellings merged (case, "Nidoran Female" = "Nidoran♀"); Basic Energies by type
    word in `species.basic_energy` ("기본 불꽃 에너지" → "Fire Energy", the TCGdex name).
- [x] `species.card_translations`: species names for Pokémon, else the table (ja, ko,
  zh-hant, any category). Used by TCGdex `parse_card`, Korean dataset `korean_card`,
  official `to_card` (ko / zh-hant). Korean / Chinese printings joining a Japanese printing
  pass their translations to the card (`join_asian_set`).
- [x] Interface language: `shared.International.latin_names` from TCGdex `/{fr,de,it,es,pt}/cards`
  listings (same card id as `/en/cards`, cached 6 h with the rest); `translate_latin`
  adds them to every Asian / China batch card with an English name ("보스의 지령 (Ordres du
  Boss)" in French; English when the card never had an international print).
  Asian Trainers with an English name now join the English card key (`join_english`):
  printings move to that card on resync, owned copies follow their printing.
- [x] `catalog_version` 9 (Pokémon Asia and China resync).
- [x] Coverage: `data_ko` 72.7% → 94.3% translated (Pokémon 99%, Trainers 78%, Energies
  82%); TCGdex Japanese SV2a, SV4a, SV8a, M2, S12a, SM12a, SV9 (1 499 cards) 99.5%; 97% of
  the Korean table names reach a French name. Left: Supporters of old Korean sets, a few
  special Energies, ties between neighbouring cards of one illustrator.
- [x] Versions: server 0.18.1, Android unchanged (no Android report). `.env.example`:
  user agent example 0.18.1, no new variable.
- [x] Checks: backend 229 tests (8 new in `test_pokemon_names.py`), ruff; live TCGdex
  listings (4 221 English cards with international names).
- [ ] User: after upgrading, the worker re-syncs Pokémon Asia and China (catalog version 9).
- [ ] Later: rerun `scripts/pokemon_card_names.py` after new Japanese / Korean sets.

## Price trends and All games sort (server 0.18.2, Android unchanged 0.10.0)
Branch `2026-10-26-000-trends-catalog-sort` (from main after 0.18.1). User report (server
0.18.0 / app 0.9.0): collection trend arrows and the finance "1 day" change always "=";
catalog "All games" sorted by raw `Card.name` above `SORT_BY_SHOWN_NAME_MAX` (5 000), so
untranslated Korean cards (Hangul sorts before Latin in en_US.utf8) filled the first pages.

- [x] Trends: `price_trends` and `finance` compared with calendar `today` (UTC). Prices
  sync once every 24 h at a drifting hour (local test server: Pokémon ~13:55 UTC,
  Yu-Gi-Oh ~19:30 UTC); until a game's sync of the day, its latest price is yesterday's
  and "1 day ago" was that same snapshot: 24 h arrow missing, finance 1 day "=",
  movers d1 empty. Reproduced on the local 0.18.1 server (1 day: 1.84 → 1.84).
  - `collection.past_prices`: each (printing, finish) compared with its price `days`
    before its own latest price date (`user_prices(on=…)` per distinct latest date).
    Used by `price_trends`, so collection arrows and movers.
  - `finance`: changes counted from the latest price day of the holdings (capped at
    today); history fetched from that day minus 365 days, chart still the last 366 days.
- [x] All games sort: `Card.sort_name` (migration `c4e6f8a0b235`, backfilled): the card's
  name in a Latin-script language (`scripts.NON_LATIN` excluded), `LANG_ORDER` first
  (English), card-wide before per-printing names; NULL for cards known only by non-Latin
  names. `names.update_sort_names` keeps it current: `CatalogWriter` (sync, refresh,
  lookup, cross-check) for the cards of each batch, game-wide after `fill_translations`,
  and the cross-check name override. `search_cards` above 5 000 results orders by
  `sort_name NULLS LAST` (both directions), `name`, `id`; indexes `ix_card_sort_name`
  and `ix_card_sort_name_desc`. Local catalog copy (82 194 cards, 3 004 without a Latin
  name): backfill 5.5 s, first page 0.5 ms ascending, 0.9 ms descending.
- [x] Versions: server 0.18.2, Android unchanged (no Android report). `.env.example`:
  user agent example 0.18.2, no new variable.
- [x] Checks: backend 231 tests (2 new: trends before today's prices, Latin sort), ruff,
  Alembic upgrade / `alembic check` / downgrade on an empty database.
- [ ] User: check the 24 h arrows and finance 1 day after upgrading; if they still stay
  "=" late in the UTC day (after every game's price sync), report it: the cause found only
  explains the hours before each game's daily sync.

## Report 2026-10-27 (server 0.19.0, Android 0.11.0)
Branch `2026-10-27-000-sso-schedule-app-update` (from main after 0.18.2). User report on
server 0.18.2 / app 0.10.0: sync at set times (cron-like), download the latest APK from
the web UI, SSO-only login straight to the provider, OIDC email missing in user and admin
settings, no "Single sign-on" card for users, password and email changed at the IdP;
Android: auto-update, "Log in" instead of "Sign in with <provider>".
Decisions (Q&A): schedule edited on the admin Data sync page and stored in the database,
with a visual editor (no cron syntax: too technical); the app asks before downloading an
update (Android always asks before installing an app installed outside a store); local
and SSO accounts are separate, never mixed.

- [x] Sync schedule: `app_setting` table (migration `d7a9c1e3f546`), key `sync_schedule`
  = time zone + one `ScheduleRule` per job kind: every N hours since the last run
  (default, from `TCG_*_INTERVAL_HOURS`), or at set times every day / on chosen weekdays
  / on one day of the month (zoneinfo, DST-safe, several times a day allowed). Set times
  passed before the schedule was saved are not caught up. Worker loads it once per tick,
  tick 300 s → 60 s. Admin API `GET/PUT/DELETE /api/admin/sync-schedule`,
  `POST /api/admin/sync-schedule/preview` (next 3 times). New env
  `TCG_SCHEDULE_TIMEZONE` (default UTC).
- [x] Web "Automatic updates" card on Data sync (`admin/ScheduleEditor.tsx`): frequency
  select, hour presets, time pickers (+ add a time), weekday toggles, day of month,
  searchable time zone with "use mine", live "Next: …" preview, Save / Cancel / Back to
  defaults. Hard-coded schedule sentence removed.
- [x] Android APK download: `services/app_release.py` lists GitHub releases of
  `TCG_ANDROID_RELEASE_REPO` (default `FoxOps/zukan`, empty: off), newest
  `android-vX.Y.Z` non-prerelease with a `zukan-*.apk` asset (server releases share the
  repo), cached 1 h (failures 5 min); `GET /api/app/android` (signed-in users). Web:
  sidebar "Android app X.Y.Z" link, About page card (size, date, release notes).
- [x] SSO-only auto-redirect: login page goes to the single provider when local login is
  off, not after `?error=` nor after logout without an IdP logout endpoint
  (`/login?logged_out=1`, avoids signing straight back in). Button reads "Log in".
  Found while testing: an unreachable IdP gave a 500 (httpx errors not mapped) → now a
  login error ("SSO provider unreachable").
- [x] OIDC email bug: `User.email` was only set on auto-create; an email with
  `email_verified=false` (Keycloak admin-created users) was dropped; userinfo was not
  read when only the email was missing. Now every SSO login copies the IdP email to the
  account (display/contact only, never used for matching), userinfo fetched when email
  is missing, migration backfills empty emails from the latest identity. `UserOut.sso`
  → admin list shows an SSO badge.
- [x] Local and SSO accounts separate: link (`?link=true`) and unlink
  (`DELETE /api/auth/identities/{id}`) removed; SSO accounts never get a Zukan password
  (self-service and admin "Set password" refused, 409); "Single sign-on" card removed.
- [x] Password and email at the IdP: `TCG_OIDC_<NAME>_ACCOUNT_URL` (guessed for Keycloak
  `<issuer>/account` and Authentik `/if/user/#/settings`), in `/api/auth/providers` and
  `MeOut.sso_account`. Settings for SSO users: read-only email, "Password and email" card
  with "Manage my account at <provider>"; `POST /api/auth/email` and admin "Set email"
  refused for SSO users.
- [x] Android auto-update: `UpdateViewModel` checks `GET /api/app/android` once a day
  after sign-in and from Settings ("Check for updates"); dialog "Zukan X available (you
  have Y). Download it now (size)?" Download / Later / Skip this version; download only
  after the user accepts (own OkHttp client: no token sent to GitHub), progress + cancel,
  SHA-256 checked against GitHub's asset digest; then FileProvider + system installer
  (`REQUEST_INSTALL_PACKAGES`, opens "Install unknown apps" when not allowed yet). Dev
  builds (`fr.zukan.app.dev`) don't check (a release APK cannot update them).
- [x] Android login label: one SSO provider without local form → "Log in"; with the local
  form → "Log in with SSO"; several providers keep their names.
- [x] Versions: server 0.19.0, Android 0.11.0. `.env.example`: `TCG_OIDC_HOME_ACCOUNT_URL`,
  `TCG_SCHEDULE_TIMEZONE`, `TCG_ANDROID_RELEASE_REPO`, user agent 0.19.0, local/SSO
  separation and schedule notes. `docs/sso.md`, README updated.
- [x] Checks: backend tests (new `test_schedule.py`, `test_app_release.py`, SSO email /
  separation / unreachable IdP in `test_oidc.py`), ruff, Alembic upgrade / check /
  downgrade on an empty database + backfill on sample rows; web tsc, check:i18n, oxlint,
  vite build, gen:api; browser: schedule editor (weekly Mon + Sat 03:00 / 12:00 →
  correct next times in Europe/Paris, saved, reloaded), SSO-only redirect and error path;
  Android 45 unit tests (new `UpdatesTest`), lint debug + release, debug build.
- [ ] User: local accounts linked to SSO before 0.19.0 now count as SSO accounts (email
  from the IdP, settings link to it); they keep their old local password for local login.
- [ ] User: Authelia / Zitadel / others: set `TCG_OIDC_<NAME>_ACCOUNT_URL` to show the
  account button.

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
