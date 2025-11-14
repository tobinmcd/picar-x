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

    speed: int = 20         # tune this
    turn_angle: int = 35    # steering servo angle
    active_keys: Set[str] = field(default_factory=set)

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
        px = self.px
        if px is None:
            # Dev mode: just log
            print(f"[CarController] active_keys={self.active_keys}")
            return

        # Allow both WASD and arrow keys
        forward_keys = {"w", "arrowup"}
        back_keys    = {"s", "arrowdown"}
        left_keys    = {"a", "arrowleft"}
        right_keys   = {"d", "arrowright"}

        moving_forward = bool(self.active_keys & forward_keys)
        moving_back    = bool(self.active_keys & back_keys)
        turning_left   = bool(self.active_keys & left_keys)
        turning_right  = bool(self.active_keys & right_keys)

        # --- Drive direction ---

        # If no movement keys, or conflicting (forward+back), then stop.
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

        # If you had i/j/k/l controlling the camera in vroomvroomcar.py,
        # you can add that here too (e.g. pan/tilt based on extra keys).

    def shutdown(self) -> None:
        """Reset the robot to a safe neutral state."""
        if self.px is not None:
            self.px.set_cam_tilt_angle(0)
            self.px.set_cam_pan_angle(0)
            self.px.set_dir_servo_angle(0)
            self.px.stop()
