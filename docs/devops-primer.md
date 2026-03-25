# DevOps Primer — What You Need to Know Before Deploying

> Read this alongside `deployment.md`. This doc explains the *concepts* behind each step — not the commands themselves, but what they actually mean and why they exist.

---

## The Core Problem: Your Laptop Is Not a Server

When you run `python app.py` locally, the app works because your machine has Python installed, your `.env` file has the API keys, and everything is set up just right. None of that exists on a cloud server. Deployment is the process of recreating that environment reliably on someone else's computer — and keeping it running 24/7.

---

## Concept 1: Containers and Docker

### What is a container?

A container is a self-contained package that includes your app *and everything it needs to run* — Python, your packages, your code. Think of it like a shipping container: the contents are packed the same way regardless of whether the ship is a cargo freighter or a small boat. The container just works.

This solves the classic "it works on my machine" problem. Once the container is built, it runs identically everywhere.

### What is Docker?

Docker is the tool that builds and runs containers. The `Dockerfile` in this project is the recipe — it tells Docker exactly how to assemble the container:

```
Start with a computer that has Python installed
Copy my requirements.txt
Install all dependencies
Copy my app code
When started, run: python app.py
```

### What is a container image vs a running container?

- **Image** — the packaged, frozen artifact (like a zip file of your app + environment). Built once, stored in a registry.
- **Container** — a running instance of that image (like unzipping and running the app).

Azure runs your image as a container. You build the image, push it to Azure, and Azure runs it.

---

## Concept 2: The Container Registry (ACR)

Azure Container Registry (ACR) is a private warehouse where your container images are stored. It's like GitHub, but for Docker images instead of code.

You push your image to ACR after building it. When Azure starts your app, it pulls the image from ACR.

**Why not just upload the code directly?** Because Azure doesn't know how to set up your Python environment from raw code. The image already has everything pre-installed — Azure just runs it.

**The naming in `deployment.md`:** `weather-agent:$GIT_SHA` means the image named `weather-agent`, tagged with the short git commit hash (e.g. `weather-agent:d83bd06`). Tagging by git commit lets you track exactly which version of your code is running in production.

---

## Concept 3: Resource Groups

A resource group is just a folder in Azure that holds related resources. Everything for this project — the container, the registry, the secrets vault — lives in one resource group called `rg-weather-agent`.

This matters because:
- You can see all project costs together
- You can delete everything at once by deleting the group
- Permissions can be applied at the group level

---

## Concept 4: Secrets and Key Vault

### Why not just use a `.env` file?

Your `.env` file works locally but you should never put it in version control, and you can't easily attach it to a cloud container. More importantly, if the secret appears in a CLI command, it ends up in your shell history. That's a security risk.

### What is Key Vault?

Azure Key Vault is a managed password safe. You put your secrets in (OpenAI API key, Azure client secret), and then other Azure resources can read them — without the secret ever being hardcoded in code or commands.

