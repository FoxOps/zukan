# Riftbound: using Riot's official API

Zukan reads the Riftbound catalog from Riot's official content API
(`riftbound-content-v1`) when it has a key for it. Without one it uses
[Riftcodex](https://riftcodex.com), an open fan API, and Riot's official card gallery, so
Riftbound works out of the box: the Riot API is optional.

The Riot API only answers keys Riot approved for a Riftbound product. You need:

1. a **Riot account**,
2. a **Riot developer account** (the same account, signed in on the developer portal),
3. a **Production API Key** for your Zukan site, requested by registering a product.

The development key the portal gives everyone (`RGAPI-...`, renewed every 24 hours) is
**not enough**: it works for other Riot games, but the Riftbound endpoint refuses it with
`403 Forbidden`.

## 1. Riot account

Create one at [riotgames.com](https://www.riotgames.com) (Sign in → Create account), or use
the account you play Riot games with.

## 2. Riot developer account

1. Go to the [Riot Developer Portal](https://developer.riotgames.com) and sign in with your
   Riot account.
2. Accept the developer terms ([Legal Jibber Jabber](https://developer.riotgames.com/policies/general))
   when asked.
3. Read the [Riftbound policy](https://developer.riotgames.com/docs/riftbound): what Riot
   approves (card libraries and deck builders, which is what Zukan is) and what it does
   not (gameplay simulation, ladders, metagame statistics, paid features...).

The dashboard now shows a development key. Keep it for tests only; it is not used by
Zukan.

## 3. Production API Key (product registration)

1. On the portal, open **Register Product** and choose a **Production API Key**.
2. Fill in the application. Riot asks for:
   - your name and contact information;
   - a description of the app: its use case, how it delivers it, and the user flow
     (for Zukan: a self-hosted collection manager, catalog browsing, collection and price
     tracking, card scanning with the Android app);
   - where it is distributed and on which platforms (web, Android);
   - a URL where Riot can reach or download it. If it is not testable yet, a working
     prototype or detailed mock-ups showing the purpose and user flow are accepted. The
     project page [foxops.github.io/zukan](https://foxops.github.io/zukan/) presents Zukan
     and links to this repository.
3. **Verify the site**: Riot gives a verification code to publish as `riot.txt` on the
   site given as product URL. The project page serves it at
   [foxops.github.io/zukan/riot.txt](https://foxops.github.io/zukan/riot.txt), from the
   `gh-pages` branch of this repository (not part of the app): to use your own code, put it
   in that file (one line) on that branch, wait for the page to update (1–2 minutes),
   open the URL to check it shows the code, then confirm on the portal. For your own
   domain instead, publish `riot.txt` at its root (`https://<your domain>/riot.txt`).
4. Wait for Riot's review. Riot may approve, refuse or later revoke a key at its own
   discretion; questions go through the
   [Developer Support Platform](https://support-developer.riotgames.com).

An application has to be complete for Riot to approve it: describe the app precisely and
make sure the URL works.

## 4. Use the key in Zukan

Put the approved key in `.env` (never in the repository, which is public):

```sh
TCG_APITOKEN_GAMES_RFB_RIOT=RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Restart (`docker compose up -d`) and run a catalog sync:

```sh
docker compose exec api zukan sync riftbound --kind catalog
```

The logs show which source was used. `Riot Riftbound API unavailable, using Riftcodex:
... 403 Forbidden` means the key is not (yet) approved for Riftbound; the sync still
completes from Riftcodex.

Limits of the Riftbound content API: 20 requests a second, 100 every 2 minutes. Zukan
needs one request per catalog sync.

## What Riot asks of an approved app

Zukan already follows these; keep them if you change it:

- card pictures and data only from Riot (the Riot API, or Riot's CDN for the official
  gallery), no unofficial assets;
- official English text, or Riot's own translation (Zukan shows Riot's Simplified Chinese
  where Riot publishes it);
- Riot's legal notice in a place easy to find (the web UI footer);
- cards Riot previewed but not yet released marked as such;
- no paid features, no gameplay automation, no ladders, no win or play rates.
