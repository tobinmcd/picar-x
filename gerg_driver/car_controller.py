# car_controller.py
from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Protocol, cast


class PicarxProtocol(Protocol):
    def forward(self, speed: int) -> None: ...

    def backward(self, speed: int) -> None: ...

    def stop(self) -> None: ...

    def set_dir_servo_angle(self, value: int) -> None: ...

    def set_cam_tilt_angle(self, value: int) -> None: ...

    def set_cam_pan_angle(self, value: int) -> None: ...


Picarx: type[PicarxProtocol]

try:
    from picarx import Picarx as HardwarePicarx

    Picarx = cast(type[PicarxProtocol], HardwarePicarx)
except ImportError:  # Running on a dev machine without hardware

    class MockPicarx:
        def forward(self, speed: int):
            print(f"[mock] forward {speed}")

        def backward(self, speed: int):
            print(f"[mock] backward {speed}")

        def stop(self):
            print("[mock] stop")

        def set_dir_servo_angle(self, angle: int):
            print(f"[mock] dir_servo {angle}")

        def set_cam_tilt_angle(self, angle: int):
            print(f"[mock] tilt {angle}")

        def set_cam_pan_angle(self, angle: int):
            print(f"[mock] pan {angle}")

    Picarx = cast(type[PicarxProtocol], MockPicarx)