In `deployment.md`, this line:
```bash
az keyvault secret set --vault-name "$KV_NAME" --name "openai-api-key" --value "$OPENAI_API_KEY"
```
...reads the key from your current shell environment (where you've set it temporarily) and stores it securely in the vault. From that point on, your code retrieves it from the vault at runtime — the secret never appears in your config files or git history.

---

## Concept 5: Managed Identity — Passwords Without Passwords

### The problem

Your container app needs to:
- Pull images from the container registry
- Read secrets from Key Vault

Normally, you'd use a username and password. But storing credentials anywhere (code, config) is risky — they can be leaked or rotated.

### The solution: Managed Identity

A managed identity is an Azure-managed "robot account" with no password. Azure handles authentication internally using cryptographic tokens that rotate automatically. You grant the identity permissions (like "this robot can read secrets from this vault"), and Azure handles the rest.

In `deployment.md`:
```bash
az identity create --name "$IDENTITY_NAME" ...        # create the robot account
az role assignment create --role AcrPull ...          # give it permission to pull images
az keyvault set-policy --secret-permissions get ...   # give it permission to read secrets
```

Your container app then runs *as* that identity. No passwords, no rotation, no leaks.

---

## Concept 6: Azure Container Apps vs the Alternatives

You might have heard of other ways to run apps in the cloud. Here's how they compare:

| Option | What it is | Why not used here |
|---|---|---|
| **Azure App Service** | Like Heroku — runs code directly | Doesn't handle WebSockets well (Gradio needs them for streaming) |
| **Azure Kubernetes Service (AKS)** | Full Kubernetes cluster | Massive overkill for one app; expensive and complex to manage |
| **Azure Container Apps** | Serverless containers | Right-sized: supports WebSockets, built-in auth, auto-TLS, ~$25/mo |
| **Azure VM** | A raw virtual machine | You'd manage the OS, Python, restarts, security patches yourself |

Container Apps is the sweet spot — it handles the infrastructure so you just deploy a container.

---

## Concept 7: Replicas and Why You're Limited to One

A **replica** is a running copy of your app. Normally you'd want multiple replicas so that if one crashes, others keep serving users. This is called **horizontal scaling**.

This app can't do that because of `MemorySaver` in `agent.py`. It stores each user's conversation history **in the container's memory (RAM)**. If two replicas run:

```
User sends message 1 → lands on Replica A → stored in Replica A's memory
User sends message 2 → lands on Replica B → Replica B has no memory of message 1
```

The chat history breaks. So `--min-replicas 1 --max-replicas 1` is **required** — not a cost-saving choice.

The fix (if you ever need scaling) is to replace `MemorySaver` with a database-backed checkpointer so all replicas share the same state. That's a code change, not a deployment change.

---

## Concept 8: HTTPS and TLS

### What is HTTPS?

HTTP is the protocol browsers use to talk to servers. HTTPS is the encrypted version — it prevents anyone intercepting the traffic from reading it (passwords, chat history, etc.).

### What is TLS?

TLS (Transport Layer Security) is the encryption technology behind HTTPS. It requires a certificate — a file that proves your server is who it says it is. Certificates used to need manual renewal every year.

### What Azure does for you

Container Apps automatically provisions and renews TLS certificates. You just enable external ingress and it handles the rest. This is why the deployment doc says "auto-managed TLS certificates" — you don't touch this at all.

**Port 443** is the standard port for HTTPS (like port 80 is for HTTP). Your Gradio app runs internally on port 7860, but users always access it via 443 — Container Apps translates between them.

---

## Concept 9: Easy Auth

Easy Auth is a feature of Azure Container Apps (and App Service) that adds Microsoft login in front of your app **without any code changes**.

Think of it as a bouncer at the door. When a user visits your app:
1. Easy Auth intercepts the request before it reaches your container
2. If they're not logged in → redirect to Microsoft login
3. After they log in → forward them to your app with their identity in a header

Your Gradio app never needs to know about OAuth, tokens, or login pages — it just receives requests from already-authenticated users.

**Why this matters for you as a developer:** You could implement login yourself (see `CLAUDE.md` Approach B), but that requires modifying `app.py`, understanding OAuth flows, and managing session middleware. Easy Auth gives you the same result with zero code changes.

---

## Concept 10: FQDN

**FQDN** stands for Fully Qualified Domain Name — it just means the full web address of your app.

Azure assigns one automatically when you create a Container App, something like:
```
weather-agent.kindwave-abc123.eastus.azurecontainerapps.io
```

This is your app's permanent address. You'll need it in Phase 0 to tell Microsoft "after login, redirect users back to this URL."

---

## Concept 11: The Azure CLI (`az` commands)

The `az` command is Azure's command-line tool. Every `az ...` command in `deployment.md` is equivalent to clicking through the Azure Portal — just faster and repeatable.

Some patterns you'll see repeatedly:

```bash
# Most commands follow this pattern:
az <service> <action> --name "thing-name" --resource-group "rg-weather-agent" [options]

# --query lets you extract a specific field from the JSON response
az identity show --name "..." --query id --output tsv
#                                        ↑ XPath-like selector   ↑ plain text output (no quotes)

# $(...) captures command output into a variable
IDENTITY_ID=$(az identity show --name "..." --query id --output tsv)
# Now $IDENTITY_ID holds the value for use in later commands
```

You'll also see variables defined at the top of Phase 1 (like `RESOURCE_GROUP="rg-weather-agent"`). These are just shell variables — they make the rest of the commands shorter and consistent. **Run all the commands in the same terminal session** so the variables stay in scope.

---

## Concept 12: Rolling Deployments

When you update the app (Phase 6), Container Apps does a **rolling replacement**:

1. Starts the new version of your container
2. Waits for it to be healthy
3. Stops the old version

During the ~10-30 second switchover, users with active sessions will lose their chat history (because `MemorySaver` is in-process). This is normal and expected — just give users a heads up before deploying.

---

## Things That Can Go Wrong (and Why)

| Error | Likely cause |
|---|---|
| `AADSTS50011` at login | The redirect URI in Entra ID doesn't exactly match your app's FQDN |
| App pulls no image / crashes immediately | Managed identity doesn't have AcrPull permission, or you used the wrong image tag |
| Secrets not loading | `keyvaultref` syntax wrong, or identity doesn't have Key Vault `get` permission |
| Chat history breaks randomly | You accidentally set `--max-replicas` above 1 |
| Gradio streaming doesn't work | WebSockets blocked — shouldn't happen on Container Apps, but check ingress settings |

---

## Reading Order

If you're going through this for the first time:

1. Read this file (concepts)
2. Read `docs/architecture.md` (diagrams of how the pieces connect)
3. Read `deployment.md` (the actual steps and commands)

The commands in `deployment.md` will make much more sense once you understand what each piece is and why it exists.
