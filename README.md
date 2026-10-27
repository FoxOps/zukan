<p align="center">
  <img src="web/src/assets/brand/logo.webp" alt="Zukan" width="320">
</p>

# Zukan

A self-hosted trading card collection manager with a web interface and an Android scanner.

Keep your collections from several TCGs in one place, track the versions you own, check
their prices, and scan cards from your phone. Use the web interface from your computer
or mobile browser and connect the Android app to the same server.

*Zukan* (図鑑) means “illustrated encyclopedia” in Japanese.

## Why Zukan?

I started Zukan because I couldn't find a collection manager that fit the way I collect.
General-purpose collection apps didn't handle the details of trading cards well enough.
The TCG tools I tried each left something missing: paid features, too much complexity,
support for only one game, no Android app, or no way to use them outside Android.

I wanted a straightforward tool for several games, available on both my computer and
my phone, that I could host myself. Zukan grew out of that need.

### Built with AI agents

I use AI agents to develop Zukan, and I stand by that choice. Agentic development
helped me turn a personal need into working software. Without it, this project would
never have happened, and that need would still be unmet.

I decide what Zukan should do and how it should evolve, but I don't pretend to have
all the answers. If you're a developer, you're very welcome to help improve the project.
I have a lot to learn and would appreciate guidance from people with more experience.
Constructive criticism is welcome, whether it's about the code, the architecture or
the product itself.

## What you can do

- **Manage several TCGs together.** Browse card catalogs, sets, printings and images
  without switching applications for each game.
- **Track the copies you actually own.** Record quantity, set, finish, condition,
  language, notes and an optional manual price. Collection changes can be undone.
- **Scan cards on Android.** Recognize card text with the camera, review matching
  printings, then add or remove copies. Manual search is also available.
- **Follow collection value.** View Cardmarket prices in EUR and TCGplayer prices in
  USD where available, with price history for cards in a collection.
- **Import and export CSV.** Move collection data in or out, with import validation
  and a dry-run option.
- **Share a server.** Each user has a separate collection. Sign in with a local account
  or an OpenID Connect provider such as Keycloak or Authentik.

The web and Android interfaces are available in English and French. Card languages
are handled separately; coverage depends on the game and its data sources.

### Supported games

- Magic: The Gathering
- Pokémon TCG
- Sorcery: Contested Realm
- Riftbound
- Yu-Gi-Oh!
- Disney Lorcana

Game providers are plugins, so more games can be added.

## Tech stack

| Component | Technologies |
| --- | --- |
| Backend and API | Python 3.13, FastAPI, Pydantic, HTTPX |
| Database | PostgreSQL 17, SQLAlchemy 2, Alembic migrations |
| Web interface | React 19, TypeScript, Vite, TanStack Query, i18next |
| Styling | Tailwind CSS 4, daisyUI 5 |
| Android app | Kotlin, Jetpack Compose, CameraX, ML Kit text recognition, Retrofit |
| Authentication | Local accounts, OpenID Connect; AppAuth for Android SSO |
| Deployment | Docker Compose, separate API and background worker services |

The API serves the built web interface. The worker refreshes catalogs, prices and cached
card images. Android performs text recognition on the device and sends the recognized
text to the server to identify cards; scanning requires a connection to your server.

## Quick start

You need Git, Docker and the Docker Compose plugin.

```sh
git clone https://github.com/FoxOps/zukan.git
cd zukan
cp .env.example .env
```

Edit `.env` before starting:

- Set `POSTGRES_PASSWORD` to a strong password. A long random hexadecimal value avoids
  special characters that would need encoding in the database URL.
- Set `TCG_SECRET_KEY` to at least 32 random characters.
- Set `TCG_DEFAULT_ADMIN_PASSWORD` to your chosen administrator password.
- For local access over plain HTTP, add `TCG_COOKIE_SECURE=false` so browser sign-in works.
  Keep the default `true` when serving over HTTPS.

For example, `openssl rand -hex 32` generates a random value suitable for either of
the first two settings. Run it separately for each.

### Start the server

Prebuilt Docker images are public on `ghcr.io/foxops/zukan`. No GitHub token or
registry sign-in is required.

```sh
docker compose pull
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000) and sign in as `admin` with the
password you configured. The initial administrator is created only when the database
has no users.

The worker starts importing catalogs automatically. The first import can take a while,
particularly for Magic and Pokémon. Follow its progress with:

```sh
docker compose logs -f worker
```

The database is stored in `./data/postgres` and cached images in `./data/images`.
Database migrations run on startup.

To update the server:

```sh
docker compose pull
docker compose up -d
```

Set `ZUKAN_TAG` in `.env` to pin a release.

### Build from source (optional)

To build the server and web interface from your checkout:

```sh
docker compose -f docker-compose-dev.yml up -d --build
```

This uses a separate Compose project, `zukan-dev`, and stores its data in `./data-dev`.
After updating your checkout, rerun the command to rebuild.

### Connect Android

Android APKs are publicly available on the
[releases page](https://github.com/FoxOps/zukan/releases); the web UI also links the latest
one (sidebar and About page). Download and install the APK, then sign in using your server
address and account. The app checks for new versions once a day and asks before
downloading one; Android then asks you to confirm the install (allow Zukan to install
apps the first time).

From your phone, use your server's LAN address or domain, such as
`http://192.168.1.10:8000`; `localhost` refers to the phone itself.
Android 8.0 or later is required.

For remote access, serve Zukan over HTTPS through a reverse proxy. Configure
`TCG_PUBLIC_URL` and `TCG_FORWARDED_ALLOW_IPS`, and serve the full TLS certificate chain.
Plain HTTP is supported for local networks.

## Configuration and documentation

All server settings are documented in [`.env.example`](.env.example), including
accounts, synchronization schedules, optional API keys and reverse proxy settings.
Catalogs refresh weekly by default; prices and owned card images refresh daily.

- [Interactive API documentation](http://localhost:8000/api/docs) — available on your
  running instance at `/api/docs`.
- [Single sign-on setup](docs/sso.md).
- [Price sources](docs/price-sources.md).
- [Riftbound data and Riot API configuration](docs/riftbound.md).
- [Design and development progress](PLAN.md).

Back up your PostgreSQL database, image directory and `.env` file. Source builds use
`./data-dev`; prebuilt deployments use `./data`.

## Contributing

Developers are welcome to contribute and to offer advice. Suggestions about the
architecture, code quality, user experience, data sources or deployment are all useful.
If you see a better way to do something, open an issue and explain it.

Bug reports, feedback from collectors, translations, documentation improvements and
support for additional games are welcome too. For a larger change, open an issue first
so we can discuss the approach before you spend time implementing it.
