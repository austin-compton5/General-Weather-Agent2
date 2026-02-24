# CLAUDE.md — Weather Agent (langraph-min)

## Project Summary

Gradio-based weather forecast chatbot using LangGraph + OpenAI. Three source files: `agent.py` (LangGraph state machine), `tools.py` (Open-Meteo API), `app.py` (Gradio UI).

---

## Microsoft SSO Implementation (Entra ID / Azure AD)

> **Detailed research**: See `docs/microsoft-sso-research.md` for full evaluation of all 7 approaches considered (oauth2-proxy, authlib, MSAL, gr.LoginButton, gradiologin, fastapi-azure-auth, Azure Easy Auth), including what doesn't work and why.

Two approaches below, ordered from least to most code changes. Both require the same Azure app registration (Step 1).

### Approaches at a Glance

| | **A:** oauth2-proxy + Entra ID | **B:** FastAPI + authlib + Entra ID |
|---|---|---|
| Python code changes | **None** | `app.py` only |
| New Python dependencies | None | `authlib` |
| User identity in Gradio | No (HTTP headers only) | Yes (`request.username`) |
| Works locally | Yes | Yes |
| Extra infrastructure | Go binary as reverse proxy | None |

**Pick oauth2-proxy** if you just need to gate access behind corporate login.
**Pick FastAPI + authlib** if you need the user's identity inside the app (e.g. per-user logging, "Welcome, X").

### What does NOT work

