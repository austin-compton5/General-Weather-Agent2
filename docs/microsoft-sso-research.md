# Microsoft SSO Research — Weather Agent

Research conducted 2026-02-24. Covers all approaches evaluated for adding Microsoft Entra ID (Azure AD) SSO to a Gradio 4.x+ Python app.

---

## Approaches Evaluated

### 1. oauth2-proxy (RECOMMENDED — zero code changes)

**Status**: Confirmed working. Has a dedicated `entra-id` provider.

A standalone Go reverse proxy that handles the entire OAuth2/OIDC flow. The Gradio app runs unchanged behind it.

```
[Browser] → [oauth2-proxy :4180] → [Gradio :7860]
```

- Install: `brew install oauth2-proxy` or download binary from https://github.com/oauth2-proxy/oauth2-proxy/releases
- Config: single `oauth2-proxy.cfg` file with tenant/client IDs
- Provider setting: `provider = "entra-id"`
- OIDC issuer: `https://login.microsoftonline.com/{TENANT_ID}/v2.0`
- Redirect URI registered in Azure: `http://localhost:4180/oauth2/callback`

**Pros**:
- Zero Python code changes
- Battle-tested in production
- WebSocket passthrough works (needed for Gradio streaming)
- Supports email domain restrictions, group-based access

