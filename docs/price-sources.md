# Price sources

A price source is a market (Cardmarket, TCGplayer...). Each one is a plugin registered
under the `zukan.prices` entry point group (`backend/app/prices/base.py`). Users pick
their preferred source in Settings; values, price ranges and sorts use it, card pages
show every source. Prices in different currencies are never added up.

## Adding a source

1. Write an object with `id`, `name`, `currency` (ISO 4217) and
   `link(game_id, market_id, lang) -> str | None` (product page URL).
2. Get prices in, one of two ways:
   - **From the game's own data** (the game API already carries them, as Scryfall does
     for Cardmarket and TCGplayer): the game provider yields `PriceQuote(...,
     source="<id>")` from `fetch_catalog` / `fetch_prices` and lists the id in its
     `price_sources`.
   - **From the market's own API**: give the source `games = {"mtg", ...}` and
     `async def fetch(http, game_id, targets)` yielding lists of `PriceQuote` tagged
     with the source id. `targets` are every printing of the game with their
     `market_ids`; the daily price job calls it after the provider's prices.
3. Store product ids on printings as `attributes["market_ids"]["<id>"]` (links, and
   matching for `fetch`).
4. Register it in `pyproject.toml`:

   ```toml
   [project.entry-points."zukan.prices"]
   mymarket = "my_package.prices:source"
   ```

5. API keys come from `TCG_APITOKEN_PRICES_<NAME>` (`app.core.config.api_token("prices",
   "<name>")`), documented in `.env.example`.

`backend/tests/test_catalog.py::test_price_source_plugin_with_its_own_api` shows a
complete source with its own API.

`app/prices/cardnexus.py` is a real one: CardNexus' daily price files
(`app/sources/cardnexus.py`), matched through the CardNexus, Cardmarket and TCGplayer ids
its catalog file gives. Besides its own quotes it yields `cardmarket` and `tcgplayer` ones
for printings no other source priced today (`MarketTarget.quoted`).
