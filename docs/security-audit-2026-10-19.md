# Security audit — Zukan

Date: 2026-10-19. Repository commit: `cc98170fac6844495326b5cb6864efddda4ffe10`.
Live target: **http://localhost:8000/**, reporting version **0.13.1**.

## Scope and method

Authorized review of this repository, its dependencies and configuration, plus non-destructive HTTP tests against the single local target. Supplied credentials were entered interactively and are absent from the artifacts. Public advisory services were consulted for dependency metadata; no active tests were sent to external services. No other local services were tested.

Reviewed authentication, authorization, session handling, collection ownership, CSV processing, image handling, web and Android security configuration, Docker deployment and CI. Created disposable `audit_tmp_*` accounts and one disposable collection item. All were deleted through the API. Password changes, administrator resets and disable/enable tests affected disposable accounts only. The supplied accounts' passwords and collection data were not changed.

The initial `codex_admin` account lacked administrative privileges. Testing continued after the owner assigned the role. This was a setup issue, not an authorization bypass.

Severity reflects demonstrated application impact and prerequisites. Source-only risks are explicitly separated from live findings. No production exploit, destructive payload, resource exhaustion, external image fetch or spreadsheet network formula was used.

## Results

| ID | Finding | Severity | Evidence |
| --- | --- | --- | --- |
| S01 | Existing sessions survive password changes and administrator resets | High | Live and source |
| S02 | Local password login has no application rate limiting | Medium | Live and source |
| S03 | Spreadsheet formulas are preserved in CSV exports | Low; depends on opening or sharing exports | Live and source |
| S04 | Predictable administrator credentials on a fresh deployment | High when exposed before setup | Source; fresh-deployment prerequisite |
| D01 | Vulnerable development dependency: `postcss-selector-parser` | Low practical risk here | Lockfile and npm advisory; no live exploitation path identified |
| B01 | CSV `NaN` price raises an unhandled exception | Low robustness issue | Live dry run and source |

Additional deployment hardening is listed below. No critical vulnerability or cross-account collection access was demonstrated.

## S01 — Existing sessions survive password changes and resets

