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
  language, notes and an optional manual price. Quantity changes can be undone.
- **Scan cards on Android.** Recognize card text with the camera, review matching
  printings, then add or remove copies. Manual search is also available.
- **Follow collection value.** View Cardmarket and CardNexus prices in EUR and TCGplayer
  prices in USD where available, with price history for cards in a collection.
- **Import and export CSV.** Move collection data in or out, with import validation
  and a dry-run option.
- **Share a server.** Each user has a separate collection. Sign in with a local account
  or an OpenID Connect provider such as Keycloak or Authentik.

The web interface is available in English, French, German and Spanish. The Android app
is available in English and French. Card languages are handled separately; coverage
depends on the game and its data sources.

### Supported games

- Magic: The Gathering
- Pokémon TCG
- Sorcery: Contested Realm
- Riftbound
- Yu-Gi-Oh!
- Disney Lorcana

Pokémon has separate international, Asia and China catalogs; Yu-Gi-Oh! has separate
TCG and OCG catalogs. Game providers are plugins, so more games can be added.
See [Supported games and sources](https://github.com/FoxOps/zukan/wiki/Supported-games-and-sources)
for the full catalog list and language coverage.

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

## Get started

- **Use an existing server:** follow the [Getting started guide](https://github.com/FoxOps/zukan/wiki/Getting-started).
- **Host your own server:** follow the [Docker installation guide](https://github.com/FoxOps/zukan/wiki/Docker-installation).
  Released server images are publicly available on `ghcr.io/foxops/zukan`.
- **Use Android:** download the APK from [GitHub releases](https://github.com/FoxOps/zukan/releases)
  and follow the [Android guide](https://github.com/FoxOps/zukan/wiki/Android-guide).
  Android 8.0 or later and a reachable Zukan server are required.

## Documentation

The **[Zukan wiki](https://github.com/FoxOps/zukan/wiki)** is the main documentation.
It contains the user guides, deployment instructions, administration procedures and
technical reference.

| Topic | Guides |
| --- | --- |
| Collections and catalog | [Find cards and printings](https://github.com/FoxOps/zukan/wiki/Catalog-and-card-pages) · [Manage your collection](https://github.com/FoxOps/zukan/wiki/Managing-your-collection) |
| Prices and data transfer | [Prices and valuation](https://github.com/FoxOps/zukan/wiki/Prices-and-valuation) · [CSV import and export](https://github.com/FoxOps/zukan/wiki/CSV-import-and-export) |
| Accounts and Android | [Account and preferences](https://github.com/FoxOps/zukan/wiki/Account-and-preferences) · [Android guide](https://github.com/FoxOps/zukan/wiki/Android-guide) |
| Installation and configuration | [Docker installation](https://github.com/FoxOps/zukan/wiki/Docker-installation) · [Configuration reference](https://github.com/FoxOps/zukan/wiki/Configuration-reference) · [Reverse proxy and HTTPS](https://github.com/FoxOps/zukan/wiki/Reverse-proxy-and-HTTPS) |
| Authentication | [Single sign-on](https://github.com/FoxOps/zukan/wiki/Single-sign-on) · [User administration](https://github.com/FoxOps/zukan/wiki/User-administration) |
| Server administration | [Synchronization](https://github.com/FoxOps/zukan/wiki/Synchronization) · [Data checks](https://github.com/FoxOps/zukan/wiki/Data-checks) · [Operations](https://github.com/FoxOps/zukan/wiki/Operations) |
| Maintenance and recovery | [Backup and restore](https://github.com/FoxOps/zukan/wiki/Backup-and-restore) · [Updates and migrations](https://github.com/FoxOps/zukan/wiki/Updates-and-migrations) · [Troubleshooting](https://github.com/FoxOps/zukan/wiki/Troubleshooting) |
| Development and integration | [Architecture](https://github.com/FoxOps/zukan/wiki/Architecture) · [Development](https://github.com/FoxOps/zukan/wiki/Development) · [API guide](https://github.com/FoxOps/zukan/wiki/API-guide) · [Plugin development](https://github.com/FoxOps/zukan/wiki/Plugin-development) |

Server configuration examples remain in [`.env.example`](.env.example). Interactive
API documentation is available on your running instance at `/api/docs`, with its
OpenAPI schema at `/api/openapi.json`.

For common questions, see the [FAQ](https://github.com/FoxOps/zukan/wiki/FAQ).

## Contributing

Developers are welcome to contribute and to offer advice. Suggestions about the
architecture, code quality, user experience, data sources or deployment are all useful.
If you see a better way to do something, open an issue and explain it.

Bug reports, feedback from collectors, translations, documentation improvements and
support for additional games are welcome too. For a larger change, open an issue first
so we can discuss the approach before you spend time implementing it.

See the [Development guide](https://github.com/FoxOps/zukan/wiki/Development) for local
setup, builds and checks, and [Plugin development](https://github.com/FoxOps/zukan/wiki/Plugin-development)
for adding games or price sources.

## License

Zukan is free software distributed under the [CeCILL 2.1](LICENSE) license. See
[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md) before contributing.
