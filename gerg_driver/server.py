# server.py
from __future__ import annotations

import argparse
import asyncio
import io
import json
import signal
import threading
import time
from contextlib import asynccontextmanager, suppress
from importlib import resources

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse

import os
import pwd
try:
    os.getlogin()
except OSError:
    os.getlogin = lambda: pwd.getpwuid(os.getuid()).pw_name

try:
    from car_controller import CarController, Picarx
except ModuleNotFoundError:
    # Fallback when imported as part of the gerg_driver package.
    from gerg_driver.car_controller import CarController, Picarx

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None


# Instantiate Picarx on the Pi. On your Mac, if you run this there,
# the mock in car_controller will be used instead.
px = Picarx()
controller = CarController(px=px)
TICK_INTERVAL = 0.03  # shorter interval to keep camera motion smooth
_tick_task: asyncio.Task | None = None

class CameraStream:
    """Very small helper to expose the Pi camera as MJPEG frames."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._picam2: Picamera2 | None = None
        self.available = False

        if Picamera2 is None:
            print("[CameraStream] picamera2 not installed; camera feed disabled.")
            return

        try:
            picam2 = Picamera2()
            config = picam2.create_video_configuration(main={"size": (640, 480)})
            picam2.configure(config)
            picam2.start()
            self._picam2 = picam2
            self.available = True
            print("[CameraStream] Camera ready at 640x480.")
        except Exception as exc:  # pragma: no cover - heavily hardware dependent
            print(f"[CameraStream] Failed to start camera: {exc}")
            self._picam2 = None
            self.available = False

    def close(self) -> None:
        picam2 = self._picam2
        if picam2 is not None:
            try:
                picam2.stop()
            except Exception:
                pass
            picam2.close()
        self._picam2 = None
        self.available = False

    def get_frame(self) -> bytes | None:
        picam2 = self._picam2
        if not self.available or picam2 is None:
            return None
        with self._lock:
            buffer = io.BytesIO()
            try:
                picam2.capture_file(buffer, format="jpeg")
            except Exception as exc:  # pragma: no cover - hardware failure path
                print(f"[CameraStream] capture failed: {exc}")
                return None
            return buffer.getvalue()

    def stream(self):
        while self.available:
            frame = self.get_frame()
            if frame is None:
                time.sleep(0.25)
                continue
            header = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
            )
            yield header + frame + b"\r\n"

camera_stream = CameraStream()

class GracefulStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except asyncio.CancelledError:
            # Shutdown can cancel ongoing streams; suppress noisy tracebacks.
            return

    async def listen_for_disconnect(self, receive) -> None:
        try:
            await super().listen_for_disconnect(receive)
        except asyncio.CancelledError:
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup_event()
    try:
        yield
    except asyncio.CancelledError:
        # Cancellation during shutdown should not bubble as an error.
        pass
    finally:
        await _shutdown_event()


app = FastAPI(lifespan=lifespan)


def _load_html_template() -> str:
    template_path = resources.files("gerg_driver").joinpath("templates/index.html")
    try:
        return template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - packaging issue
        raise RuntimeError(
            "Missing PiCar-X controller template; reinstall picar-x."
        ) from exc


HTML_PAGE = _load_html_template()

@app.get("/")
async def index():
    return HTMLResponse(HTML_PAGE)


@app.get("/camera/status")
async def camera_status():
    return {"available": camera_stream.available}


@app.get("/video")
async def video_feed():
    if not camera_stream.available:
        raise HTTPException(status_code=503, detail="Camera unavailable")
    return GracefulStreamingResponse(
        camera_stream.stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.websocket("/ws/keys")
async def websocket_keys(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            msg_type = payload.get("type")
            if msg_type == "gamepad":
                axes = payload.get("axes", {})
                controller.on_gamepad_state(
                    float(axes.get("lx", 0.0)),
                    float(axes.get("ly", 0.0)),
                    float(axes.get("rx", 0.0)),
                    float(axes.get("ry", 0.0)),
                )
                await websocket.send_text("ok gamepad")
                continue

            key = payload.get("key")
            pressed = bool(payload.get("pressed", True))
            if key is not None:
                controller.on_key_event(key, pressed)
            # Optional echo for debugging
            await websocket.send_text(f"ok {key} {'down' if pressed else 'up'}")
    except WebSocketDisconnect:
        # Client closed the connection; ensure the robot stops safely.
        controller.clear_keys()
        controller.clear_gamepad()
        controller.shutdown()


async def _tick_loop():
    try:
        while True:
            controller.tick()
            await asyncio.sleep(TICK_INTERVAL)
    except asyncio.CancelledError:
        pass


async def _startup_event() -> None:
    global _tick_task
    loop = asyncio.get_running_loop()
    _tick_task = loop.create_task(_tick_loop())


async def _shutdown_event() -> None:
    global _tick_task
    if _tick_task is not None:
        _tick_task.cancel()
        with suppress(asyncio.CancelledError):
            await _tick_task
        _tick_task = None
    controller.shutdown()
    camera_stream.close()


def main(argv: list[str] | None = None) -> None:
    """Entry point used by `picarx-serve` console script."""
    parser = argparse.ArgumentParser(description="Run the PiCar-X control server.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default: loopback only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="TCP port to serve on (default: 8000)",
    )
    args = parser.parse_args(argv)
    config = uvicorn.Config(
        "gerg_driver.server:app",
        host=args.host,
        port=args.port,
    )
    server = uvicorn.Server(config)

    def _handle_exit(signum, frame) -> None:
        if server.should_exit:
            server.force_exit = True
        else:
            server.should_exit = True

    server.install_signal_handlers = False
    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)
    try:
        server.run()
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
