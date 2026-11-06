# Link Accounts

Researched 2026-11-06 from official docs only. Page: `/link-accounts`. Code: `accounts/`, `api/accounts.py`.

## Requirements by platform

| Platform | App / registration | Credentials | Scopes / permissions | Redirect URI rules | Token life and refresh | Account ID | Approval / tier | Read-only test call | Docs |
|---|---|---|---|---|---|---|---|---|---|
| Google Ads (API v26) | Google Cloud project with the Google Ads API enabled. **No developer token**: sunset 2026-09-09; existing tokens are ignored now and a future major version will reject them. | OAuth client ID (`…apps.googleusercontent.com`) + client secret, type Web application; or a service account | `https://www.googleapis.com/auth/adwords`; `access_type=offline`, `prompt=consent` for a refresh token | HTTPS (localhost exempt), no raw IPs, no wildcards or fragments, exact match incl. trailing slash | Access token about 1 h (`expires_in`), refreshed from the refresh token at `oauth2.googleapis.com/token`. Refresh token valid until revoked (7 days while the consent screen is in Testing) | 10 digits, no dashes; `login-customer-id` only through a manager (MCC) | Access level now belongs to the Cloud project: Test (test accounts only, 15,000 ops/day) by default. Production needs Explorer (2,880 ops/day, usually auto-reviewed), Basic or Standard (manual review). New Basic/Standard need brand verification | `GET /v26/customers:listAccessibleCustomers` | https://developers.google.com/google-ads/api/docs/api-policy/developer-token · https://developers.google.com/identity/protocols/oauth2/web-server |
| Meta Marketing API (v27.0) | Meta app of type Business + the Marketing API product; Facebook Login for Business | App ID + App Secret; user token (Connect) or a System User token | `ads_read` (read), `ads_management` (changes), `business_management` | Must be listed in Valid OAuth Redirect URIs (HTTPS, strict mode) | Short-lived user token (hours), exchanged server-side (`grant_type=fb_exchange_token`) for a long-lived ~60-day token; it can't be refreshed after expiry. System User tokens don't expire | `act_<digits>` | Standard access is enough for your own accounts; advanced access needs App Review. Marketing API tier is Limited by default; Full needs 500+ calls in 15 days at under 15% errors. Business verification for sensitive data | `GET /v27.0/act_{id}?fields=name,account_status` | https://developers.facebook.com/docs/marketing-api/get-started/authorization · https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived |
| LinkedIn Marketing API (202610) | Developer app tied to a Company Page, Advertising API product approved | Client ID + client secret | `r_ads`, `r_ads_reporting` (read), `rw_ads` (changes). 3-legged only. The member needs an ad account role | Absolute HTTPS URL, query ignored, no `#` | Access token 60 days. Programmatic refresh tokens (about 365 days) for approved partners only; otherwise re-run Connect. Auth code lives 30 min | Digits (`urn:li:sponsoredAccount:{id}`) | Development tier (up to 5 ad accounts, added in the app's Products tab), Standard tier by application | `GET /rest/adAccounts/{id}`, header `LinkedIn-Version: 202610` | https://learn.microsoft.com/en-us/linkedin/marketing/getting-started · https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow |
| TikTok Marketing API (v1.3) | TikTok for Business developer account + an approved app with scopes ticked | App ID + Secret | Ad account management / reporting scopes chosen on the app | The advertiser redirect URL set on the app | `auth_code` is good for 1 h, single use, exchanged at `/open_api/v1.3/oauth2/access_token/` for a long-term token that does not expire (it stops on revoke) | Advertiser ID, digits | App review in the developer portal | `GET /open_api/v1.3/oauth2/advertiser/get/` | https://business-api.tiktok.com/portal/docs/obtain-a-long-term-access-token/v1.3 |
| X Ads API (v12) | Approved developer account, a developer app, plus an Ads API access request approved for that app | API key + secret, and a user access token + secret | OAuth 1.0a user context for a user with access to the ads account | 3-legged web callback, or a PIN-based flow | User tokens don't expire until revoked | Short alphanumeric, e.g. `18ce54d4x5t` | Ads API access application | `GET /12/accounts` (OAuth 1.0a signed) | https://docs.x.com/x-ads-api/getting-started/step-by-step-guide · https://docs.x.com/x-ads-api/fundamentals/accessing-ads-accounts |

Status: Google, Meta, LinkedIn and TikTok have Connect (OAuth), Test connection and Unlink. For X the requirements are listed but the OAuth 1.0a connect flow isn't built yet: paste the four values, and Test connection signs the call. The developer.x.com pages returned HTTP 402 when fetched; the X rows come from docs.x.com. Check the X API version against the current reference.

## Security design

- Secrets live outside the repo in `$ATLAS_SECRETS_DIR` (default `~/.config/atlas-dashboard/`). The directory is 0700. `credentials.json`, `admin.json` and `settings.json` are 0600, written atomically (temp file, then fsync, then rename).
- Secrets are write-only. No endpoint, page, log line or error returns a secret. Status shows masked IDs (last 4 characters) and set / not set. Test errors are scrubbed of any stored value.
- Every write (save, connect, test, unlink, data mode) needs the `X-Admin-Key` header. The server keeps only a salted PBKDF2-HMAC-SHA256 hash (600,000 iterations; this Python 3.9 build has no `hashlib.scrypt`). Five wrong attempts per IP (`CF-Connecting-IP`) in 15 minutes lock that IP out with a 429.
- With no passphrase set, the page is read-only and says how to set one.
- OAuth `state` is random, single-use, expires in 10 minutes, and is bound to an HttpOnly, SameSite=Lax session cookie set when Connect starts.
- Live data mode is a read selector (`accounts.get_data_mode()`). It never enables writes; env `ATLAS_ALLOW_LIVE=1` stays the only switch for that.

## One-time setup (on the server, as `owner`)

```
cd ~/Documents/GitHub/atlas-campaign-builder/dashboard   # wherever the served checkout lives
.venv/bin/python -m accounts.set_admin_key
```

Optionally set `ATLAS_PUBLIC_URL=https://atlas.richportmedia.ai` in the service environment, so redirect URIs never depend on proxy headers. Then register each card's redirect URI (`https://atlas.richportmedia.ai/link-accounts/callback/<platform>`) in that platform's app.
