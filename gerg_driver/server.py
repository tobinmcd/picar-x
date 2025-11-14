# server.py
from __future__ import annotations

import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from car_controller import CarController, Picarx  # type: ignore

app = FastAPI()

# Instantiate Picarx on the Pi. On your Mac, if you run this there,
# the mock in car_controller will be used instead.
px = Picarx()
controller = CarController(px=px)

HTML_PAGE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>PiCar-X Controller</title>
    <style>
      body { font-family: sans-serif; padding: 1rem; }
      #status { margin-top: 0.5rem; font-size: 0.9rem; }
      .key-hint { font-family: monospace; padding: 0.1rem 0.3rem; border: 1px solid #ccc; border-radius: 4px; }
    </style>
  </head>
  <body>
    <h1>PiCar-X Controller</h1>
    <p>
      Use <span class="key-hint">W</span>
          <span class="key-hint">A</span>
          <span class="key-hint">S</span>
          <span class="key-hint">D</span>
      or arrow keys to drive the robot.
    </p>
    <p id="status">Connecting...</p>

    <script>
      const statusEl = document.getElementById("status");
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${protocol}://${location.host}/ws/keys`);

      ws.onopen = () => {
        statusEl.textContent = "Connected";
      };

      ws.onclose = () => {
        statusEl.textContent = "Disconnected";
      };

      ws.onerror = (event) => {
        console.error("WebSocket error:", event);
        statusEl.textContent = "Error (see console)";
      };

      ws.onmessage = (event) => {
        // For future telemetry; for now just log
        console.log("From server:", event.data);
      };

      // Track which keys we've reported as pressed to avoid duplicates.
      const pressed = new Set();

      function handleKey(event, isDown) {
        const key = event.key;                      // e.g. "w", "ArrowUp"
        const normalized =
          key.length === 1
            ? key.toLowerCase()
            : key.startsWith("Arrow")
              ? key.toLowerCase()
              : key;

        const relevantKeys = ["w","a","s","d","arrowup","arrowdown","arrowleft","arrowright"];
        if (!relevantKeys.includes(normalized)) {
          return;
        }

        event.preventDefault();

        if (isDown) {
          if (pressed.has(key)) {
            return;  // already down from our POV
          }
          pressed.add(key);
        } else {
          if (!pressed.has(key)) {
            return;  // nothing to release
          }
          pressed.delete(key);
        }

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ key: normalized, pressed: isDown }));
        }
      }

      document.addEventListener("keydown", (event) => handleKey(event, true));
      document.addEventListener("keyup", (event)  => handleKey(event, false));
    </script>
  </body>
</html>
"""

@app.get("/")
async def index():
    return HTMLResponse(HTML_PAGE)


@app.websocket("/ws/keys")
async def websocket_keys(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            key = payload.get("key")
            pressed = bool(payload.get("pressed", True))
            if key is not None:
                controller.on_key_event(key, pressed)
            # Optional echo for debugging
            await websocket.send_text(f"ok {key} {'down' if pressed else 'up'}")
    except WebSocketDisconnect:
        # Client closed the connection; ensure the robot stops safely.
        controller.clear_keys()
        controller.shutdown()


@app.on_event("shutdown")
def shutdown_event():
    controller.shutdown()
