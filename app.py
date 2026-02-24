"""
Gradio UI for the Weather Agent.
"""

import os
from datetime import datetime

import gradio as gr
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage

from agent import create_agent

load_dotenv()

# Create the agent once at module level
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


MAP_HTML = """
<p style="font-size:0.82rem; color:#6b7280; margin:0 0 8px; line-height:1.4;">
  Drag the pin, click the map, or search for a city. The location is used for weather queries.
</p>
<div style="display:flex; gap:8px; margin-bottom:8px;">
  <input id="map-addr-input" type="text" placeholder="Search city or address..."
    style="flex:1; padding:7px 12px; border-radius:10px; border:1px solid #e5e7eb;
           font-size:0.88rem; outline:none; font-family:inherit; box-sizing:border-box;"
    onkeydown="if(event.key==='Enter') window.weatherMapSearch()"/>
  <button onclick="window.weatherMapSearch()"
    style="padding:7px 14px; background:#6366f1; color:#fff; border:none;
           border-radius:10px; cursor:pointer; font-size:0.88rem; font-family:inherit;">
    Search
  </button>
</div>
<div id="weather-map" style="height:400px; border-radius:14px; overflow:hidden;
     border:1px solid #e5e7eb; isolation:isolate;"></div>
<div id="map-coord-status"
     style="font-size:0.76rem; color:#9ca3af; margin-top:5px; text-align:center;">
  Allow location access or search to set your starting point.
</div>
"""

MAP_JS = """
// element = this HTML component's root DOM node (Gradio 6 passes it via new Function)
// elem_id="map-widget" lets us re-find it reliably from window-scope functions.

function _mapRoot() {
  return document.getElementById('map-widget') || element;
}

// Load Leaflet CSS + JS dynamically
if (!document.getElementById('leaflet-css')) {
  var _lnk = document.createElement('link');
  _lnk.id = 'leaflet-css';
  _lnk.rel = 'stylesheet';
  _lnk.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  document.head.appendChild(_lnk);
}
if (!document.getElementById('leaflet-js')) {
  var _scr = document.createElement('script');
  _scr.id = 'leaflet-js';
  _scr.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  document.head.appendChild(_scr);
}

function _pushCoords(lat, lng) {
  var coordStr = lat.toFixed(6) + ',' + lng.toFixed(6);
  var root = _mapRoot();
  var st = root && root.querySelector('#map-coord-status');
  if (st) {
    st.textContent = 'Location: ' + lat.toFixed(5) + '\u00b0, ' + lng.toFixed(5) + '\u00b0';
    st.style.color = '#6366f1';
  }
  var attempts = 0;
  var tryPush = function() {
    var ta = document.querySelector('#coord-box textarea');
    if (ta) {
      ta.value = coordStr;
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      ta.dispatchEvent(new Event('change', { bubbles: true }));
    } else if (++attempts < 25) {
      setTimeout(tryPush, 200);
    }
  };
  tryPush();
}

window.weatherMapSearch = async function() {
  var root = _mapRoot();
  var inp = root && root.querySelector('#map-addr-input');
  var q = inp ? inp.value.trim() : '';
  if (!q) return;
  var st = root && root.querySelector('#map-coord-status');
  if (st) { st.textContent = 'Searching\u2026'; st.style.color = '#9ca3af'; }
  try {
    var r = await fetch(
      'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + encodeURIComponent(q),
      { headers: { 'Accept-Language': 'en' } }
    );
    var d = await r.json();
    if (d.length > 0) {
      if (window.weatherMapPlaceMarker)
        window.weatherMapPlaceMarker(parseFloat(d[0].lat), parseFloat(d[0].lon), 17);
      if (inp) inp.value = d[0].display_name;
    } else {
      if (st) { st.textContent = 'Location not found.'; st.style.color = '#ef4444'; }
    }
  } catch (e) {
    if (st) { st.textContent = 'Search error.'; st.style.color = '#ef4444'; }
  }
};

function _initMap() {
  var root = _mapRoot();
  var mapEl = root && root.querySelector('#weather-map');
  if (!mapEl || typeof L === 'undefined') {
    setTimeout(_initMap, 150);
    return;
  }
  if (mapEl._leaflet_id) return;

  var map = L.map(mapEl).setView([38.9, -77.0], 13);
  window._weatherMap = map;

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }).addTo(map);

  var marker = null;
  var placeMarker = function(lat, lng, zoom) {
    if (marker) {
      marker.setLatLng([lat, lng]);
    } else {
      marker = L.marker([lat, lng], { draggable: true }).addTo(map);
      marker.on('dragend', function(ev) {
        var p = ev.target.getLatLng();
        _pushCoords(p.lat, p.lng);
      });
    }
    if (zoom != null) map.setView([lat, lng], zoom);
    _pushCoords(lat, lng);
  };

  window.weatherMapPlaceMarker = placeMarker;
  map.on('click', function(ev) { placeMarker(ev.latlng.lat, ev.latlng.lng, null); });

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      function(pos) { placeMarker(pos.coords.latitude, pos.coords.longitude, 13); },
      function() {}
    );
  }

  new ResizeObserver(function() {
    setTimeout(function() { map.invalidateSize(); }, 50);
  }).observe(mapEl);
}

_initMap();
"""