**Cons**:
- User identity not available inside Gradio (forwarded as HTTP headers `X-Forwarded-Email`, `X-Forwarded-User`, `X-Forwarded-Preferred-Username` but Gradio doesn't read them)
- Extra binary to install and run
- Requires running two processes (proxy + app)

**Gotcha — 200+ groups**: If users belong to 200+ Azure AD groups, oauth2-proxy needs `User.Read` scope to query Microsoft Graph for the full group list. Without it, users authenticate with zero groups.

**Gotcha — multi-tenant**: Requires `insecure_oidc_skip_issuer_verification = true` because the discovery document issuer doesn't match the configured URL.

**Source**: https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/ms_entra_id/

---

### 2. FastAPI + authlib + Gradio `auth_dependency` (RECOMMENDED — one file changed)

**Status**: Confirmed working with Azure Entra ID. Verified in Gradio GitHub issue #8410.

Wraps Gradio in a FastAPI app, uses `authlib` for OIDC, and uses Gradio's `auth_dependency` parameter (introduced in PR #7557) to enforce auth.

- Dependency: `authlib>=1.3.0`
- OIDC discovery URL: `https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration`
- Redirect URI registered in Azure: `http://localhost:7860/auth`
- Scopes: `openid email profile`
- Gradio app mounted at `/gradio` with `auth_dependency=get_user`
- Login page mounted at `/login-page` (separate `gr.Blocks` instance with a "Sign in with Microsoft" button linking to `/login`)
- Session managed by Starlette `SessionMiddleware`
- `demo.launch()` replaced by `uvicorn.run(fastapi_app)`

**Pros**:
- User identity available inside Gradio via `request.username` (from `gr.Request`)
- No extra binaries — pure Python
- Single process
- `authlib` handles OIDC discovery, token exchange, session natively — no server-side flow caching needed (unlike MSAL)

**Cons**:
- Requires restructuring `app.py` (wrap in FastAPI, mount Gradio)
- `css=` and `theme=` must move from `demo.launch()` to `gr.Blocks()` constructor
- Session middleware uses signed cookies (4KB limit, but `authlib` stores minimal data)

**Key code pattern**:
```python
oauth = OAuth()
oauth.register(
    name="azure",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# auth_dependency returns username or None
def get_user(request: Request):
    user = request.session.get("user")
    if user:
        return user.get("name") or user.get("preferred_username")
    return None

app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio", auth_dependency=get_user)
```

**Sources**:
- Gradio issue #8410 (Azure Entra ID working example): https://github.com/gradio-app/gradio/issues/8410
- Gradio issue #7005 / PR #7557 (auth_dependency feature): https://github.com/gradio-app/gradio/issues/7005
- Gradio sharing docs: https://www.gradio.app/guides/sharing-your-app

---

### 3. MSAL (Microsoft Authentication Library) — viable but more complex

**Status**: Works, but more boilerplate than authlib for this use case.

Microsoft's official Python library for Entra ID auth. Uses `ConfidentialClientApplication` with authorization code flow.

- Dependency: `msal>=1.28.0`
- Requires server-side caching of auth flow objects (too large for cookie-based sessions)
- Auth flow objects keyed by `state` parameter in an in-memory dict
- Token exchange via `acquire_token_by_auth_code_flow()`

**Why authlib is simpler for this use case**:
- MSAL's `initiate_auth_code_flow()` returns a large flow dict that must be stored server-side (cookie size limit). authlib handles this internally.
- MSAL doesn't integrate with Starlette/FastAPI natively — you write raw middleware. authlib has `authlib.integrations.starlette_client`.
- MSAL is better suited for complex scenarios (token caching, silent refresh, multi-account).

**When to prefer MSAL**:
- Need token refresh (`acquire_token_silent()`)
- Need to call Microsoft Graph API with user tokens
- Complex multi-tenant or B2C scenarios

---

### 4. `gr.LoginButton()` — DOES NOT WORK with Entra ID

**Status**: Only works with Hugging Face OAuth on Hugging Face Spaces.

The environment variables `OPENID_PROVIDER_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_SCOPES` are HF Spaces-specific — auto-populated by the Spaces platform when `hf_oauth: true` is set in the Space config. They are NOT a general-purpose OIDC configuration mechanism.

Feature request to support custom OIDC providers was closed as "Not Planned" by the Gradio team.

**Source**: https://github.com/gradio-app/gradio/issues/10240

---

### 5. `gradiologin` — DOES NOT WORK reliably with Entra ID

**Status**: Third-party library, reported broken with non-Google providers.

- GitHub: https://github.com/jakjus/gradiologin
- Issue report: https://github.com/gradio-app/gradio/issues/10240 — user reports "seems to be compliant only with google"
- Gradio team closed as "Not Planned" and noted it's not maintained by them
- No documented successful use with Microsoft Entra ID

---

### 6. `fastapi-azure-auth` — WRONG FIT for browser login

**Status**: Works for API bearer token validation, not for browser-based login flows.

- GitHub: https://github.com/intility/fastapi-azure-auth
- Designed for APIs where the client sends a `Bearer` token in the `Authorization` header
- Gradio is a browser app — users don't manually attach bearer tokens
- Would need to be combined with a separate login flow (authlib) anyway, defeating the purpose

---

### 7. Azure App Service "Easy Auth" — platform-specific

**Status**: Works, zero code changes, but only on Azure App Service.

- Enable in Azure Portal > App Service > Settings > Authentication > Add identity provider > Microsoft
- All requests to the app require authentication at the platform level
- User identity in `X-MS-CLIENT-PRINCIPAL-NAME` header (Gradio doesn't read it by default)
- Not usable for local development or non-Azure hosting

---

## Azure App Registration (shared setup)

Regardless of approach:

1. Azure Portal > Microsoft Entra ID > App registrations > New registration
2. Name: anything
3. Supported account types: "Accounts in this organizational directory only" (single tenant)
4. Redirect URI: depends on approach (see above)
5. Copy Application (client) ID and Directory (tenant) ID from Overview
6. Certificates & secrets > New client secret > copy Value immediately
7. API permissions: `openid`, `email`, `profile` should be present by default

---

## Decision Matrix

| Criteria | oauth2-proxy | authlib | MSAL | Easy Auth |
|---|---|---|---|---|
| Code changes | None | `app.py` only | `app.py` + `auth.py` | None |
| New dependencies | Go binary | `authlib` | `msal` | None |
| User identity in app | No | Yes | Yes | No |
| Works locally | Yes | Yes | Yes | No |
| Token refresh | No | No (add manually) | Built-in | N/A |
| MS Graph API calls | No | Manual | Built-in | No |
| Production maturity | High | High | High | High |
| Complexity | Low | Low | Medium | Lowest (platform-only) |
