"""
Gradio UI for the Weather Agent.
"""

import os
import re
from datetime import datetime

import gradio as gr
import httpx
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from agent import create_agent

load_dotenv()

agent = create_agent()


# ── Reverse geocode (pin drag / click) ────────────────

def reverse_geocode_location(coords: str):
    """Reverse geocode lat,lng → (coord_state, status_markdown)."""
    if not coords:
        return coords, ""
    parts = coords.split(",")
    if len(parts) != 2:
        return coords, ""
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except ValueError:
        return coords, ""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"format": "json", "lat": lat, "lon": lng},
                headers={"User-Agent": "WeatherAgent/1.0", "Accept-Language": "en"},
            )
            resp.raise_for_status()
            data = resp.json()
        name = data.get("display_name", "")
        label = f"**{name}**  \n`{lat:.5f}, {lng:.5f}`" if name else f"`{lat:.5f}, {lng:.5f}`"
        return coords, label
    except Exception:
        return coords, f"`{lat:.5f}, {lng:.5f}`"


# ── Agent streaming ────────────────────────────────────

def chat_stream(message: str, session_id: str):
    """Yield (accumulated_text, new_map_coords) tuples.

    new_map_coords is non-empty exactly once per geocode_address result,
    parsed from our own tool output format — no external parsing fragility.
    """
    config = {"configurable": {"thread_id": session_id}}
    accumulated = ""
    pending_coords = ""   # set when a geocode ToolMessage arrives, cleared after next yield

    for event in agent.stream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        stream_mode="messages",
    ):
        msg, _ = event

        # ── Geocode result ── our format, we control it
        if isinstance(msg, ToolMessage):
            content = str(msg.content)
            lat_m = re.search(r"Latitude:\s*([-\d.]+)", content)
            lng_m = re.search(r"Longitude:\s*([-\d.]+)", content)
            if lat_m and lng_m:
                pending_coords = f"{lat_m.group(1)},{lng_m.group(1)}"
                # Yield immediately so the map updates before the agent starts talking
                yield accumulated, pending_coords
                pending_coords = ""   # one-shot trigger

        # ── Agent text ──
        if isinstance(msg, AIMessage) and msg.content:
            if isinstance(msg.content, str):
                accumulated += msg.content
                yield accumulated, pending_coords
                pending_coords = ""

    if not accumulated:
        yield "I'm sorry, I couldn't process that request.", ""


# ── Map HTML / JS ──────────────────────────────────────

MAP_HTML = """
<div id="weather-map" style="
  height: 360px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
"></div>
"""

# Injected once via demo.load(fn=None, js=MAP_JS)
MAP_JS = """
if (!document.getElementById('leaflet-css')) {
  var _lnk = document.createElement('link');
  _lnk.id = 'leaflet-css'; _lnk.rel = 'stylesheet';
  _lnk.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  document.head.appendChild(_lnk);
}
if (!document.getElementById('leaflet-js')) {
  var _scr = document.createElement('script');
  _scr.id = 'leaflet-js';
  _scr.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  document.head.appendChild(_scr);
}

// Write value into the hidden drag-box using the native setter so
// Gradio's Svelte runtime detects the change and fires .change().
function _writeDragBox(value) {
  var ta = document.querySelector('#drag-box textarea');
  if (!ta) return;
  var setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value'
  ).set;
  setter.call(ta, value);
  ta.dispatchEvent(new Event('input',  { bubbles: true }));
  ta.dispatchEvent(new Event('change', { bubbles: true }));
}

function _initMap() {
  var mapEl = document.getElementById('weather-map');
  if (!mapEl || typeof L === 'undefined') { setTimeout(_initMap, 200); return; }
  if (mapEl._leaflet_id) return;

  var map = L.map(mapEl).setView([20, 0], 2);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }).addTo(map);

  var marker = null;

  // Called from Python-side JS (geocode result) — visual only, no drag-box write.
  window.weatherMapPlaceMarker = function(lat, lng, zoom) {
    if (marker) {
      marker.setLatLng([lat, lng]);
    } else {
      marker = L.marker([lat, lng], { draggable: true }).addTo(map);
      marker.on('dragend', function(e) {
        var p = e.target.getLatLng();
        _writeDragBox(p.lat.toFixed(6) + ',' + p.lng.toFixed(6));
      });
    }
    map.setView([lat, lng], zoom != null ? zoom : 11);
  };

  // Map click: place/move marker + update coord state
  map.on('click', function(e) {
    window.weatherMapPlaceMarker(e.latlng.lat, e.latlng.lng, null);
    _writeDragBox(e.latlng.lat.toFixed(6) + ',' + e.latlng.lng.toFixed(6));
  });

  new ResizeObserver(function() {
    setTimeout(function() { map.invalidateSize(); }, 50);
  }).observe(mapEl);
}

_initMap();
"""

