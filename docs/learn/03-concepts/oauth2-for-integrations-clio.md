# OAuth2 for integrations (Clio)

## The problem OAuth2 solves

A law firm wants IntakeAgent to create contacts and matters in their Clio account. They should
not hand us their Clio password. OAuth2 lets the firm's user authorise our application once,
and gives us a token that works for their account only, for the scopes they allowed, and that
they can revoke without changing their password.

## The authorization code flow, step by step

Clio uses the standard **authorization code** grant (`backend/intakeagent/exporters/clio.py`,
`ClioOAuthClient`):

1. **Register the app** in Clio's developer portal. You get a `client_id` and `client_secret`
   and you register a `redirect_uri` (ours: `/oauth/clio/callback`).
2. **Send the user to Clio.** `authorize_url()` builds
   `{base}/oauth/authorize?response_type=code&client_id=...&redirect_uri=...&state=...`.
   The backend's `/oauth/clio/authorize` route redirects there. `state` is a random string we
   check on return to prevent CSRF.
3. **User logs in and consents** on Clio's page. Clio redirects the browser to our
   `redirect_uri` with `?code=...&state=...`.
4. **Exchange the code.** `exchange_code(code)` posts to `{base}/oauth/token` with
   `grant_type=authorization_code`, the code, client id, secret and redirect URI. Clio returns
   `access_token`, `refresh_token`, `expires_in`.
5. **Call the API** with `Authorization: Bearer {access_token}`.
6. **Refresh** when the access token expires: `refresh(refresh_token)` posts
   `grant_type=refresh_token` and gets a new access token.

The code is short-lived and single-use; the secret never goes to the browser; the access token
is what carries authority.

## Where tokens live

Tokens are credentials. The MVP returns them once from the callback endpoint for the operator
to place in environment variables (`CLIO_ACCESS_TOKEN`, `CLIO_REFRESH_TOKEN`). A production
system stores them encrypted per tenant and refreshes automatically on a 401. Never log them,
never commit them, and treat `refresh_token` as more sensitive than `access_token` because it
is long-lived.

## Clio API v4 shapes

Clio wraps every payload in `{"data": {...}}` and every response the same way. The exporter
builds two payloads (`build_contact_payload`, `build_matter_payload`):

- `POST /api/v4/contacts.json` with `type: "Person"`, `first_name`, `last_name`,
  `phone_numbers[]`, `email_addresses[]`, `addresses[]`.
- `POST /api/v4/matters.json` with `client: {id}`, `description`, `status: "Pending"`,
  `open_date`, optional `practice_area` and `location`.

Regions have different hosts (`app.clio.com`, `eu.app.clio.com`, `ca.`, `au.`), which is why
`CLIO_BASE_URL` is configurable. Clio also versions the API via an `X-API-VERSION` header; we
rely on the default.

## Conflict check

Before opening a matter, firms search existing contacts for every party. `conflict_check()`
calls `GET /api/v4/contacts.json?query={name}&fields=id,name,type` for each name in
`conflict_check_names` and reports hits. In mock mode it reports none. The result travels with
the export so the reviewer sees it.

## Mock mode and testing

Without credentials, `ClioExporter.live` is false and `export()` returns the same payloads with
fake ids. Tests (`tests/test_exporters.py`) use `httpx.MockTransport` to check the live path:
contact POST before matter POST, bearer header present, and the OAuth exchange and refresh
grants. This is the pattern for any third-party integration: build the request exactly, then
prove it with a transport you control.

## Common mistakes

- Forgetting `state` validation (CSRF).
- Putting the client secret in the frontend.
- Not handling the 401-then-refresh path, so integrations break after an hour.
- Using `localhost` in `redirect_uri` for production; it must match the registered value
  exactly, including scheme and trailing path.
