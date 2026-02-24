# Map Widget Implementation

Add an interactive Leaflet.js map to `app.py` that lets users set their location, which is then injected into weather queries.

## What it does

- Shows an interactive map with a draggable pin
- Tries `navigator.geolocation` on load; falls back gracefully
- Address search bar (Nominatim/OpenStreetMap — free, no API key)
- Click anywhere on the map to move the pin
- Coordinates are silently prepended to agent messages as `[My current location: latitude X, longitude Y]`
- User sees their original message in the chat; the agent gets the location context

## Files to change

Only `app.py`.

---

## Step 1 — Add `MAP_HTML` constant (after `CUSTOM_CSS`)

```python
MAP_HTML = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<p style="font-size:0.82rem; color:#6b7280; margin:0 0 8px; line-height:1.4;">
  Drag the pin, click the map, or search for a city. The location is used for weather queries.
</p>
<div style="display:flex; gap:8px; margin-bottom:8px;">
  <input id="map-addr-input" type="text" placeholder="Search city or address..."
    style="flex:1; padding:7px 12px; border-radius:10px; border:1px solid #e5e7eb;
           font-size:0.88rem; outline:none; font-family:inherit; box-sizing:border-box;"
    onkeydown="if(event.key==='Enter') weatherMapSearch()"/>
  <button onclick="weatherMapSearch()"
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

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function() {
  if (window._weatherMapInitDone) return;
  window._weatherMapInitDone = true;

  var marker = null;

  function tryInit(attempts) {
    if (typeof L === 'undefined' || !document.getElementById('weather-map')) {
      if (attempts < 20) setTimeout(function() { tryInit(attempts + 1); }, 200);
      return;
    }
    var map = L.map('weather-map').setView([38.9, -77.0], 16);
    window._weatherMap = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18
    }).addTo(map);

    function placeMarker(lat, lng, zoom) {
      if (marker) {
        marker.setLatLng([lat, lng]);
      } else {
        marker = L.marker([lat, lng], { draggable: true }).addTo(map);
        marker.on('dragend', function(e) {
          var p = e.target.getLatLng();
          pushCoords(p.lat, p.lng);
        });
      }
      if (zoom != null) map.setView([lat, lng], zoom);
      pushCoords(lat, lng);
    }

    window.weatherMapPlaceMarker = placeMarker;
    map.on('click', function(e) { placeMarker(e.latlng.lat, e.latlng.lng, null); });

    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        function(pos) { placeMarker(pos.coords.latitude, pos.coords.longitude, 17); },
        function() {}
      );
    }

    new ResizeObserver(function() {
      setTimeout(function() { map.invalidateSize(); }, 50);
    }).observe(document.getElementById('weather-map'));
  }

  tryInit(0);

  function pushCoords(lat, lng) {
    var coordStr = lat.toFixed(6) + ',' + lng.toFixed(6);
    var st = document.getElementById('map-coord-status');
    if (st) {
      st.textContent = 'Location: ' + lat.toFixed(5) + '\u00b0, ' + lng.toFixed(5) + '\u00b0';
      st.style.color = '#6366f1';
    }
    var attempts = 0;
    (function tryPush() {
      var ta = document.querySelector('#coord-box textarea');
      if (ta) {
        ta.value = coordStr;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        ta.dispatchEvent(new Event('change', { bubbles: true }));
      } else if (++attempts < 25) {
        setTimeout(tryPush, 200);
      }
    })();
  }

  window.weatherMapSearch = async function() {
    var inp = document.getElementById('map-addr-input');
    var q = inp ? inp.value.trim() : '';
    if (!q) return;
    var st = document.getElementById('map-coord-status');
    if (st) { st.textContent = 'Searching\u2026'; st.style.color = '#9ca3af'; }
    try {
      var r = await fetch(
        'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + encodeURIComponent(q),
        { headers: { 'Accept-Language': 'en' } }
      );
      var d = await r.json();
      if (d.length > 0) {
        if (window.weatherMapPlaceMarker)
          window.weatherMapPlaceMarker(parseFloat(d[0].lat), parseFloat(d[0].lon), 13);
        if (inp) inp.value = d[0].display_name;
      } else {
        if (st) { st.textContent = 'Location not found.'; st.style.color = '#ef4444'; }
      }
    } catch (e) {
      if (st) { st.textContent = 'Search error.'; st.style.color = '#ef4444'; }
    }
  };
})();
</script>
"""
```

