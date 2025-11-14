from picarx import Picarx
from time import sleep
import json
import socket
import threading
import time

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

DEBUG_TRACE = True
REMOTE_BIND_HOST = "0.0.0.0"
REMOTE_PORT = 8765


def debug(msg):
    if DEBUG_TRACE:
        print(f"[debug] {msg}")


def reset_keys(state, lock):
    with lock:
        for key in state:
            state[key] = False


def start_remote_key_server(key_state, lock):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((REMOTE_BIND_HOST, REMOTE_PORT))
    server.listen(1)
    stop_event = threading.Event()

    def handle_client(conn, addr):
        debug(f"Client connected from {addr}")
        reset_keys(key_state, lock)
        with conn:
            stream = conn.makefile("r")
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    debug(f"Invalid payload: {line}")
                    continue
                key_name = (payload.get("key") or "").lower()
                state = payload.get("state")
                if key_name not in key_state:
                    continue
                desired = state == "down"
                with lock:
                    key_state[key_name] = desired
                debug(f"Remote key {key_name} {'down' if desired else 'up'}")
        debug(f"Client {addr} disconnected; clearing key state")
        reset_keys(key_state, lock)

    def accept_loop():
        debug(f"Listening for remote keys on {REMOTE_BIND_HOST}:{REMOTE_PORT}")
        while not stop_event.is_set():
            try:
                server.settimeout(0.5)
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    return stop_event, server


def show_info():
    print("\033[H\033[J", end="")  # clear terminal windows
    print(manual)


def snapshot(state, lock):
    with lock:
        return state.copy()


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

    px = None
    key_state = {key: False for key in CONTROL_KEYS}
    key_lock = threading.Lock()
    stop_event = None
    server_socket = None

    try:
        stop_event, server_socket = start_remote_key_server(key_state, key_lock)
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
            key_snapshot = snapshot(key_state, key_lock)
            desired_motion = "stop"
            if key_snapshot["w"] and not key_snapshot["s"]:
                desired_motion = "forward"
            elif key_snapshot["s"] and not key_snapshot["w"]:
                desired_motion = "backward"

            if desired_motion != current_motion:
                if desired_motion == "forward":
                    px.forward(DRIVE_SPEED)
                elif desired_motion == "backward":
                    px.backward(DRIVE_SPEED)
                else:
                    px.stop()
                debug(f"Motion change: {current_motion} -> {desired_motion}")
                current_motion = desired_motion

            if now - last_steer_update >= STEER_UPDATE_INTERVAL:
                desired_dir_angle = current_dir_angle
                if key_snapshot["a"] and not key_snapshot["d"]:
                    desired_dir_angle = max(
                        desired_dir_angle - STEER_ANGLE_STEP, -STEER_ANGLE_LIMIT
                    )
                elif key_snapshot["d"] and not key_snapshot["a"]:
                    desired_dir_angle = min(
                        desired_dir_angle + STEER_ANGLE_STEP, STEER_ANGLE_LIMIT
                    )

                if desired_dir_angle != current_dir_angle:
                    px.set_dir_servo_angle(desired_dir_angle)
                    debug(f"Steering angle: {current_dir_angle} -> {desired_dir_angle}")
                    current_dir_angle = desired_dir_angle

                last_steer_update = now

            if now - last_camera_update >= CAMERA_INTERVAL:
                new_tilt = tilt_angle
                new_pan = pan_angle

                if key_snapshot["i"] and not key_snapshot["k"]:
                    new_tilt = min(tilt_angle + CAMERA_STEP, CAMERA_LIMIT)
                elif key_snapshot["k"] and not key_snapshot["i"]:
                    new_tilt = max(tilt_angle - CAMERA_STEP, -CAMERA_LIMIT)

                if key_snapshot["l"] and not key_snapshot["j"]:
                    new_pan = min(pan_angle + CAMERA_STEP, CAMERA_LIMIT)
                elif key_snapshot["j"] and not key_snapshot["l"]:
                    new_pan = max(pan_angle - CAMERA_STEP, -CAMERA_LIMIT)

                camera_changed = False
                if new_tilt != tilt_angle:
                    tilt_angle = new_tilt
                    px.set_cam_tilt_angle(tilt_angle)
                    debug(f"Tilt angle -> {tilt_angle}")
                    camera_changed = True

                if new_pan != pan_angle:
                    pan_angle = new_pan
                    px.set_cam_pan_angle(pan_angle)
                    debug(f"Pan angle -> {pan_angle}")
                    camera_changed = True

                if camera_changed:
                    last_camera_update = now

            sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        print("\n Quit")
    finally:
        if stop_event is not None:
            stop_event.set()
        if server_socket is not None:
            server_socket.close()
        if px is not None:
            px.set_cam_tilt_angle(0)
            px.set_cam_pan_angle(0)
            px.set_dir_servo_angle(0)
            px.stop()
            sleep(0.2)
