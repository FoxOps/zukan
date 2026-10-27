# Single sign-on (OpenID Connect)

Zukan works with any OpenID Connect provider. Providers are configured in `.env`
(documented in `.env.example`): list their names in `TCG_OIDC_PROVIDERS`, then set
`TCG_OIDC_<NAME>_*` for each, e.g. for a provider named `home`:

```sh
TCG_OIDC_PROVIDERS=["home"]
TCG_OIDC_HOME_DISPLAY_NAME=Home SSO
TCG_OIDC_HOME_ISSUER=https://sso.example.com/realms/home
TCG_OIDC_HOME_CLIENT_ID=tcg-web
TCG_OIDC_HOME_CLIENT_SECRET=...
TCG_OIDC_HOME_MOBILE_CLIENT_ID=tcg-android
TCG_OIDC_HOME_ADMIN_GROUPS=["tcg-admins"]
TCG_PUBLIC_URL=https://tcg.example.com
```

Lists are JSON. Restart the `api` service after a change (`docker compose up -d`).

Each provider needs two clients at the IdP:

| Client | Type | Used by | Redirect URI |
|---|---|---|---|
| `tcg-web` | confidential, authorization code + PKCE (S256) | web UI | `https://<site>/api/auth/oidc/<name>/callback` |
| `tcg-android` | public, authorization code + PKCE (S256) | Android app | `fr.zukan.app:/oauth2redirect` (dev builds: `fr.zukan.app.dev:/oauth2redirect`) |

`<name>` is the provider name from `TCG_OIDC_PROVIDERS`. `<site>` is `TCG_PUBLIC_URL`.

Rules worth knowing:

- Accounts are matched on issuer + subject, never on email. Local and SSO accounts are
  separate: an SSO login never joins a local account, and SSO accounts have no Zukan
  password.
- The IdP manages SSO users' password and email: the email is copied to the account on
  every SSO login (from the ID token, else userinfo), and Zukan's settings show an "Edit my
  profile" button to the provider's account page instead of offering password and email forms. That page is
  guessed for Keycloak and Authentik; set `TCG_OIDC_<NAME>_ACCOUNT_URL` for others
  (Authelia: `https://auth.example.com/settings`, Zitadel: `https://<host>/ui/console/users/me`).
- When `TCG_OIDC_<NAME>_ADMIN_GROUPS` is set, the role is synced from the IdP groups on every SSO login,
  and administrators cannot change the role of that provider's users on the Users page.
  Leave it empty to manage roles in Zukan instead.
- ID tokens must be signed with an asymmetric key (RS*/PS*/ES*/EdDSA). HS256 tokens
  are refused.
- Both clients must share the same issuer, so web and mobile logins map to the same
  account.
- Keep one administrator able to sign in locally until SSO is confirmed working, then
  optionally set `TCG_LOCAL_LOGIN_ENABLED=false`. With a single provider, the login page
  then goes straight to it (except after an SSO error, or after logging out when the
  provider has no logout endpoint). Administrators can no longer create local accounts
  then: SSO accounts are created at their first sign-in. Recovery: set it back to
  `true`, then `zukan create-admin NAME` inside the api container.

## Keycloak

1. Create clients `tcg-web` (Client authentication **on**, Standard flow, PKCE method
   S256) and `tcg-android` (Client authentication **off**, Standard flow, PKCE S256).
2. Groups claim: on each client, **Client scopes → dedicated scope → Add mapper →
   Group Membership**, token claim name `groups`, *Full group path* off, add to ID token.
3. `.env`: `TCG_OIDC_<NAME>_ISSUER=https://keycloak.example.com/realms/<realm>`
   (default scopes are fine).

A ready development realm lives in `deploy/keycloak/tcg-realm.json`:
`docker compose -f docker-compose-dev.yml --profile sso-dev up keycloak`, issuer `http://localhost:8080/realms/tcg`,
web secret `tcg-web-dev-secret` (`TCG_OIDC_<NAME>_CLIENT_SECRET`), users `admin` / `user` (password `password`).

## Authentik

1. Create an **OAuth2/OpenID Provider** for the web app: client type *Confidential*,
   redirect URI (strict) as above, **Signing key: select a certificate** (without one
   Authentik signs with HS256, which is refused), *Issuer mode: Same identifier is used
   for all providers*.
2. Create a second provider for Android: client type *Public*, redirect URI
   `fr.zukan.app:/oauth2redirect` (and `fr.zukan.app.dev:/oauth2redirect` for dev
   builds), **same signing key**, same issuer mode.
3. Create an application for each provider. Groups are included in the `profile` scope.
4. `.env`: `TCG_OIDC_<NAME>_ISSUER=https://authentik.example.com/application/o/<web-app-slug>/`
   (default scopes are fine). Copy the issuer exactly from the provider's *OpenID Configuration Issuer* field.

## Authelia

```yaml
identity_providers:
  oidc:
    clients:
      - client_id: tcg-web
        client_name: Zukan
        client_secret: '$pbkdf2-sha512$...'   # authelia crypto hash generate
        public: false
        require_pkce: true
        pkce_challenge_method: S256
        redirect_uris: ['https://tcg.example.com/api/auth/oidc/authelia/callback']
        scopes: [openid, profile, email, groups]
        token_endpoint_auth_method: client_secret_basic
        authorization_policy: two_factor
      - client_id: tcg-android
        client_name: Zukan Android
        public: true
        require_pkce: true
        pkce_challenge_method: S256
        redirect_uris: ['fr.zukan.app:/oauth2redirect', 'fr.zukan.app.dev:/oauth2redirect']
        scopes: [openid, profile, email, groups]
        token_endpoint_auth_method: none
        authorization_policy: two_factor
```

`.env`: `TCG_OIDC_<NAME>_ISSUER=https://auth.example.com`,
`TCG_OIDC_<NAME>_SCOPES=["openid","profile","email","groups"]`.
Authelia puts `groups` and `preferred_username` in the userinfo response by default;
Zukan reads userinfo automatically when they are missing from the ID token.
