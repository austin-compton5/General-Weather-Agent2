# Map Implementation Notes

## The Core Problem: Gradio Doesn't Have a Map

Gradio doesn't ship with a map component. The only way to add one is to inject raw HTML and JavaScript using `gr.HTML` — which works, but Gradio wasn't really designed for it.

---

## The Svelte Problem

Gradio's UI is built with a framework called Svelte. Svelte intentionally walls off its components from outside JavaScript — custom JS you inject can't directly read or write Gradio's inputs and outputs. There's no official API for it.

This means we can't just say "hey map, when the user clicks, update this textbox." We have to trick Gradio into thinking a user typed something.

---

## Workarounds We Used

### 1. A hidden textbox as a messenger (Map → Python)

We added a hidden textbox (`coord_box`) to the page. When the user clicks the map or drags the pin, the map's JavaScript writes the coordinates into that textbox and fires fake "typing" events. Gradio sees those events, thinks a user typed something, and passes the value to Python normally.

It also has to retry in a loop because Gradio builds the page piece by piece — the textbox might not exist yet when the map first loads.

### 2. A second hidden textbox (Python → Map)

We needed the reverse too: when the agent looks up a city and gets coordinates back, the map pin should move. To do that, Python writes the coordinates to a second hidden textbox (`map_out_box`). We watch that textbox for changes and fire JavaScript to move the pin when it updates.

### 3. Window globals so the two scripts can talk

The map setup script and the pin-moving script run at different times and can't see each other's variables. We worked around this by attaching the map and the pin function to `window` (the browser's global object), so both scripts can find them.

### 4. CSS fixes for map controls getting buried

Gradio's layout kept rendering on top of the map's zoom buttons and tiles. We had to manually set z-index values in CSS to force the map layers to the right depth.

---

## Fragile Points

| What | Why it could break |
|---|---|
| Hidden textbox trick | Depends on Gradio rendering a `<textarea>` with a specific ID. If a Gradio update changes that structure, coordinates stop flowing silently. |
| Fake typing events | If Gradio changes how it listens for input events internally, the bridge breaks with no error message. |
| Map load timing | The retry loop waits 150ms between attempts. On a slow connection, Leaflet might not load in time and the map won't initialize. |
| Window globals | If Gradio ever re-renders the map component, those globals get wiped and the pin stops moving. |
| Regex coordinate parsing | We pull lat/lng out of the geocoder's text response using a pattern match. If the tool's output format changes even slightly, the map pin silently stops updating. |
| `js=`-only change event | The pattern we use to trigger JS from Python (a `.change()` with no Python function, just a `js=` side effect) is undocumented. It works today but isn't a guaranteed feature. |

---

## Summary

The map works for the POC, but it relies on several hacks that Gradio doesn't officially support. None of them give useful errors when they break — things will just silently stop working. If this moves to production, the right fix is to use a framework that gives JavaScript proper access to the UI, rather than fighting Gradio's walls.