# Fired client-side when geocode_box value changes (Python → map).
# Retries until Leaflet is ready.
CENTER_MAP_JS = """
(coords) => {
  if (!coords) return;
  var parts = coords.split(',');
  if (parts.length !== 2) return;
  var lat = parseFloat(parts[0]), lng = parseFloat(parts[1]);
  if (isNaN(lat) || isNaN(lng)) return;
  var attempt = function(n) {
    if (window.weatherMapPlaceMarker) {
      window.weatherMapPlaceMarker(lat, lng, 11);
    } else if (n > 0) {
      setTimeout(function() { attempt(n - 1); }, 200);
    }
  };
  attempt(15);
}
"""


# ── CSS ────────────────────────────────────────────────

CUSTOM_CSS = """
.gradio-container {
    max-width: 1200px !important;
    margin: 0 auto !important;
    padding: 0 1rem !important;
}

#header {
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    padding: 1.25rem 0 0.5rem;
}
#header .header-text { text-align: center; }
#header h1 { font-size: 1.35rem; font-weight: 700; margin: 0; }
#header p  { font-size: 0.85rem; opacity: 0.6; margin: 0.25rem 0 0; }
#header .logo {
    position: absolute; right: 0; top: 50%;
    transform: translateY(-50%);
    width: 38px; height: 38px;
}

#chatbot { border-radius: 16px !important; height: 480px !important; }
#msg-input { border-radius: 12px !important; }
#msg-input textarea { font-size: 1rem !important; }

#location-status {
    font-size: 0.8rem;
    color: #6b7280;
    min-height: 2.2rem;
    padding: 0.25rem 0 0.5rem;
}

/* hidden bridge boxes */
#drag-box, #geocode-box { display: none !important; }

#weather-map { isolation: isolate; }
.leaflet-pane       { z-index: 1 !important; }
.leaflet-top,
.leaflet-bottom     { z-index: 2 !important; }

.chip-row {
    display: flex; justify-content: center;
    gap: 0.5rem; padding: 0.25rem 0; flex-wrap: wrap;
}
.chip-row button {
    border-radius: 20px !important;
    font-size: 0.82em !important;
    white-space: nowrap !important;
}

footer { display: none !important; }

@media (max-width: 640px) {
    .gradio-container { padding: 0 0.5rem !important; }
    #header { padding: 0.75rem 0 0.25rem; }
    #header h1 { font-size: 1.15rem; }
    #chatbot { height: 55dvh !important; border-radius: 12px !important; }
    .chip-row {
        flex-wrap: nowrap; overflow-x: auto;
        justify-content: flex-start; gap: 0.4rem;
        padding: 0.25rem; -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }
    .chip-row::-webkit-scrollbar { display: none; }
    .chip-row button {
        flex-shrink: 0;
        font-size: 0.78em !important;
        padding: 0.35rem 0.75rem !important;
    }
}

@media (min-width: 641px) and (max-width: 1024px) {
    .gradio-container { max-width: 700px !important; }
    #chatbot { height: 60dvh !important; }
}

@media (min-width: 1025px) {
    #chatbot { height: 480px !important; }
}
"""


# ── Gradio app ─────────────────────────────────────────

