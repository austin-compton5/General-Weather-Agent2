# Azure Deployment Plan — Weather Agent

## Context

Deploy the Gradio/LangGraph weather chatbot as a lightweight, robust internal Azure service for ~20 concurrent users. Goal: HTTPS, Microsoft SSO, secrets management, and easy redeployment — with zero code changes to the app.

**Key constraint:** `MemorySaver()` in `agent.py` stores conversation state in-process. This hard-caps the deployment at exactly 1 replica. Scaling to 2+ replicas would break chat history across requests.

---

## Chosen Approach: Azure Container Apps + Easy Auth

**Why Container Apps over App Service or AKS:**
- Serverless containers, ~$25/month for always-on 1 replica
- Native WebSocket support (required for Gradio streaming)
- Built-in Easy Auth = Microsoft Entra ID SSO with **zero code changes**
- Auto-managed TLS certificates and HTTPS ingress

---

## Architecture

```
Browser (HTTPS:443)
  → Azure Container Apps
      └── Easy Auth (Entra ID SSO — blocks unauthenticated requests)
          └── Container: Gradio app (port 7860)
                ├── Azure OpenAI API
                └── Open-Meteo + Nominatim (no auth)
```

---

## Phase 0: Azure App Registration (Entra ID)

Do this first in the [Azure Portal](https://portal.azure.com) — you need the client/tenant IDs before creating the Container App.

1. Entra ID → App registrations → New registration
   - Name: `weather-agent`
   - Supported accounts: **This org only** (single-tenant)
   - Redirect URI: Platform = Web, URI = `https://<FQDN>/.auth/login/aad/callback`
     *(Add the real FQDN after Phase 4 creates the Container App)*
2. Copy: **Application (client) ID** and **Directory (tenant) ID**
3. Certificates & secrets → New client secret → copy the Value immediately — you'll store it in Key Vault in Phase 1 -- 
4. Token configuration → Add optional claim → ID token → `email`, `preferred_username`

---

## Phase 1: Azure Resources

```bash
RESOURCE_GROUP="rg-weather-agent"
LOCATION="eastus"
ACR_NAME="acrweatheragent42"      
ACA_ENV="env-weather-agent"
ACA_APP="weather-agent"
KV_NAME="kv-weather-agent-contoso"      
IDENTITY_NAME="id-weather-agent"

# Resource group
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

# Container Registry (Basic SKU, ~$5/mo) — admin account disabled
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Basic

# Key Vault — stores OpenAI key and Azure client secret
az keyvault create \
  --name "$KV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

# Store secrets now (export these in your shell before running — do not hardcode)
az keyvault secret set --vault-name "$KV_NAME" --name "openai-api-key"      --value "$OPENAI_API_KEY"
az keyvault secret set --vault-name "$KV_NAME" --name "azure-client-secret" --value "$AZURE_CLIENT_SECRET"

# User-assigned managed identity for the Container App
az identity create \
  --name "$IDENTITY_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

IDENTITY_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RESOURCE_GROUP" --query id --output tsv)
IDENTITY_PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RESOURCE_GROUP" --query principalId --output tsv)
ACR_ID=$(az acr show --name "$ACR_NAME" --query id --output tsv)

# Grant managed identity permission to pull images from ACR
az role assignment create \
  --assignee "$IDENTITY_PRINCIPAL_ID" \
  --role AcrPull \
  --scope "$ACR_ID"

# Grant managed identity permission to read secrets from Key Vault
KV_ID=$(az keyvault show --name "$KV_NAME" --resource-group "$RESOURCE_GROUP" --query id --output tsv)
az role assignment create \
  --assignee "$IDENTITY_PRINCIPAL_ID" \
  --role "Key Vault Secrets User" \
  --scope "$KV_ID"

# Container Apps environment
az containerapp env create \
  --name "$ACA_ENV" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"
```

---

## Phase 2: Dockerfile Hardening (Already Done)

Both required hardening changes are already in `Dockerfile`:

1. **Python version pinned** — `FROM python:3.13.10-slim` ✓
2. **Non-root user** — `adduser appuser` + `USER appuser` before `EXPOSE` ✓

No changes needed here.

---

## Phase 3: Build and Push Image

```bash
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer --output tsv)
GIT_SHA=$(git rev-parse --short HEAD)

# Builds in Azure (no local Docker required), pushes directly to ACR
# Uses your Azure CLI credentials (RBAC) — no admin account needed
az acr build \
  --registry "$ACR_NAME" \
  --image "weather-agent:$GIT_SHA" \
  --image "weather-agent:latest" \
  .
```

`az acr build` runs the build on Azure using the context from `.dockerignore` (already correct) — no local Docker Desktop needed.

---

## Phase 4: Create the Container App

```bash
OPENAI_SECRET_URI="https://$KV_NAME.vault.azure.net/secrets/openai-api-key"

az containerapp create \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ACA_ENV" \
  --image "$ACR_LOGIN_SERVER/weather-agent:$GIT_SHA" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-identity "$IDENTITY_ID" \
  --mi-user-assigned "$IDENTITY_ID" \
  --target-port 7860 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 1 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --termination-grace-period 60 \
  --secrets "openai-api-key=keyvaultref:$OPENAI_SECRET_URI;identityref:$IDENTITY_ID" \
  --env-vars "OPENAI_API_KEY=secretref:openai-api-key" \
  --query properties.configuration.ingress.fqdn \
  --output tsv
```

The last two flags print the FQDN — go back to Phase 0 and add the real redirect URI to the Entra ID app registration.

**Why these settings:**
- `--registry-identity` — managed identity pulls images from ACR; no password needed or stored
- `--mi-user-assigned` — attaches the managed identity to the container app so it can resolve the Key Vault secret at runtime
- `keyvaultref:` with `;identityref:` — the secret value is fetched from Key Vault at runtime and never stored in Container Apps config or appears in CLI history
- `--termination-grace-period 60` — gives in-flight WebSocket streams up to 60 seconds to finish before the replica is killed on redeploy
- `--min-replicas 1 --max-replicas 1` — **required** due to `MemorySaver` single-instance constraint
- `0.5 vCPU / 1.0 GiB` — Gradio + LangGraph is I/O-bound; sufficient for 20 users

---

## Phase 5: Enable Easy Auth (Microsoft Entra ID SSO)

Zero code changes. Runs as a sidecar that intercepts all traffic before it reaches the container.

```bash
# Read client secret from Key Vault — never hardcode in script or pass directly on CLI
AZURE_CLIENT_SECRET_VALUE=$(az keyvault secret show \
  --vault-name "$KV_NAME" \
  --name "azure-client-secret" \
  --query value --output tsv)

az containerapp auth update \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --enabled true \
  --unauthenticated-client-action RedirectToLoginPage

az containerapp auth microsoft update \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --client-id "<AZURE_CLIENT_ID>" \
  --client-secret "$AZURE_CLIENT_SECRET_VALUE" \
  --tenant-id "<AZURE_TENANT_ID>"
```

Easy Auth forwards `X-MS-CLIENT-PRINCIPAL-NAME` (and other identity headers) to the container, but Gradio doesn't need to read them for basic access gating — it simply blocks unauthenticated requests at the ingress layer.

### Setting loginParameters (account picker)

The Azure CLI cannot set `loginParameters` due to a bug with `=` in values ([#29330](https://github.com/Azure/azure-cli/issues/29330)). Use the REST API instead:

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

az rest --method PATCH \
  --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/containerApps/$ACA_APP/authConfigs/current?api-version=2023-05-01" \
  --body '{"properties":{"identityProviders":{"azureActiveDirectory":{"login":{"loginParameters":["prompt=select_account"]}}}}}'
```

This forces the Microsoft account picker on login (instead of silent auto-sign-in) when the user has an active Microsoft session. Verify with:

```bash
az containerapp auth show -g "$RESOURCE_GROUP" -n "$ACA_APP" --query "identityProviders.azureActiveDirectory.login.loginParameters"
```

Should return `["prompt=select_account"]` with no extra quotes.

---

## Phase 6: Ongoing Deployments

```bash
GIT_SHA=$(git rev-parse --short HEAD)

az acr build \
  --registry "$ACR_NAME" \
  --image "weather-agent:$GIT_SHA" \
  --image "weather-agent:latest" \
  .

az containerapp update \
  --name "$ACA_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$ACR_LOGIN_SERVER/weather-agent:$GIT_SHA"
```

Container Apps performs a rolling replacement (~10-30s downtime). Announce planned deploys to users since active chat sessions are lost on restart.

---

## Cost Estimate

| Component | Est. Monthly Cost |
|---|---|
| Container Apps (0.5 vCPU, 1 GiB, always-on, 1 replica) | ~$18-20 |
| Azure Container Registry (Basic) | ~$5 |
| Log Analytics ingestion | ~$2 |
| Key Vault (first 10k operations free) | ~$0 |
| **Total** | **~$25** |

---

## Gotchas

1. **Single replica is mandatory** — `MemorySaver` in `agent.py` means 2+ replicas breaks chat history. Never set `--max-replicas` above 1 without replacing `MemorySaver` with a persistent checkpointer.
2. **Easy Auth redirect URI must be exactly** `https://<FQDN>/.auth/login/aad/callback` — a mismatch causes `AADSTS50011` at login.
3. **WebSocket + Easy Auth** — works correctly on Container Apps; the session cookie established during HTTP auth is passed on the WebSocket upgrade handshake.
4. **Nominatim rate limit** — 1 req/sec policy; rarely an issue at 20 users but monitor for 429s. Add `functools.lru_cache` to `geocode_address` in `tools.py` if needed.
5. **MemorySaver resets on redeploy** — all active conversations are lost. Announce planned deploys.

---

## Verification Checklist

- [ ] `https://<FQDN>/` redirects to Microsoft login when unauthenticated
- [ ] Sign in with org account → Gradio UI loads with map and CSS
- [ ] Ask "Weather in Paris" → map pins Paris, weather streams in chat
- [ ] Drag pin → location status updates (reverse geocode works)
- [ ] Reload page after chat → history gone (expected, MemorySaver)
- [ ] `https://<FQDN>/.auth/logout` → signs out
- [ ] Sign in with a personal Microsoft account → blocked at Entra ID
- [ ] Check logs: `az containerapp logs show --name "$ACA_APP" --resource-group "$RESOURCE_GROUP" --follow`

---

## Azure Resources Summary

```
Resource Group: rg-weather-agent
  ├── Azure Container Registry (Basic): acrweatheragent42 (admin disabled)
  │     └── Images: weather-agent:latest + weather-agent:<git-sha>
  ├── Key Vault: kv-weather-agent-contoso
  │     ├── Secret: openai-api-key
  │     └── Secret: azure-client-secret
  ├── Managed Identity: id-weather-agent
  │     ├── Role: AcrPull on acrweatheragent42
  │     └── Role: Key Vault Secrets User on kv-weather-agent-contoso
  ├── Container Apps Environment: env-weather-agent
  │     └── Container App: weather-agent
  │           ├── Ingress: external HTTPS (TLS managed automatically)
  │           ├── Port: 7860
  │           ├── Replicas: min=1, max=1
  │           ├── CPU: 0.5 vCPU, Memory: 1.0 GiB
  │           ├── Identity: id-weather-agent
  │           ├── Secret: openai-api-key → keyvaultref (kv-weather-agent)
  │           └── Easy Auth: Microsoft Entra ID (single-tenant)
  └── Entra ID App Registration: weather-agent
        └── Redirect URI: https://<FQDN>/.auth/login/aad/callback
```
