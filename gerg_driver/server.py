# server.py
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
from importlib import resources
import io
import json
import os
import pwd
import threading
import time
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn


def _getlogin_fallback() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


try:
    os.getlogin()
except OSError:
    os.getlogin = _getlogin_fallback  # type: ignore[assignment]

try:
    from .car_controller import CarController, Picarx
except ModuleNotFoundError:
    # Fallback when imported as part of the gerg_driver package.
    from gerg_driver.car_controller import CarController, Picarx

try:
    from picamera2 import Picamera2  # type: ignore

    _PICAMERA_AVAILABLE = True
except ImportError:
    _PICAMERA_AVAILABLE = False

    class Picamera2:  # type: ignore[no-redef]
        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)


try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack  # type: ignore
    from av import VideoFrame  # type: ignore
    import numpy as np  # type: ignore

    _WEBRTC_IMPORT_ERROR = False
except ImportError:
    np = None
    _WEBRTC_IMPORT_ERROR = True
    RTCPeerConnection = None
    RTCSessionDescription = None

    class VideoStreamTrack:  # type: ignore[no-redef]
        async def next_timestamp(self):
            raise NotImplementedError

        async def recv(self):
            raise NotImplementedError

    class VideoFrame:  # type: ignore[no-redef]
        @classmethod
        def from_ndarray(cls, *args, **kwargs):
            raise NotImplementedError


if TYPE_CHECKING:

    class _VideoStreamTrackBase:
        async def next_timestamp(self):
            raise NotImplementedError

        async def recv(self):
            raise NotImplementedError

    class _PeerConnectionBase:
        async def close(self) -> None:
            raise NotImplementedError
else:
    _VideoStreamTrackBase = VideoStreamTrack
    _PeerConnectionBase = RTCPeerConnection


# Instantiate Picarx on the Pi. On your Mac, if you run this there,
# the mock in car_controller will be used instead.
px = Picarx()
controller = CarController(px=px)
TICK_INTERVAL = 0.02  # shorter interval to keep camera motion smooth
_tick_task: asyncio.Task | None = None


class CameraStream:
    """Very small helper to expose the Pi camera as MJPEG frames."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._picam2: Picamera2 | None = None
        self._size = (640, 480)
        self.available = False

        if not _PICAMERA_AVAILABLE:
            print("[CameraStream] picamera2 not installed; camera feed disabled.")
            return

        try:
            picam2 = Picamera2()
            config = picam2.create_video_configuration(
                main={"size": self._size, "format": "RGB888"},
                buffer_count=2,
            )
            picam2.configure(config)
            picam2.start()
            self._picam2 = picam2
            self.available = True
            print(f"[CameraStream] Camera ready at {self._size[0]}x{self._size[1]}.")
        except Exception as exc:  # pragma: no cover - heavily hardware dependent
            print(f"[CameraStream] Failed to start camera: {exc}")
            self._picam2 = None
            self.available = False

    def close(self) -> None:
        picam2 = self._picam2
        if picam2 is not None:
            with suppress(Exception):
                picam2.stop()
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

    def get_frame_array(self):
        picam2 = self._picam2
        if not self.available or picam2 is None:
            return None
        if np is None:
            return None
        with self._lock:
            try:
                frame = picam2.capture_array()
            except Exception as exc:  # pragma: no cover - hardware failure path
                print(f"[CameraStream] capture array failed: {exc}")
                return None
            return frame

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

WEBRTC_AVAILABLE = not _WEBRTC_IMPORT_ERROR and np is not None
_peer_connections: set[Any] = set()
_close_tasks: set[asyncio.Task[None]] = set()


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
        raise RuntimeError("Missing PiCar-X controller template; reinstall picar-x.") from exc


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


class CameraVideoTrack(_VideoStreamTrackBase):
    def __init__(self, camera: CameraStream) -> None:
        super().__init__()
        self._camera = camera
        self._last_frame = None
        self._fallback_frame = None

    async def recv(self):
        assert np is not None
        pts, time_base = await self.next_timestamp()
        frame = self._camera.get_frame_array()
        if frame is None:
            if self._last_frame is None:
                if self._fallback_frame is None:
                    width, height = self._camera._size
                    self._fallback_frame = np.zeros((height, width, 3), dtype=np.uint8)
                frame = self._fallback_frame
            else:
                frame = self._last_frame
        self._last_frame = frame
        video_frame = cast(Any, VideoFrame.from_ndarray(frame, format="rgb24"))
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


@app.post("/webrtc/offer")
async def webrtc_offer(payload: dict):
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC not available on this device")
    if not camera_stream.available:
        raise HTTPException(status_code=503, detail="Camera unavailable")

    sdp = payload.get("sdp")
    sdp_type = payload.get("type")
    if not sdp or not sdp_type:
        raise HTTPException(status_code=400, detail="Missing SDP offer")

    assert RTCPeerConnection is not None
    assert RTCSessionDescription is not None
    pc = RTCPeerConnection()
    _peer_connections.add(pc)

    @pc.on("connectionstatechange")
    def on_connectionstatechange():
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            task = asyncio.create_task(_close_peer(pc))
            _close_tasks.add(task)
            task.add_done_callback(_close_tasks.discard)

    pc.addTrack(CameraVideoTrack(camera_stream))

    offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    assert pc.localDescription is not None
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


async def _close_peer(pc: _PeerConnectionBase) -> None:
    if pc in _peer_connections:
        _peer_connections.discard(pc)
    await pc.close()


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
    for pc in list(_peer_connections):
        await _close_peer(pc)
    controller.shutdown()
    camera_stream.close()


def main(argv: list[str] | None = None) -> None:
    """Entry point used by `picarx-serve` console script."""
    parser = argparse.ArgumentParser(description="Run the PiCar-X control server.")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interface to bind (default: all interfaces)",
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

    try:
        server.run()
    except KeyboardInterrupt:
        # Uvicorn translates shutdown cancellation into KeyboardInterrupt.
        # Swallow it so Ctrl-C exits cleanly without a traceback.
        return
