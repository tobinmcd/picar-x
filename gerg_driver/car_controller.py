# car_controller.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set, Union

try:
    from picarx import Picarx as HardwarePicarx
    Picarx = HardwarePicarx
except ImportError:  # Running on a dev machine without hardware
    class MockPicarx:
        def forward(self, speed: int): print(f"[mock] forward {speed}")
        def backward(self, speed: int): print(f"[mock] backward {speed}")
        def stop(self): print("[mock] stop")
        def set_dir_servo_angle(self, angle: int): print(f"[mock] dir_servo {angle}")
        def set_cam_tilt_angle(self, angle: int): print(f"[mock] tilt {angle}")
        def set_cam_pan_angle(self, angle: int): print(f"[mock] pan {angle}")
    Picarx = MockPicarx

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
    px: Union[HardwarePicarx, MockPicarx]

    speed: int = 100         # tune this
    turn_angle: int = 30    # steering servo angle
    camera_step: int = 1
    camera_limit: int = 30
    active_keys: Set[str] = field(default_factory=set)
    forward_keys: Set[str] = field(default_factory=lambda: {"w", "arrowup"})
    back_keys: Set[str]    = field(default_factory=lambda: {"s", "arrowdown"})
    left_keys: Set[str]    = field(default_factory=lambda: {"a", "arrowleft"})
    right_keys: Set[str]   = field(default_factory=lambda: {"d", "arrowright"})
    camera_up_keys: Set[str]    = field(default_factory=lambda: {"i"})
    camera_down_keys: Set[str]  = field(default_factory=lambda: {"k"})
    camera_left_keys: Set[str]  = field(default_factory=lambda: {"j"})
    camera_right_keys: Set[str] = field(default_factory=lambda: {"l"})
    pan_angle: int = 0
    tilt_angle: int = 0

    def on_key_event(self, key: str, pressed: bool) -> None:
        """Handle a key down/up event coming from the web client."""
        k = key.lower()
        if pressed:
            self.active_keys.add(k)
        else:
            self.active_keys.discard(k)
        self._apply_motion()

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

        self._apply_drive(px)
        self._update_camera(px)

    def tick(self) -> None:
        """Call periodically to keep the camera moving while keys are held."""
        px = self._require_px(log=False)
        if px is None:
            return
        self._update_camera(px)

    def _require_px(self, *, log: bool = True):
        px = self.px
        if px is None and log:
            print(f"[CarController] active_keys={self.active_keys}")
        return px

    def _apply_drive(self, px) -> None:
        moving_forward = bool(self.active_keys & self.forward_keys)
        moving_back    = bool(self.active_keys & self.back_keys)
        turning_left   = bool(self.active_keys & self.left_keys)
        turning_right  = bool(self.active_keys & self.right_keys)

        # --- Drive direction ---
        if (not moving_forward and not moving_back) or (moving_forward and moving_back):
            px.stop()
        else:
            if moving_forward:
                px.forward(self.speed)
            elif moving_back:
                px.backward(self.speed)

        # --- Steering servo ---
        if turning_left and not turning_right:
            px.set_dir_servo_angle(-self.turn_angle)
        elif turning_right and not turning_left:
            px.set_dir_servo_angle(self.turn_angle)
        else:
            px.set_dir_servo_angle(0)

    def _update_camera(self, px) -> None:
        """Incrementally apply camera movement."""
        tilt_up = bool(self.active_keys & self.camera_up_keys)
        tilt_down = bool(self.active_keys & self.camera_down_keys)
        pan_right = bool(self.active_keys & self.camera_right_keys)
        pan_left = bool(self.active_keys & self.camera_left_keys)

        new_tilt = self._next_camera_angle(
            self.tilt_angle, positive=tilt_up, negative=tilt_down
        )
        new_pan = self._next_camera_angle(
            self.pan_angle, positive=pan_right, negative=pan_left
        )

        if new_tilt != self.tilt_angle:
            self.tilt_angle = new_tilt
            px.set_cam_tilt_angle(new_tilt)

        if new_pan != self.pan_angle:
            self.pan_angle = new_pan
            px.set_cam_pan_angle(new_pan)

    def _next_camera_angle(self, current: int, *, positive: bool, negative: bool) -> int:
        if positive and not negative:
            return self._clamp_camera_angle(current + self.camera_step)
        if negative and not positive:
            return self._clamp_camera_angle(current - self.camera_step)
        return current

    def _clamp_camera_angle(self, value: int) -> int:
        limit = self.camera_limit
        if value > limit:
            return limit
        if value < -limit:
            return -limit
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