**Evidence.** In [auth.py](../backend/app/api/auth.py#L240), changing a password only replaces `password_hash`. Administrator resets in [users.py](../backend/app/api/users.py#L43) do the same. Neither invalidates refresh tokens or existing access tokens. [deps.py](../backend/app/api/deps.py#L26) checks signature, expiry, account existence and `disabled`, but has no session revocation or password-version check.

On disposable account ID `6`:

| Operation | Result |
| --- | --- |
| Change own password with current password | `204` |
| Use original access token for `GET /api/auth/me` | `200` |
| Use pre-change refresh token for `POST /api/auth/refresh` | `200`, new token pair |
| Administrator resets password | `200` |
| Use existing refresh token again | `200`, new token pair |
| Disable account, then use old access token | `401 Account unavailable` |
| Re-enable account, then use existing refresh token | `200` |
| Log out using the current refresh token | `200` |
| Reuse that refresh token after logout | `401 Invalid refresh token` |
| Use original access token after logout | `200` |

**Reproduction.** Create a disposable user through `POST /api/users`; log in and retain access token `A` and refresh token `R`. Change the user's password through `POST /api/auth/password`. Submit `R` to `/api/auth/refresh`: it still succeeds. Repeat after resetting the password through `PATCH /api/users/{id}`. For logout, revoke the current refresh token and then call `/api/auth/me` with `A`.

**Impact.** Someone who obtained a session token can retain account access despite a password change intended to recover the account. A refresh token can keep producing new access tokens. The default refresh lifetime is 90 days and renews on rotation; password changes do not end that persistence. Logout correctly revokes its refresh family but leaves already-issued access tokens usable until expiry, normally up to one hour. Temporary disabling blocks use while disabled but does not permanently terminate sessions.

**Proposed fix.** Add a persistent user authentication version, include it in issued access and refresh sessions, and verify it on every authenticated request and refresh. In the same transaction as a password change/reset or account disable, increment that version and revoke all user refresh tokens. For per-session logout, associate access tokens with a server-side session/family ID and reject access tokens for revoked sessions. Keep other sessions alive only when explicitly intended. A shorter access lifetime reduces exposure but does not fix refresh-token persistence.

**Acceptance tests.** Old access and refresh tokens fail after password change, administrator reset and disable/re-enable. Logout rejects both token types for that session. A fresh login with the new password works; the previous password fails. Run against an isolated test database.

## S02 — Password login has no application rate limiting

**Evidence.** [auth.py](../backend/app/api/auth.py#L118) performs password verification for each request, with no limiter in the route or application middleware. The deployment files contain no rate-limiting reverse proxy. Twelve sequential requests with an incorrect password for a disposable user returned twelve `401` responses in **0.91 seconds**, with no `429` or backoff. A correct login immediately afterwards succeeded.

**Reproduction.** Create a disposable account. Send twelve sequential `POST /api/auth/login` requests with that username and `password: "audit-wrong-password"`; record response codes and timing. Stop after this bounded sample. The supplied reproducer implements this test.

**Impact.** The directly exposed API permits sustained password guessing and credential stuffing unless an external control intervenes. Argon2 makes password checks appropriately costly but also makes unrestricted requests consume server resources. No account compromise or denial of service was attempted or demonstrated. Twelve attempts alone cannot exclude a higher upstream threshold; the source confirms the application itself has no such control.

**Proposed fix.** Apply shared, bounded rate limits by both normalized account name and trusted client IP, with progressive delays and `429` plus `Retry-After`. Use a shared store when running multiple processes. Avoid permanent account locks that attackers can trigger. Cover local login and other expensive unauthenticated authentication endpoints. Trust forwarded client addresses only from explicitly configured proxies.

**Acceptance tests.** Exceeding the configured limit yields `429`; unrelated users are not globally locked out; cooldown permits legitimate login; spoofed forwarding headers cannot bypass limits.

## S03 — CSV export preserves spreadsheet formulas

**Evidence.** [csv_io.py](../backend/app/services/csv_io.py#L52) uses `csv.writer` but does not neutralize formula-prefixed text fields. A disposable item's notes were set to the harmless string `=1+1` through `PATCH /api/collection/items/76`. `GET /api/collection/export.csv` returned:

```csv
game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes
mtg,UNH,23,_____,en,nonfoil,NM,1,,=1+1
```

**Reproduction.** On a disposable item, set notes to `=1+1`, export the collection, and inspect the notes cell. Optionally open that file in a spreadsheet locally and check whether the cell is interpreted as a formula. Spreadsheet execution was not part of this audit; the demonstrated fact is unsanitized export.

**Impact.** Spreadsheet applications may interpret exported text as formulas. A recipient opening a shared export or a user exporting imported, untrusted notes could encounter attacker-controlled formulas. This audit demonstrated only an arithmetic marker. Direct cross-user note injection was blocked by ownership controls, so the current exploit chain requires imported/shared data or social engineering.

**Proposed fix.** Before writing spreadsheet-facing CSV, treat textual values beginning with `=`, `+`, `-` or `@` as text, including values with leading whitespace or control characters. Prefix a text marker supported by the intended spreadsheet applications and verify it in those applications. Apply the policy to notes, names, set identifiers and other external text while preserving typed numeric columns. CSV quoting alone does not neutralize formulas. If exact machine round trips are required, provide a separately documented raw format or a spreadsheet format with explicit text cell types.

**Acceptance tests.** Arithmetic and formula-prefixed text remain literal text in supported spreadsheet applications; embedded quotes/newlines remain valid CSV; ordinary numeric quantities/prices remain numeric.

## S04 — Predictable bootstrap administrator

**Evidence.** [config.py](../backend/app/core/config.py#L31) defaults to `admin` / `changeme`. [main.py](../backend/app/main.py#L36) automatically creates that administrator when the database contains no users. The repository's existing `test_default_admin_created_on_empty_database` explicitly asserts successful login using those credentials. Docker Compose publishes the API port on all host interfaces by default. Startup requires a sufficiently long JWT secret but does not require a unique bootstrap password.

**Reproduction, isolated fresh deployment only.** Configure a valid JWT secret and database password, leave the bootstrap credentials unset, and start with an empty disposable database. The initial administrator is `admin` / `changeme`. Do not reset or empty an existing database to reproduce this. No fresh deployment was launched and no login to a real default administrator was attempted during the audit.

**Impact.** Anyone reaching a newly deployed instance before its owner changes the password could obtain administrator access. This does **not** establish that the audited instance still accepts the default credentials.

**Proposed fix.** Remove the predictable default password. Require an explicitly supplied strong bootstrap secret or use an out-of-band administrative creation command. Prefer a single-use setup token and mandatory password setup before ordinary API access. Bind local-only deployments to `127.0.0.1` unless broader exposure is explicitly chosen. Update documentation and bootstrap tests accordingly.

**Acceptance tests.** An empty database never produces a known-password administrator; deliberate secure bootstrap succeeds; restarting does not create additional administrators or reset credentials.

## D01 — Vulnerable build dependency

`web/package-lock.json` pins `@tailwindcss/typography@0.5.20`, which pins `postcss-selector-parser@6.0.10`. `npm audit --package-lock-only --json --ignore-scripts` reports two moderate entries for **one underlying issue**: the parser and its dependent package. The affected parser has quadratic behavior on specially formed selectors, fixed in `7.1.6`, according to the [maintainer advisory GHSA-rj75-hqrm-r3gf](https://github.com/postcss/postcss-selector-parser/security/advisories/GHSA-rj75-hqrm-r3gf).

**Reproduction.** Run that audit command from `web/`, or inspect the saved `npm-audit.json`. No expensive selector payload was executed.

**Impact in this repository.** This package is a development/build dependency. The Docker runtime serves prebuilt static assets and does not run this parser on request input. No path from an untrusted HTTP request to selector parsing was identified. Exposure would require untrusted CSS entering the build pipeline. `npm audit --omit=dev` reported zero vulnerabilities.

**Proposed fix.** Prefer an updated compatible parent dependency that uses a patched parser. Otherwise evaluate a narrowly scoped override to parser `7.1.6` or later, regenerate the lockfile, and verify build output and Tailwind typography compatibility; this crosses the parent's pinned major version. Do not blindly apply npm's proposed downgrade of typography to `0.5.4`. Add dependency auditing to CI with documented reachability assessment.

## B01 — Non-finite CSV price causes HTTP 500

**Evidence.** The following small upload to `POST /api/collection/import?dry_run=true` returned `500 {"detail":"Internal server error"}`:

```csv
game,set_code,collector_number,quantity,manual_price
mtg,UNH,23,1,NaN
```

Changing `NaN` to `1` returned `200`, one validated row, zero imports and no errors. The disposable account's collection remained empty.

**Cause and impact.** `Decimal("NaN")` succeeds, then the comparison at [csv_io.py line 163](../backend/app/services/csv_io.py#L163) raises `decimal.InvalidOperation` outside the exception handler. This is an input-validation error; it did not expose a traceback, corrupt data or demonstrate a service-wide outage. It should not be described as a proven denial of service.

**Proposed fix.** Reject non-finite values before comparisons:

```python
if price is not None and (not price.is_finite() or not (0 <= price < 10**10)):
    report.errors.append(RowError(line, f"Invalid price {price}"))
    continue
```

Also catch `csv.Error` as a normal import validation failure and apply consistent quantity, price precision and notes-length limits between JSON and CSV input. Validate `NaN`, `sNaN`, infinities and malformed CSV without writes.

## Additional hardening and conditional risks

These are source/configuration observations, not additional demonstrated compromise paths.

| Observation and evidence | Impact and proposed correction | Verification |
| --- | --- | --- |
| `/` and `/login` return neither `Content-Security-Policy: frame-ancestors` nor `X-Frame-Options`. See saved response headers. | Add `frame-ancestors 'none'` or an explicit permitted parent policy, optionally `X-Frame-Options: DENY`. Authenticated cross-site clickjacking was not demonstrated; `SameSite` cookies constrain it. | Inspect headers and test framing with the intended browser/site relationships. |
| `Dockerfile:35` enables `--forwarded-allow-ips='*'`; Compose publishes the API directly. | Any reachable client may supply proxy metadata. Restrict trusted proxies to actual proxy addresses and restrict direct API access when behind a proxy. No authorization bypass from this setting was demonstrated. | Untrusted clients cannot affect server-perceived scheme/client address; legitimate proxy headers still work. |
| The 5 MB CSV check runs after FastAPI receives/parses `UploadFile` (`collection.py:591`). No whole-request byte limit is present in the repository deployment. | A large multipart file may consume temporary storage before the handler rejects it. Add a streaming request-body limit at the edge/ASGI layer before multipart parsing, plus upload concurrency limits. Current parser protections do not replace a whole-file limit. | Test bounded just-over-limit uploads only in an isolated environment and check early rejection and temporary-file cleanup. No large upload or exhaustion test was performed here. |
| Image fetches use `http.get()` and inspect length after reading the entire response (`images.py:133,185`); redirects are followed (`core/http.py`). | Upstream images can consume excessive memory. Stream with cumulative byte limits. Consider allowed schemes/hosts and rejection of private/link-local destinations on each redirect if upstream URLs are treated as untrusted. No arbitrary URL submission endpoint or direct user-controlled SSRF was established. | Mock upstream redirects, oversized bodies and invalid content types; avoid production resource-exhaustion tests. |
| Python dependencies have lower bounds but no lockfile; Docker base images and CI actions use mutable tags. | Builds are not fully reproducible. Add a reviewed lock/constraints file with integrity checks and pin deployment artifacts by digest where practical; regularly update them. | Repeat a build from the same dependency inputs and compare inventories. |
| Android permits cleartext traffic globally and stores tokens in private DataStore. Backups are disabled. | HTTP outside a trusted local transport exposes credentials/tokens to network interception. Make HTTPS the default policy and make any LAN HTTP exception explicit; consider Keystore-backed token encryption for the device-compromise threat model. These are source observations; no device or network interception tests were performed. | Test configured transport policy and token storage on a disposable emulator. |

The audited URL is intentionally HTTP localhost; this alone is not reported as a transport vulnerability. Secure/HttpOnly cookie flags are present. `.env.example` contains placeholders, and startup rejects JWT secrets shorter than 32 characters; the placeholder secret is therefore not reported as a working token-forgery key.

## Controls that resisted the tested cases

- Anonymous access to `/api/auth/me`, `/api/users`, `/api/admin/overview`, `/api/collection` and `/api/games`: `401`.
- Standard user's access to administrator routes: `403`.
- Reading and patching another test account's item, and undoing its transaction: `404`.
- Submitting `role: "admin"` to self-service settings did not elevate the user's role.
- An authenticated cookie write without `X-TCG-CSRF`: `403`; the same empty settings update with the header: `200`. Cookie login and refresh without the header: `403`. Cross-origin preflight: `405`, with no CORS grant.
- Malformed bearer token: `401`. Password hashing uses Argon2; access-token verification restricts the signature algorithm and audience. No password-hash or token-signature cracking was attempted.
- Account disabling blocks current access. Refresh-token logout revokes the tested refresh family, although S01's access-token limitation remains.
- SVG asset routes explicitly apply restrictive CSP and `nosniff`; no unsandboxed SVG execution was established.

A small SQL-looking search string was processed without a server error. That probe alone does not prove SQL injection absence; reviewed query paths use SQLAlchemy expressions and bound values.

## Dependency coverage and limits

`pip-audit 2.10.1` examined **51 local distribution records**: **50 public packages with no known vulnerabilities reported**, plus the application `zukan`, skipped because it is not on PyPI. Notable local versions include FastAPI `0.143.0`, Starlette `1.7.0`, python-multipart `0.0.32`, Pillow `12.3.0`, PyJWT `2.15.1` and cryptography `50.0.2`.

This inventory comes from `backend/.venv`, not from inspection of the running server process or a container image. Its editable application metadata says `0.8.0`, while source and live health say `0.13.1`. Accordingly, the dependency result must not be presented as certification of the running service's installed versions. Python's lower bounds permit older versions; obtain and audit a release-specific runtime inventory before deployment approval.

Android dependency declarations were reviewed, but no resolved Android dependency vulnerability scan or APK analysis was completed. SSO providers are disabled on this target; OIDC code was reviewed but no live identity-provider flow was exercised. No container base-image/OS vulnerability scan, full Git-history secret scan, browser exploit demonstration or load test was performed.

The repository test suite was not run against local database services: its fixtures issue `drop_all` and `TRUNCATE`, and those services are outside the authorized HTTP target. HTTP checks and import dry runs supplied the active evidence. The report does not claim complete absence of vulnerabilities.

## Artifacts and reproduction

Files are in [security-audit-2026-10-19/](security-audit-2026-10-19/):

- `http-results.json`: primary live evidence, excluding three invalid early cookie-test observations caused by the audit client's cookie-header parsing; corrected observations are in the follow-up file.
- `http-followup.json`: corrected cookie/CSRF checks, malformed-token rejection and CSV dry runs.
- `npm-audit.json` and `python-audit.json`: dependency scanner results.
- `reproduce.py` and `followup.py`: bounded HTTP reproduction tools, hardcoded to localhost:8000, with interactive password prompts and disposable account cleanup.

From the repository root, run `python3 docs/security-audit-2026-10-19/reproduce.py` and, if needed, `python3 docs/security-audit-2026-10-19/followup.py`. The first requests both supplied accounts' passwords; the second requests the administrator password. Administrator privileges are required to create/delete disposable accounts. They write result JSON under `/tmp`. Run one at a time. If interrupted before cleanup, inspect for the generated `audit_tmp_*` account and remove only that test account.

Only audit documentation and evidence files were added to the repository. Application fixes above are proposals and have **not** been applied or deployed.

## Recommended order

1. Implement session revocation on password/security changes, then validate password recovery and logout behavior.
2. Remove known bootstrap credentials and add authentication rate limiting before broader exposure.
3. Neutralize spreadsheet text and handle non-finite CSV prices.
4. Add early upload/download limits and deployment hardening, then update the build dependency and introduce reproducible dependency inventories.

## Status 2026-10-21 (server 0.14.0)

- S01 fixed: sessions end on password change, administrator reset and disable; logout ends
  that session's access token.
- S02 fixed: failed sign-ins limited per account name and per client address (429 +
  `Retry-After`), refresh and SSO requests limited per address; forwarded addresses only
  trusted from `TCG_FORWARDED_ALLOW_IPS`.
- S03 fixed: formula-like text exported behind `'`, removed again on import.
- B01 fixed: non-finite, negative, over-precise prices and oversized quantities / notes are
  row errors; malformed CSV and NUL characters are validation errors.
- D01 fixed: `postcss-selector-parser` overridden to 7.1.x; `npm audit` runs in CI.
- Hardening done: framing and other security headers, 413 for request bodies over 6 MB
  before parsing, image downloads streamed with a size cap.
- Deferred: S04 (predictable bootstrap administrator) until before 1.0; Android transport
  and token storage; Python lockfile and image digests.
