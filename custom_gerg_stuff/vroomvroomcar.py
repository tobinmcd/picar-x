from picarx import Picarx
from time import sleep
import time

try:
    import keyboard
except ImportError as exc:
    raise SystemExit(
        "The 'keyboard' package is required for non-blocking key tracking. "
        "Install it with 'pip install keyboard' (use sudo on the Pi if needed)."
    ) from exc

manual = """
Press keys on keyboard to control PiCar-X!
    w: Forward
    a: Turn left
    s: Backward
    d: Turn right
    i: Head up
    k: Head down
    j: Turn head left
    l: Turn head right
    ctrl+c: Press twice to exit the program
"""


def show_info():
    print("\033[H\033[J", end="")  # clear terminal windows
    print(manual)


if __name__ == "__main__":
    CONTROL_KEYS = ("w", "a", "s", "d", "i", "k", "j", "l")
    DRIVE_SPEED = 80
    STEER_ANGLE_LIMIT = 30
    STEER_ANGLE_STEP = 2
    STEER_UPDATE_INTERVAL = 0.1
    CAMERA_STEP = 2
    CAMERA_INTERVAL = 0.1
    CAMERA_LIMIT = 30
    LOOP_INTERVAL = 0.05

    def handle_key_event(event, key_state):
        key_name = (event.name or "").lower()
        if key_name in key_state:
            key_state[key_name] = event.event_type == "down"

    px = None
    key_state = {key: False for key in CONTROL_KEYS}
    hook = keyboard.hook(lambda event: handle_key_event(event, key_state))

    try:
        px = Picarx()
        pan_angle = 0
        tilt_angle = 0
        current_motion = "stop"
        current_dir_angle = 0
        last_camera_update = 0.0
        last_steer_update = 0.0
        show_info()

        while True:
            now = time.time()
            desired_motion = "stop"
            if key_state["w"] and not key_state["s"]:
                desired_motion = "forward"
            elif key_state["s"] and not key_state["w"]:
                desired_motion = "backward"

            if desired_motion != current_motion:
                if desired_motion == "forward":
                    px.forward(DRIVE_SPEED)
                elif desired_motion == "backward":
                    px.backward(DRIVE_SPEED)
                else:
                    px.stop()
                current_motion = desired_motion

            if now - last_steer_update >= STEER_UPDATE_INTERVAL:
                desired_dir_angle = current_dir_angle
                if key_state["a"] and not key_state["d"]:
                    desired_dir_angle = max(
                        desired_dir_angle - STEER_ANGLE_STEP, -STEER_ANGLE_LIMIT
                    )
                elif key_state["d"] and not key_state["a"]:
                    desired_dir_angle = min(
                        desired_dir_angle + STEER_ANGLE_STEP, STEER_ANGLE_LIMIT
                    )

                if desired_dir_angle != current_dir_angle:
                    px.set_dir_servo_angle(desired_dir_angle)
                    current_dir_angle = desired_dir_angle

                last_steer_update = now

            if now - last_camera_update >= CAMERA_INTERVAL:
                new_tilt = tilt_angle
                new_pan = pan_angle

                if key_state["i"] and not key_state["k"]:
                    new_tilt = min(tilt_angle + CAMERA_STEP, CAMERA_LIMIT)
                elif key_state["k"] and not key_state["i"]:
                    new_tilt = max(tilt_angle - CAMERA_STEP, -CAMERA_LIMIT)

                if key_state["l"] and not key_state["j"]:
                    new_pan = min(pan_angle + CAMERA_STEP, CAMERA_LIMIT)
                elif key_state["j"] and not key_state["l"]:
                    new_pan = max(pan_angle - CAMERA_STEP, -CAMERA_LIMIT)

                camera_changed = False
                if new_tilt != tilt_angle:
                    tilt_angle = new_tilt
                    px.set_cam_tilt_angle(tilt_angle)
                    camera_changed = True

                if new_pan != pan_angle:
                    pan_angle = new_pan
                    px.set_cam_pan_angle(pan_angle)
                    camera_changed = True

                if camera_changed:
                    last_camera_update = now

            sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        print("\n Quit")
    finally:
        keyboard.unhook(hook)
        if px is not None:
            px.set_cam_tilt_angle(0)
            px.set_cam_pan_angle(0)
            px.set_dir_servo_angle(0)
            px.stop()
            sleep(0.2)