- `gr.LoginButton()` — Hugging Face Spaces only, not a general OIDC mechanism. Feature request was closed as "Not Planned" ([#10240](https://github.com/gradio-app/gradio/issues/10240)).
- `gradiologin` — third-party lib, reported broken with non-Google providers.
- `fastapi-azure-auth` — designed for API bearer tokens, not browser login flows.

---

### Step 1: Register App in Microsoft Entra ID (shared by both approaches)

1. Go to [Azure Portal](https://portal.azure.com) > **Microsoft Entra ID** > **App registrations** > **New registration**
2. **Name**: `Weather Agent` (or any name)
3. **Supported account types**: *Accounts in this organizational directory only* (single tenant)
4. **Redirect URI**: Platform = **Web**, URI depends on approach:
   - oauth2-proxy: `http://localhost:4180/oauth2/callback`
   - FastAPI + authlib: `http://localhost:7860/auth`
5. Click **Register**
6. From the **Overview** page, copy:
   - **Application (client) ID**
   - **Directory (tenant) ID**
7. Go to **Certificates & secrets** > **New client secret** > copy the secret **Value** immediately (it won't be shown again)
8. Go to **API permissions** > verify `openid`, `email`, `profile` are present (they are by default under Microsoft Graph delegated permissions)

---

### Approach A: oauth2-proxy + Microsoft Entra ID (zero code changes)

A standalone reverse proxy that handles the entire OAuth2 flow against Microsoft Entra ID. Your Gradio app runs unchanged behind it.

```
[Browser] → [oauth2-proxy :4180] → [Gradio :7860]
```

#### A1. Install oauth2-proxy

```bash
# macOS
brew install oauth2-proxy

# Or download from https://github.com/oauth2-proxy/oauth2-proxy/releases
```

#### A2. Create `oauth2-proxy.cfg`

```ini
provider = "entra-id"
oidc_issuer_url = "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0"
client_id = "YOUR_CLIENT_ID"
client_secret = "YOUR_CLIENT_SECRET"
scope = "openid email profile"

# Where your Gradio app runs
upstream = "http://localhost:7860"

# Where oauth2-proxy listens (users visit this port)
http_address = "0.0.0.0:4180"

# Cookie settings
cookie_secret = "GENERATE_WITH_COMMAND_BELOW"
cookie_secure = false  # set true in production with HTTPS

# Who can log in — restrict to your org's email domain
email_domains = ["yourcompany.com"]
```

Generate `cookie_secret`:
```bash
python -c 'import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
```

#### A3. Run

```bash
# Terminal 1: Gradio app (unchanged)
python app.py

# Terminal 2: auth proxy
oauth2-proxy --config=oauth2-proxy.cfg
```

Visit `http://localhost:4180`. Unauthenticated users are redirected to Microsoft login, then forwarded to Gradio.

#### A4. Gotchas

- **WebSockets**: oauth2-proxy passes through WebSocket connections (needed for Gradio streaming). Default config handles this.
- **User identity**: oauth2-proxy forwards `X-Forwarded-Email`, `X-Forwarded-User`, `X-Forwarded-Preferred-Username` headers, but Gradio doesn't read them. The app won't know who logged in.
- **HTTPS in production**: Microsoft requires HTTPS redirect URIs in production. Use TLS termination via nginx/Caddy in front, or `--tls-cert-file`/`--tls-key-file` on oauth2-proxy.
- **200+ groups**: If users belong to 200+ Azure AD groups, add `User.Read` scope for oauth2-proxy to query Microsoft Graph for the full group list.

---

### Approach B: FastAPI + authlib + Microsoft Entra ID (one file changed)

Wraps Gradio in FastAPI, uses `authlib` for the OIDC flow against Microsoft Entra ID, and uses Gradio's `auth_dependency` parameter to enforce login. Confirmed working with Entra ID ([GitHub #8410](https://github.com/gradio-app/gradio/issues/8410)).

#### B1. Set Environment Variables

Add to `.env` (do NOT commit):

```
AZURE_CLIENT_ID=<your-client-id>
AZURE_CLIENT_SECRET=<your-client-secret>
AZURE_TENANT_ID=<your-tenant-id>
```

#### B2. Install Dependency

Add to `requirements.txt`:

```
authlib>=1.3.0
```

```bash
pip install authlib
```

#### B3. Modify `app.py`

Key changes to `app.py`:

1. Create a `FastAPI` instance and add `SessionMiddleware`
2. Register Azure as an OAuth provider with `authlib`
3. Add `/login`, `/auth`, `/logout` routes
4. Create a `get_user()` function for Gradio's `auth_dependency`
5. Mount a login page at `/login-page` and the main app at `/gradio`
6. Replace `demo.launch()` with `uvicorn.run()`
7. Move `css=CUSTOM_CSS` from `demo.launch()` into `gr.Blocks(css=CUSTOM_CSS)` inside `create_gradio_app()`

```python
"""
Gradio UI for the Weather Agent, wrapped in FastAPI with Microsoft SSO.
"""

import os
import hashlib
from datetime import datetime

import gradio as gr
import uvicorn
from authlib.integrations.starlette_client import OAuth, OAuthError
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from langchain_core.messages import AIMessage, HumanMessage
from starlette.middleware.sessions import SessionMiddleware

from agent import create_agent

load_dotenv()

# ── Azure OAuth config ─────────────────────────────────
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
SECRET_KEY = os.getenv(
    "APP_SECRET_KEY",
    hashlib.sha256((AZURE_CLIENT_SECRET or "fallback").encode()).hexdigest(),
)

# ── FastAPI app ────────────────────────────────────────
fastapi_app = FastAPI()
fastapi_app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

oauth = OAuth()
oauth.register(
    name="azure",
    client_id=AZURE_CLIENT_ID,
    client_secret=AZURE_CLIENT_SECRET,
    server_metadata_url=(
        f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
        "/v2.0/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email profile"},
)


# ── Auth routes ────────────────────────────────────────
@fastapi_app.get("/")
def root(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/gradio/")
    return RedirectResponse(url="/login-page/")


@fastapi_app.route("/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth")
    return await oauth.azure.authorize_redirect(request, redirect_uri)


@fastapi_app.route("/auth")
async def auth(request: Request):
    try:
        token = await oauth.azure.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse(url="/")
    request.session["user"] = token.get("userinfo", {})
    return RedirectResponse(url="/gradio/")


@fastapi_app.route("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/")


# ── Auth dependency for Gradio ─────────────────────────
def get_user(request: Request):
    """Return username if authenticated, None otherwise."""
    user = request.session.get("user")
    if user:
        return user.get("name") or user.get("preferred_username")
    return None


# ── Agent ──────────────────────────────────────────────
agent = create_agent()


def chat_stream(message: str, history: list, session_id: str):
    """Process a chat message and stream the response."""
    config = {"configurable": {"thread_id": session_id}}
    accumulated_content = ""
    for event in agent.stream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        stream_mode="messages",
    ):
        msg, metadata = event
        if isinstance(msg, AIMessage) and msg.content:
            if isinstance(msg.content, str):
                accumulated_content += msg.content
                yield accumulated_content
    if not accumulated_content:
        yield "I'm sorry, I couldn't process that request."


# ── Gradio UI ──────────────────────────────────────────
CUSTOM_CSS = """..."""  # keep existing CUSTOM_CSS string unchanged


def create_gradio_app():
    # IMPORTANT: pass css= here now, NOT in demo.launch()
    with gr.Blocks(title="Weather Agent", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:
        # ... keep the entire existing create_gradio_app() body unchanged ...
        pass
    return demo


# ── Login page (shown to unauthenticated users) ───────
with gr.Blocks() as login_demo:
    gr.Markdown("## Please sign in")
    gr.Button("Sign in with Microsoft", link="/login")

fastapi_app = gr.mount_gradio_app(fastapi_app, login_demo, path="/login-page")

# ── Main app (protected by auth_dependency) ────────────
demo = create_gradio_app()
demo.queue()
fastapi_app = gr.mount_gradio_app(
    fastapi_app, demo, path="/gradio", auth_dependency=get_user
)

if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY not set.")
    if not os.getenv("AZURE_CLIENT_ID"):
        print("Warning: AZURE_CLIENT_ID not set. SSO will not work.")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=7860)
```

#### B4. Run and Test

```bash
python app.py
```

1. Open `http://localhost:7860` — redirects to login page
2. Click "Sign in with Microsoft" — redirects to Microsoft login
3. Sign in with an org account — redirects back to `/gradio/`
4. Visit `http://localhost:7860/logout` to sign out

#### B5. Accessing User Identity in Gradio

Inside any Gradio event handler, add a `gr.Request` parameter to get the logged-in username:

```python
def respond(message, chat_history, session, request: gr.Request):
    username = request.username  # value returned by get_user()
    ...
```

#### B6. Gotchas

- **`css=` and `theme=` move**: These were passed to `demo.launch()` before. Now pass them to `gr.Blocks()` inside `create_gradio_app()`.
- **No separate `auth.py` needed**: `authlib` handles OIDC discovery, token exchange, and session management directly — no MSAL, no server-side flow cache.
- **Session security**: For production, set `APP_SECRET_KEY` explicitly and use HTTPS.
- **Behind a reverse proxy**: If deployed behind nginx at a sub-path, add `root_path` to `gr.mount_gradio_app()`.

---

### Production Notes (both approaches)

- **HTTPS**: Microsoft requires HTTPS redirect URIs in production. Update the redirect URI in Entra ID and use a reverse proxy (nginx, Caddy) or platform TLS.
- **Session storage**: Default `SessionMiddleware` uses signed cookies. For production with many users, consider Redis or database-backed sessions.
- **Token refresh**: Neither minimal implementation handles token refresh. For long-lived sessions, add refresh logic.
- **Allowed tenants**: The single-tenant app registration restricts access to your org. For multi-tenant, change the registration and validate the `tid` claim.
- **Azure App Service**: If deploying to Azure App Service, a third option exists — enable "Easy Auth" in the portal for zero-code SSO. Only works on that platform.