@dataclass
class CarController:
    """
    Stateless-ish adapter that lets the web layer say:
        controller.on_key_event(key, pressed)
    and we turn that into Picarx calls.

    Parameters
    ----------
    px:
        Initialized ``Picarx`` (or the mock) that actually talks to the hardware.
    """

    px: PicarxProtocol | None

    speed: int = 100  # tune this
    turn_angle: int = 20  # steering servo angle
    camera_step: float = 0.8
    camera_pan_limit: int = 45
    camera_tilt_limit: int = 30
    active_keys: set[str] = field(default_factory=set)
    forward_keys: set[str] = field(default_factory=lambda: {"w", "arrowup"})
    back_keys: set[str] = field(default_factory=lambda: {"s", "arrowdown"})
    left_keys: set[str] = field(default_factory=lambda: {"a", "arrowleft"})
    right_keys: set[str] = field(default_factory=lambda: {"d", "arrowright"})
    camera_up_keys: set[str] = field(default_factory=lambda: {"i"})
    camera_down_keys: set[str] = field(default_factory=lambda: {"k"})
    camera_left_keys: set[str] = field(default_factory=lambda: {"j"})
    camera_right_keys: set[str] = field(default_factory=lambda: {"l"})
    camera_center_keys: set[str] = field(default_factory=lambda: {"center-camera"})
    pan_angle: int = 0
    tilt_angle: int = 0
    pan_angle_f: float = 0.0
    tilt_angle_f: float = 0.0
    last_dir_angle: int | None = None
    last_drive_direction: int | None = None
    last_drive_speed: int | None = None
    camera_speed_scale: float = 1.0
    gamepad_deadzone: float = 0.08
    gamepad_timeout_s: float = 0.6
    gamepad_active: bool = False
    gamepad_last_ts: float = 0.0
    gamepad_lx: float = 0.0
    gamepad_ly: float = 0.0
    gamepad_rx: float = 0.0
    gamepad_ry: float = 0.0

    def on_key_event(self, key: str, pressed: bool) -> None:
        """Handle a key down/up event coming from the web client."""
        k = key.lower()
        if k in self.camera_center_keys:
            if pressed:
                self.recenter_camera()
            return
        if pressed:
            self.active_keys.add(k)
        else:
            self.active_keys.discard(k)
        self._apply_motion()

    def on_gamepad_state(self, lx: float, ly: float, rx: float, ry: float) -> None:
        """Handle analog gamepad state from the web client."""
        self.gamepad_active = True
        self.gamepad_last_ts = time.monotonic()
        self.gamepad_lx = self._apply_deadzone(self._clamp_axis(lx))
        self.gamepad_ly = self._apply_deadzone(self._clamp_axis(ly))
        self.gamepad_rx = self._apply_deadzone(self._clamp_axis(rx))
        self.gamepad_ry = self._apply_deadzone(self._clamp_axis(ry))
        self._apply_motion()

    def clear_gamepad(self) -> None:
        """Forget any gamepad state and return to keyboard control."""
        self.gamepad_active = False
        self.gamepad_last_ts = 0.0
        self.gamepad_lx = 0.0
        self.gamepad_ly = 0.0
        self.gamepad_rx = 0.0
        self.gamepad_ry = 0.0

    def clear_keys(self) -> None:
        """Forget any keys the server thinks are active and stop motion."""
        if self.active_keys:
            self.active_keys.clear()
            self._apply_motion()

    # --- main motion logic --------------------------------------------------

    def _apply_motion(self) -> None:
        """Compute robot motion from the current active_keys."""
        px = self._require_px()
        if px is None:
            return

        if self._use_gamepad():
            self._apply_drive_gamepad(px)
            self._update_camera_gamepad(px)
        else:
            self._apply_drive(px)
            self._update_camera(px)

    def tick(self) -> None:
        """Call periodically to keep the camera moving while keys are held."""
        px = self._require_px(log=False)
        if px is None:
            return
        if (
            self.gamepad_active
            and self.gamepad_last_ts
            and time.monotonic() - self.gamepad_last_ts > self.gamepad_timeout_s
        ):
            self.clear_gamepad()
            if self.active_keys:
                self._apply_motion()
            else:
                self._set_drive(px, direction=0, speed=0)
                self._set_dir_servo_angle(px, 0)
            return
        if not self._use_gamepad():
            self._update_camera(px)

    def _require_px(self, *, log: bool = True) -> PicarxProtocol | None:
        px = self.px
        if px is None and log:
            print(f"[CarController] active_keys={self.active_keys}")
        return px

    def _apply_drive(self, px) -> None:
        moving_forward = bool(self.active_keys & self.forward_keys)
        moving_back = bool(self.active_keys & self.back_keys)
        turning_left = bool(self.active_keys & self.left_keys)
        turning_right = bool(self.active_keys & self.right_keys)

        # --- Drive direction ---
        if (not moving_forward and not moving_back) or (moving_forward and moving_back):
            self._set_drive(px, direction=0, speed=0)
        else:
            if moving_forward:
                self._set_drive(px, direction=1, speed=self.speed)
            elif moving_back:
                self._set_drive(px, direction=-1, speed=self.speed)

        # --- Steering servo ---
        if turning_left and not turning_right:
            self._set_dir_servo_angle(px, -self.turn_angle)
        elif turning_right and not turning_left:
            self._set_dir_servo_angle(px, self.turn_angle)
        else:
            self._set_dir_servo_angle(px, 0)

    def _apply_drive_gamepad(self, px) -> None:
        steering = round(self.turn_angle * self.gamepad_lx)
        self._set_dir_servo_angle(px, steering)

        if self.gamepad_ly == 0.0:
            self._set_drive(px, direction=0, speed=0)
            return

        speed = round(self.speed * abs(self.gamepad_ly))
        if self.gamepad_ly < 0:
            self._set_drive(px, direction=1, speed=speed)
        else:
            self._set_drive(px, direction=-1, speed=speed)

    def _update_camera(self, px) -> None:
        """Incrementally apply camera movement."""
        tilt_up = bool(self.active_keys & self.camera_up_keys)
        tilt_down = bool(self.active_keys & self.camera_down_keys)
        pan_right = bool(self.active_keys & self.camera_right_keys)
        pan_left = bool(self.active_keys & self.camera_left_keys)

        delta_pan = self.camera_step * ((1 if pan_right else 0) - (1 if pan_left else 0))
        delta_tilt = self.camera_step * ((1 if tilt_up else 0) - (1 if tilt_down else 0))
        if delta_pan == 0.0 and delta_tilt == 0.0:
            return

        new_pan_f = self._clamp_camera_angle(self.pan_angle_f + delta_pan, self.camera_pan_limit)
        new_tilt_f = self._clamp_camera_angle(
            self.tilt_angle_f + delta_tilt,
            self.camera_tilt_limit,
        )
        pan = self._round_camera_angle(new_pan_f)
        tilt = self._round_camera_angle(new_tilt_f)

        self.pan_angle_f = new_pan_f
        self.tilt_angle_f = new_tilt_f

        if pan != self.pan_angle:
            self.pan_angle = pan
            px.set_cam_pan_angle(pan)

        if tilt != self.tilt_angle:
            self.tilt_angle = tilt
            px.set_cam_tilt_angle(tilt)

    def _update_camera_gamepad(self, px) -> None:
        delta_pan = self.camera_step * self.camera_speed_scale * self.gamepad_rx
        delta_tilt = self.camera_step * self.camera_speed_scale * -self.gamepad_ry
        if delta_pan == 0.0 and delta_tilt == 0.0:
            return

        new_pan_f = self._clamp_camera_angle(self.pan_angle_f + delta_pan, self.camera_pan_limit)
        new_tilt_f = self._clamp_camera_angle(
            self.tilt_angle_f + delta_tilt,
            self.camera_tilt_limit,
        )
        pan = self._round_camera_angle(new_pan_f)
        tilt = self._round_camera_angle(new_tilt_f)

        self.pan_angle_f = new_pan_f
        self.tilt_angle_f = new_tilt_f

        if pan != self.pan_angle:
            self.pan_angle = pan
            px.set_cam_pan_angle(pan)

        if tilt != self.tilt_angle:
            self.tilt_angle = tilt
            px.set_cam_tilt_angle(tilt)

    def _clamp_camera_angle(self, value: float, limit: int) -> float:
        bound = float(limit)
        if value > bound:
            return bound
        if value < -bound:
            return -bound
        return value

    def _round_camera_angle(self, value: float) -> int:
        if value >= 0:
            return math.floor(value + 0.5)
        return math.ceil(value - 0.5)

    def _set_dir_servo_angle(self, px, angle: int) -> None:
        if self.last_dir_angle is not None and self.last_dir_angle == angle:
            return
        self.last_dir_angle = angle
        px.set_dir_servo_angle(angle)

    def _set_drive(self, px, *, direction: int, speed: int) -> None:
        if (
            self.last_drive_direction is not None
            and self.last_drive_speed is not None
            and self.last_drive_direction == direction
            and self.last_drive_speed == speed
        ):
            return
        self.last_drive_direction = direction
        self.last_drive_speed = speed
        if direction == 0:
            px.stop()
        elif direction > 0:
            px.forward(speed)
        else:
            px.backward(speed)

    def recenter_camera(self) -> None:
        """Snap the camera back to the neutral pan/tilt position."""
        px = self._require_px()
        if px is None:
            self.pan_angle = 0
            self.tilt_angle = 0
            self.pan_angle_f = 0.0
            self.tilt_angle_f = 0.0
            return
        self.pan_angle = 0
        self.tilt_angle = 0
        self.pan_angle_f = 0.0
        self.tilt_angle_f = 0.0
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)

    def _use_gamepad(self) -> bool:
        if not self.gamepad_active:
            return False
        if (
            self.gamepad_last_ts
            and time.monotonic() - self.gamepad_last_ts > self.gamepad_timeout_s
        ):
            self.gamepad_active = False
            return False
        return True

    def _apply_deadzone(self, value: float) -> float:
        if abs(value) < self.gamepad_deadzone:
            return 0.0
        return value

    def _clamp_axis(self, value: float) -> float:
        if value > 1.0:
            return 1.0
        if value < -1.0:
            return -1.0
        return value

    def shutdown(self) -> None:
        """Reset the robot to a safe neutral state."""
        if self.px is not None:
            self.px.set_cam_tilt_angle(0)
            self.px.set_cam_pan_angle(0)
            self.px.set_dir_servo_angle(0)
            self.px.stop()
        self.pan_angle = 0
        self.tilt_angle = 0
        self.pan_angle_f = 0.0
        self.tilt_angle_f = 0.0
        self.last_dir_angle = 0
        self.last_drive_direction = 0
        self.last_drive_speed = 0
