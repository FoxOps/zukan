# Field Journal UI rework: function preservation checklist

Source: `FUNCTION-PRESERVATION.csv` of the 2026-11-23 design review (direction 01, Field Journal).
Each row lists where the existing capability lives after the rework. Controls moved; data,
routes, permissions and mutations are unchanged (no backend or API change).

| Area | Capability | Where it is now | Kept |
|---|---|---|---|
| Shell | Overview (was Dashboard), Collection, Catalog, Finance; Binder and Decks when the module is available | Sidebar group "Collection" (module filter `me.modules` unchanged); phones: bottom bar (Overview, Collection, Catalog) + More drawer | ✓ |
| Shell | Import / export, Settings | Sidebar group "Workspace" | ✓ |
| Shell | Admin Users, Groups, Data sync, Data checks, Server (admins only) | Sidebar group "Administration" (`role === 'admin'`), tabs on every admin page | ✓ |
| Shell | Mobile drawer | Hamburger and More open it; Escape and backdrop close it, focus returns to the opener; links close it | ✓ |
| Shell | Language, light/dark, account, logout | Top bar (language in the drawer on phones); account menu: Settings, About, Log out (same logout code, failed logout keeps the session) | ✓ |
| Shell | Maintenance banner and screen, Android download, version, About, publisher notice | Banner above pages; screen restyled; sidebar footer (Android link, `v{version}`, About); page footer notice | ✓ |
| Shell | Type-to-search | Page search fields first; top-bar catalog search only on pages without one | ✓ |
| Authentication | Local login, SSO providers, local-login-disabled, SSO-only redirect, safe `next`, errors, busy, cookie/CSRF/refresh, session expiry | Login page split layout; `submit`, `safeNext`, provider logic untouched; `api/client.ts` untouched | ✓ |
| Overview | Totals per currency and per game, unpriced links | Value metric (other currencies listed, never added), "Cards with a price" metric with unpriced link, "Your games" panel with per-game unpriced links | ✓ |
| Overview | Most valuable cards, movers and periods | "Most valuable cards" panel (View all), Price movers panel (24h/7d/30d) | ✓ |
| Overview | Admin-only sync status | Data sync panel for admins | ✓ |
| Overview | History by game and 30/90/365 days | Value over time panel (game select, periods) | ✓ |
| Overview | Transactions with condition, finish, language, source, time, undo | Recent changes panel, Undo per change; undone ones marked | ✓ |
| Overview | New account | Single empty-state panel (Browse the catalog / Import a collection) | ✓ |
| Catalog | Game groups, remembered regions, games shown | Game tabs; region picker in the filter column (`zukan.region.*` storage unchanged); "Choose the games shown" link | ✓ |
| Catalog | Multilingual search, result count, pending/previous results | Search field with count and spinner next to it (`keepPreviousData`) | ✓ |
| Catalog | Set picker, sort within a set, colors include/exact, attributes | Filter column: Set (searchable Select), Sort by (with a set), Colors + match mode, Game attributes (expandable, open when used); Reset and active-filter summary | ✓ |
| Catalog | Image/list views (persisted), pagination, printing links | View toggle (`tcg.catalogView`), Pagination, tiles/rows link to `/cards/:id/:printing` | ✓ |
| Catalog | — | New: Add copies on tiles and rows (stock dialog with every version, same as the card page search) | + |
| Collection | Filters: game, query, set, color, exact/include, finish, condition, language, no price | Game tabs + filter column (sheet on phones; values in the URL) | ✓ |
| Collection | Sorts name/newest/updated/quantity/value | Sort select above results | ✓ |
| Collection | List/images (persisted), pagination, per-currency page totals | View toggle (`tcg.collectionView`), Pagination, "this page" totals per currency | ✓ |
| Collection | +/− and item edit (quantity, manual price, notes, delete) | Stepper on tiles and rows; Edit opens the item dialog | ✓ |
| Collection | Add from catalog | "Add cards" page action | ✓ |
| Card | Printing deep links, default redirect, not found | Same routes and redirects in `CardDetail.tsx` | ✓ |
| Card | Localized names, rules, symbols, legality, attributes | Hero (names) and "Card details" tab | ✓ |
| Card | Image, back flip, landscape, thumbnails, fallback | `CardImage` unchanged, artwork column | ✓ |
| Card | Owned copies, finish and price source choice, history | Owned copies metric, finish buttons, Prices tab (source switch, history chart) | ✓ |
| Card | Current/cheapest/most expensive/lowest offer, market links | Price block in the hero (this printing), Prices tab (others), links in the printings table | ✓ |
| Card | Printing list, filter, sorts | Printings tab (default; sort and set search, `?sort=` kept); tab kept in the URL (`?tab=`) | ✓ |
| Card | Stock: version, valid finish, all conditions, language fallback/other language, quantity, add/remove | Stock dialog, logic unchanged; Adjust per printing; no cross-printing change | ✓ |
| Binder | Module gate, follow by game/set/language/finish, progress | Binder page (Follow a set dialog), progress on set cards | ✓ |
| Binder | Set detail in collector order, owned/missing, language/finish, copy picker and removal confirm, links, stop-following confirm | Binder detail: breadcrumb, header panel, All/Missing/Owned tabs, table, dialogs unchanged | ✓ |
| Decks | Every deck action (create, format, metadata, sections, search/add, quantities, printing, split, move, allocate/release, validation incl. unverified, views, import, export, shopping list, rename/delete confirm) | Decks pages restyled; components and their logic unchanged | ✓ |
| Finance | Scope, value, quantity, printings, average, median, coverage, unpriced, period changes, history, other-currency notice, breakdowns, top items, movers, states | Finance page: game tabs, metric rows, change metrics, history panel, breakdown panels, top items, movers | ✓ |
| Transfers | CSV per game, ZIP parts, import CSV/ZIP, add vs replace, dry run, all-or-nothing, row/file errors, reports, format reference and example | Import panel (file, mode, Check file, Import, report, "CSV format and examples") and Export panel | ✓ |
| Preferences | Email, password, SSO restrictions, language/browser, price sources (≥1, main), games shown and regions, modules, theme | Settings panels: Display and language (new Appearance choice, same saved preference as the top bar), Price sources, Games shown, Optional modules, account | ✓ |
| Users / Groups / Data sync / Data checks / Server | All controls | Admin pages restyled with header and tabs; forms, dialogs, typed reset confirmation and maintenance confirmation unchanged | ✓ |
| About and states | Attribution, notices, Android app, version, 404, errors, toasts, loading/empty/failure/retry, permissions, reduced motion, keyboard | About panels, NotFound and error screens restyled; Toasts unchanged; motion-reduce on transitions; focus management in drawer and filter sheet | ✓ |
