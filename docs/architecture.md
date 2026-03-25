# Architecture Diagrams — Weather Agent

## Application Architecture

```mermaid
graph TD
    subgraph Browser
        UI["Gradio UI\n(chat + Leaflet map)"]
    end

    subgraph app.py
        GR["Gradio Blocks\ncreate_gradio_app()"]
        RGC["reverse_geocode_location()\nnominatim reverse lookup"]
        CS["chat_stream()\nstreaming generator"]
    end

    subgraph agent.py
        AG["LangGraph Agent\nStateGraph + MemorySaver"]
        LLM["OpenAI gpt-4o-mini\nChatOpenAI"]
        TN["ToolNode"]
    end

    subgraph tools.py
        GEO["geocode_address()\nNominatim forward lookup"]
        WX["get_weather_forecast()\nOpen-Meteo API"]
    end

    subgraph "External APIs"
        OAI["OpenAI API"]
        NOM["Nominatim\nopenstreetmap.org"]
        OME["Open-Meteo API\napi.open-meteo.com"]
        OSM["OpenStreetMap tiles\ntile.openstreetmap.org"]
    end

    UI -- "user message\n(text + optional image)" --> GR
    UI -- "pin drag / map click\n(lat,lng)" --> RGC
    RGC -- "display name" --> UI
    RGC -- "HTTP GET /reverse" --> NOM

    GR -- "HumanMessage" --> CS
    CS -- "stream events" --> AG
    AG -- "invoke" --> LLM
    LLM -- "tool_call" --> TN
    TN -- "geocode_address" --> GEO
    TN -- "get_weather_forecast" --> WX
    GEO -- "HTTP GET /search" --> NOM
    WX -- "HTTP GET /v1/forecast" --> OME
    LLM -- "API call" --> OAI
    TN -- "ToolMessage" --> AG
    AG -- "AIMessage stream" --> CS
    CS -- "partial text + coords" --> GR
    GR -- "update chatbot + geocode_box" --> UI
    UI -- "load Leaflet tiles" --> OSM
```

---

## LangGraph State Machine

```mermaid
stateDiagram-v2
    [*] --> agent : HumanMessage
    agent --> tools : tool_calls present
    agent --> [*] : no tool_calls (END)
    tools --> agent : ToolMessage result

    note right of agent
        gpt-4o-mini
        bound with 2 tools
    end note

    note right of tools
        geocode_address
        get_weather_forecast
    end note
```

---

## Deployment Architecture (Azure Container Apps + Easy Auth)

```mermaid
graph TD
    USER["User's Browser"]

    subgraph "Microsoft Entra ID"
        AAD["Azure AD\nOIDC / OAuth2\nSingle-tenant"]
    end

    subgraph "Azure (eastus)"

        subgraph "Container Apps Environment: env-weather-agent"
            subgraph "Container App: weather-agent"
                EA["Easy Auth sidecar\n(intercepts all traffic)"]
                APP["Gradio app\nport 7860 HTTP"]
            end
        end

        ACR["Azure Container Registry\nweather-agent:latest\nweather-agent:<git-sha>"]
        KV["Key Vault: kv-weather-agent\n• openai-api-key\n• azure-client-secret"]
        ID["Managed Identity\nid-weather-agent\nAcrPull + KV get"]
    end

    subgraph "External APIs"
        OAI2["OpenAI API"]
        NOM2["Nominatim"]
        OME2["Open-Meteo"]
    end

    USER -- "HTTPS :443" --> EA
    EA -- "unauthenticated → redirect" --> AAD
    AAD -- "OIDC callback (/.auth/login/aad/callback)" --> EA
    EA -- "authenticated → forward\nHTTP (internal)" --> APP
    APP -- "keyvaultref at runtime" --> KV
    KV -- "secret value" --> APP
    ID -- "AcrPull" --> ACR
    ACR -- "image pull" --> APP
    APP --> OAI2
    APP --> NOM2
    APP --> OME2
```

---

## Deployment Pipeline

```mermaid
sequenceDiagram
    participant Dev as Developer (local)
    participant ACR as Azure Container Registry
    participant ACA as Container App

    Dev->>ACR: az acr build --image weather-agent:<git-sha>
    Note over ACR: Build runs in Azure cloud<br/>(no local Docker needed)
    ACR-->>Dev: build complete
    Dev->>ACA: az containerapp update --image weather-agent:<git-sha>
    Note over ACA: Rolling replacement ~10-30s<br/>MemorySaver state is reset
    ACA-->>Dev: update complete
```