---

## Step 2 — Update `CUSTOM_CSS`

Add these rules at the end of the `CUSTOM_CSS` string (before the closing `"""`):

```css
/* Map widget */
#weather-map { isolation: isolate; }
.leaflet-pane { z-index: 1 !important; }
.leaflet-top, .leaflet-bottom { z-index: 2 !important; }
```

Also update `max-width` in `.gradio-container` from `820px` to `1200px` to accommodate the side-by-side layout.

---

## Step 3 — Update `create_gradio_app()`

Replace the body with a side-by-side layout. Key changes:

1. Add `pin_coords = gr.State(value="")` after `session_id`
2. Wrap map and chat in `gr.Row` → two `gr.Column`s
3. Add hidden `coord_box` textbox (JS bridge)
4. Wire `coord_box.change()` → `pin_coords`
5. Update `respond()` signature to accept `coords` and inject location
6. Add `pin_coords` to `msg.submit` inputs

```python
def create_gradio_app():
    with gr.Blocks(title="Weather Agent") as demo:
        gr.HTML(
            # ... keep existing header HTML unchanged ...
        )

        session_id = gr.State(value=lambda: f"session_{datetime.now().timestamp()}")
        pin_coords = gr.State(value="")

        with gr.Row(equal_height=False):
            # ── Left column: map ──────────────────────────────
            with gr.Column(scale=2, min_width=280):
                gr.HTML(MAP_HTML)
                coord_box = gr.Textbox(elem_id="coord-box", visible=False)

            # ── Right column: chat ────────────────────────────
            with gr.Column(scale=3, min_width=320):
                chatbot = gr.Chatbot(
                    elem_id="chatbot",
                    show_label=False,
                    placeholder=( ... ),  # keep unchanged
                )

                msg = gr.MultimodalTextbox(
                    elem_id="msg-input",
                    placeholder="Message Weather Agent...",
                    show_label=False,
                    file_types=["image"],
                )

                suggestions = [ ... ]  # keep unchanged
                with gr.Row(elem_classes=["chip-row"]):
                    for s in suggestions:
                        btn = gr.Button(s, variant="secondary", size="sm")
                        btn.click(fn=lambda text=s: {"text": text, "files": []}, outputs=[msg])

                gr.Button("New Chat", variant="secondary", size="sm").click(
                    fn=lambda: ([], f"session_{datetime.now().timestamp()}"),
                    outputs=[chatbot, session_id],
                )

        # Wire JS bridge → pin_coords state
        coord_box.change(
            fn=lambda c: c,
            inputs=[coord_box],
            outputs=[pin_coords],
        )

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

            for f in files:
                chat_history = chat_history + [{"role": "user", "content": f}]

            if text:
                chat_history = chat_history + [{"role": "user", "content": text}]
                chat_history = chat_history + [{"role": "assistant", "content": ""}]
                for partial_response in chat_stream(agent_text, chat_history, session):
                    chat_history[-1]["content"] = partial_response
                    yield None, chat_history
            else:
                yield None, chat_history

        # Add pin_coords to inputs
        msg.submit(respond, [msg, chatbot, session_id, pin_coords], [msg, chatbot])

    return demo
```

---

## How JS → Python communication works

```
User drags pin / searches address
  → JS calls pushCoords(lat, lng)
    → finds #coord-box textarea
    → sets textarea.value = "lat,lng"
    → dispatches native 'input' + 'change' events
      → Gradio's Svelte reactive system picks up the change
        → coord_box.change() fires
          → pin_coords State updated
            → next respond() call includes coordinates
```

Gradio 4.x `gr.HTML` re-executes `<script>` tags by replacing them with new `document.createElement('script')` nodes (in `@gradio/html` Svelte component's `afterUpdate` hook), so inline scripts work.

---

## Notes

- **No API key needed**: Nominatim is free. Leaflet tiles are free from OpenStreetMap.
- **No `agent.py` changes needed**: The LLM handles `[My current location: ...]` prefixes naturally.
- **Privacy**: Geolocation prompts the user for permission; declining is a silent no-op (map starts at DC as fallback).
- **`window._weatherMapInitDone` guard**: Prevents double-initialization if Gradio re-renders the HTML component.
- **`ResizeObserver`**: Calls `map.invalidateSize()` if the container is ever hidden/shown (e.g., if you later add an accordion).