CUSTOM_CSS = """
/* Viewport meta is set by Gradio, ensure proper scaling */
.gradio-container {
    max-width: 1200px !important;
    margin: 0 auto !important;
    padding: 0 1rem !important;
}

/* Header */
#header {
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    padding: 1.25rem 0 0.5rem;
}
#header .header-text {
    text-align: center;
}
#header h1 {
    font-size: 1.35rem;
    font-weight: 700;
    margin: 0;
}
#header p {
    font-size: 0.85rem;
    opacity: 0.6;
    margin: 0.25rem 0 0;
}
#header .logo {
    position: absolute;
    right: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 38px;
    height: 38px;
}

/* Chatbot */
#chatbot {
    border-radius: 16px !important;
    height: 480px !important;
}

/* Multimodal input */
#msg-input {
    border-radius: 12px !important;
}
#msg-input textarea {
    font-size: 1rem !important;
}

/* Suggestion chips */
.chip-row {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.25rem 0;
    flex-wrap: wrap;
}
.chip-row button {
    border-radius: 20px !important;
    font-size: 0.82em !important;
    white-space: nowrap !important;
}

/* Hide Gradio footer */
footer {
    display: none !important;
}

/* Map widget */
#weather-map { isolation: isolate; }
.leaflet-pane { z-index: 1 !important; }
.leaflet-top, .leaflet-bottom { z-index: 2 !important; }

/* ---- Mobile (max 640px) ---- */
@media (max-width: 640px) {
    .gradio-container {
        padding: 0 0.5rem !important;
    }

    #header {
        padding: 0.75rem 0 0.25rem;
    }
    #header h1 {
        font-size: 1.15rem;
    }
    #header p {
        font-size: 0.8rem;
    }

    /* Shorter chat area on small screens */
    #chatbot {
        height: 55dvh !important;
        border-radius: 12px !important;
    }

    /* Chips scroll horizontally instead of wrapping */
    .chip-row {
        flex-wrap: nowrap;
        overflow-x: auto;
        justify-content: flex-start;
        gap: 0.4rem;
        padding: 0.25rem 0.25rem;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }
    .chip-row::-webkit-scrollbar {
        display: none;
    }
    .chip-row button {
        flex-shrink: 0;
        font-size: 0.78em !important;
        padding: 0.35rem 0.75rem !important;
    }
}

/* ---- Tablet (641px – 1024px) ---- */
@media (min-width: 641px) and (max-width: 1024px) {
    .gradio-container {
        max-width: 700px !important;
    }

    #chatbot {
        height: 60dvh !important;
    }
}

/* ---- Large desktop (1025px+) ---- */
@media (min-width: 1025px) {
    #chatbot {
        height: 480px !important;
    }
}
"""


def create_gradio_app():
    """Create and return the Gradio interface."""

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

        session_id = gr.State(value=lambda: f"session_{datetime.now().timestamp()}")
        pin_coords = gr.State(value="")

        with gr.Row(equal_height=False):
            # Left column: map
            with gr.Column(scale=2, min_width=280):
                gr.HTML(value=MAP_HTML, elem_id="map-widget", js_on_load=MAP_JS)
                coord_box = gr.Textbox(elem_id="coord-box", visible=False)

            # Right column: chat
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
                        'Try &ldquo;Weather in Paris next week&rdquo;</p>'
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
                    "Weather in Paris next week?",
                    "Tokyo forecast Jan 20-25",
                    "LA weather in fahrenheit",
                    "London 5-day forecast",
                ]
                with gr.Row(elem_classes=["chip-row"]):
                    for s in suggestions:
                        btn = gr.Button(s, variant="secondary", size="sm")
                        btn.click(fn=lambda text=s: {"text": text, "files": []}, outputs=[msg])

                gr.Button("New Chat", variant="secondary", size="sm").click(
                    fn=lambda: ([], f"session_{datetime.now().timestamp()}"),
                    outputs=[chatbot, session_id],
                )

        # Wire JS bridge → pin_coords state
        coord_box.change(fn=lambda c: c, inputs=[coord_box], outputs=[pin_coords])

        # --- Event wiring ---
        def respond(message, chat_history, session, coords):
            text = message.get("text", "").strip()
            files = message.get("files", [])

            if not text and not files:
                yield None, chat_history
                return

            # Inject location into agent message (user sees original text)
            agent_text = text
            if text and coords:
                parts = [p.strip() for p in coords.split(",")]
                if len(parts) == 2:
                    try:
                        float(parts[0]); float(parts[1])
                        agent_text = (
                            f"[My current location: latitude {parts[0]}, "
                            f"longitude {parts[1]}] {text}"
                        )
                    except ValueError:
                        pass

            # Display uploaded images in chat
            for f in files:
                chat_history = chat_history + [{"role": "user", "content": f}]

            # Stream agent response for the text portion
            if text:
                chat_history = chat_history + [{"role": "user", "content": text}]
                chat_history = chat_history + [{"role": "assistant", "content": ""}]
                for partial_response in chat_stream(agent_text, chat_history, session):
                    chat_history[-1]["content"] = partial_response
                    yield None, chat_history
            else:
                yield None, chat_history

        msg.submit(respond, [msg, chatbot, session_id, pin_coords], [msg, chatbot])

    return demo


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY environment variable not set!")
        print("Please set it with: export OPENAI_API_KEY='your-api-key'")
        print("Or create a .env file with: OPENAI_API_KEY=your-api-key")
        print()

    demo = create_gradio_app()
    demo.queue()
    demo.launch(share=False, css=CUSTOM_CSS, theme=gr.themes.Soft())