def create_gradio_app():
    with gr.Blocks(title="Weather Agent") as demo:

        gr.HTML(
            '<div id="header">'
            '<div class="header-text">'
            "<h1>Weather Agent</h1>"
            "<p>Get weather forecasts for any location &mdash; just ask.</p>"
            "</div>"
            '<svg class="logo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
            '<rect width="100" height="100" rx="22" fill="#6366f1"/>'
            '<text x="50" y="64" text-anchor="middle" font-size="42" '
            'font-weight="700" font-family="system-ui,sans-serif" fill="white">W</text>'
            "</svg>"
            "</div>"
        )

        session_id  = gr.State(value=lambda: f"session_{datetime.now().timestamp()}")
        coord_state = gr.State("")   # canonical "lat,lng" — single source of truth

        with gr.Row(equal_height=False):

            # ── Left: map ─────────────────────────────
            with gr.Column(scale=2, min_width=280):

                location_status = gr.Markdown(
                    "*Mention a location in chat — it will appear here.*",
                    elem_id="location-status",
                )

                gr.HTML(value=MAP_HTML, js_on_load=MAP_JS)

                # Python → JS bridge: set by respond() when geocoding happens
                geocode_box = gr.Textbox(
                    elem_id="geocode-box", visible=False, container=False, label=""
                )
                # JS → Python bridge: written by Leaflet on drag or map click
                drag_box = gr.Textbox(
                    elem_id="drag-box", visible=False, container=False, label=""
                )

            # ── Right: chat ───────────────────────────
            with gr.Column(scale=3, min_width=320):

                chatbot = gr.Chatbot(
                    elem_id="chatbot",
                    show_label=False,
                    placeholder=(
                        '<div style="display:flex;flex-direction:column;align-items:center;'
                        'justify-content:center;height:100%;color:#9ca3af;padding:1.5rem;">'
                        '<p style="font-size:1.8rem;margin:0;">&#9925;</p>'
                        '<p style="font-size:clamp(0.9rem,2.5vw,1rem);margin:0.5rem 0 0.25rem;'
                        'font-weight:500;">How can I help?</p>'
                        '<p style="font-size:clamp(0.75rem,2vw,0.85rem);">'
                        "Tell me a location and I'll put it on the map, "
                        "then ask for the forecast.</p>"
                        "</div>"
                    ),
                )

                msg = gr.MultimodalTextbox(
                    elem_id="msg-input",
                    placeholder="Message Weather Agent...",
                    show_label=False,
                    file_types=["image"],
                )

                suggestions = [
                    "Weather in Paris, France",
                    "New York 7-day forecast",
                    "Tokyo weather this week",
                    "London forecast in celsius",
                ]
                with gr.Row(elem_classes=["chip-row"]):
                    for s in suggestions:
                        btn = gr.Button(s, variant="secondary", size="sm")
                        btn.click(fn=lambda text=s: {"text": text, "files": []}, outputs=[msg])

                gr.Button("New Chat", variant="secondary", size="sm").click(
                    fn=lambda: ([], f"session_{datetime.now().timestamp()}"),
                    outputs=[chatbot, session_id],
                )

        # ── Event wiring ───────────────────────────────

        # 1. geocode_box value change → JS only: center map
        #    (fires when respond() yields a non-empty geocode trigger)
        geocode_box.change(
            fn=None,
            inputs=[geocode_box],
            js=CENTER_MAP_JS,
        )

        # 2. drag_box written by JS (pin drag or map click)
        #    → Python reverse geocodes → updates coord_state + status label
        drag_box.change(
            reverse_geocode_location,
            inputs=[drag_box],
            outputs=[coord_state, location_status],
        )

        # 3. Chat submit
        def respond(message, chat_history, session, coords):
            text  = message.get("text", "").strip()
            files = message.get("files", [])

            if not text and not files:
                yield None, chat_history, "", coords
                return

            # Prepend pinned location so agent uses it for the weather call
            agent_text = text
            if text and coords:
                parts = coords.split(",")
                if len(parts) == 2:
                    try:
                        lat, lng = float(parts[0]), float(parts[1])
                        agent_text = (
                            f"[My current location: latitude {lat:.6f}, "
                            f"longitude {lng:.6f}] {text}"
                        )
                    except ValueError:
                        pass

            for f in files:
                chat_history = chat_history + [{"role": "user", "content": f}]

            if text:
                chat_history = chat_history + [{"role": "user",      "content": text}]
                chat_history = chat_history + [{"role": "assistant", "content": ""}]

                active_coords = coords   # best-known location, updates on geocode
                geocode_trigger = ""     # non-empty triggers map center (one-shot per geocode)

                for partial_text, new_coords in chat_stream(agent_text, session):
                    if new_coords:
                        active_coords   = new_coords
                        geocode_trigger = new_coords   # fires geocode_box.change → JS
                    else:
                        geocode_trigger = ""           # reset so change only fires once

                    chat_history[-1]["content"] = partial_text
                    yield None, chat_history, geocode_trigger, active_coords
            else:
                yield None, chat_history, "", coords

        msg.submit(
            respond,
            inputs=[msg, chatbot, session_id, coord_state],
            outputs=[msg, chatbot, geocode_box, coord_state],
        )

    return demo


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY not set.")

    demo = create_gradio_app()
    demo.queue()
    demo.launch(share=False, css=CUSTOM_CSS, theme=gr.themes.Soft())
