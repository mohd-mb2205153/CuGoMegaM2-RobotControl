"""
CuGoMEGA M2 - VR joystick teleop bridge server
================================================

Serves the WebXR page over HTTPS, and runs a secure WebSocket (WSS)
server that receives right-controller joystick data from the Quest 3
and drives the M2 over RS232.

CHANNEL MAPPING - IMPORTANT:
  Derived empirically from keyboard testing on the actual robot, this
  unit responds as:
      Channel 1 = LEFT motor, INVERTED
      Channel 2 = RIGHT motor, normal
  i.e. driving straight forward requires  !M -600 600
  This is the OPPOSITE channel assignment from the assembly manual's
  diagram, plus a polarity flip - most likely because the two crawler
  units are physically mirrored. If your unit behaves differently,
  flip CH1_SIGN / CH2_SIGN or swap CH1_IS_LEFT below.

SETUP:
  1. pip install pyserial websockets cryptography
  2. python generate_cert.py <your-pc-lan-ip>
       -> creates cert.pem / key.pem in this folder
  3. Set SERIAL_PORT below.
  4. Make sure webxr_joystick.html is in this same folder.
  5. Run: python vr_teleop_server.py
  6. On the Quest 3, same WiFi network, browser to
     https://<your-pc-lan-ip>:8443/webxr_joystick.html
     Accept the self-signed cert warning (Advanced -> Proceed).
  7. Tap "Enter VR" and move the right thumbstick. Center it to stop.

SAFETY:
  - Wheels OFF THE GROUND for your first session, always.
  - There is no grip-button dead-man's switch - centering the joystick
    is what stops the robot. Be deliberate about returning to center.
  - If no message arrives for STALE_TIMEOUT seconds (WiFi drop, headset
    removed, tab closed), the control loop commands zero speed. This
    exists BECAUSE the Keya driver has no documented watchdog of its
    own - don't treat it as your only safety net; keep a way to
    physically cut power within reach during testing.
  - Set DRY_RUN = True to test the VR/network pipeline with no robot.
"""

import asyncio
import json
import ssl
import time
import threading
import http.server
import serial
import websockets

SERIAL_PORT = "COM6"
BAUD_RATE = 115200
MAX_SPEED = 600              # keep below the 1000 max for headroom
DEADZONE = 0.12              # ignore small stick drift around center
STALE_TIMEOUT = 0.5          # seconds - zero the motors if input stops
CONTROL_HZ = 10              # how often we actually write to the serial port
HTTPS_PORT = 8443
WSS_PORT = 8765
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"
DRY_RUN = False
VERBOSE = True               # print every command + reply for debugging

# Channel mapping - see docstring. CH1_IS_LEFT=True means the first
# value in "!M a b" drives the LEFT motor.
CH1_IS_LEFT = True
CH1_SIGN = -1                # left motor is inverted on this unit
CH2_SIGN = 1


class M2Driver:
    """
    All serial access is serialized behind a lock. Without this, the
    control loop and any other caller can interleave writes mid-command
    and garble what the driver receives.
    """

    def __init__(self, port=SERIAL_PORT, baud=BAUD_RATE, timeout=0.15):
        self.ser = None if DRY_RUN else serial.Serial(port, baud, timeout=timeout)
        self._lock = threading.Lock()

    def _send(self, cmd: str) -> str:
        if DRY_RUN:
            if VERBOSE:
                print(f"[DRY RUN] {cmd!r}")
            return ""
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write((cmd + "\r").encode("ascii"))
            # read_until stops at the terminator instead of waiting for a
            # fixed byte count. The driver replies "+\r" (2 bytes), so
            # read(64) would block for the FULL timeout on every single
            # command - fine when typing by hand, fatal at 10-20Hz.
            reply = self.ser.read_until(b"\r")
        text = reply.decode("ascii", errors="replace")
        if VERBOSE:
            print(f"{cmd!r} -> {text!r}")
        return text

    def drive(self, left: int, right: int) -> str:
        if CH1_IS_LEFT:
            ch1, ch2 = left * CH1_SIGN, right * CH2_SIGN
        else:
            ch1, ch2 = right * CH1_SIGN, left * CH2_SIGN
        return self._send(f"!M {int(ch1)} {int(ch2)}")

    def stop(self) -> str:
        return self._send("!M 0 0")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def apply_deadzone(v: float) -> float:
    return 0.0 if abs(v) < DEADZONE else v


def mix_arcade(x: float, y: float):
    """Single-stick arcade mixing: forward/back + turn -> left/right wheel speed."""
    x = apply_deadzone(x)
    y = apply_deadzone(y)
    linear = -y * MAX_SPEED   # stick forward (negative y) -> positive speed
    angular = x * MAX_SPEED
    left = clamp(int(linear + angular), -1000, 1000)
    right = clamp(int(linear - angular), -1000, 1000)
    return left, right


class ControlState:
    """Latest-value-wins target, shared between the WS handler and the loop."""

    def __init__(self):
        self.left = 0
        self.right = 0
        self.last_msg_time = 0.0
        self.lock = threading.Lock()

    def set_target(self, left, right):
        with self.lock:
            self.left, self.right = left, right
            self.last_msg_time = time.time()

    def get_target(self):
        with self.lock:
            if time.time() - self.last_msg_time > STALE_TIMEOUT:
                return 0, 0
            return self.left, self.right


async def control_loop(driver: M2Driver, state: ControlState):
    """
    The ONLY thing that writes to the serial port.

    Incoming joystick messages just update the target; this loop sends
    the most recent one at a fixed, sane rate. That decoupling is the
    fix for the burst/pile-up problem: the browser can send at whatever
    rate it likes, and stale intermediate values are simply skipped
    rather than queued up behind a slow serial round-trip.
    """
    period = 1.0 / CONTROL_HZ
    last_sent = None
    while True:
        left, right = state.get_target()
        # Always resend zeros at least once after motion, then idle quietly
        # rather than spamming the port when nothing is happening.
        if (left, right) != (0, 0) or last_sent != (0, 0):
            await asyncio.to_thread(driver.drive, left, right)
            last_sent = (left, right)
        await asyncio.sleep(period)


async def ws_handler(websocket, state: ControlState):
    print("VR client connected.")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                x = float(data.get("x", 0))
                y = float(data.get("y", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            left, right = mix_arcade(x, y)
            state.set_target(left, right)
    finally:
        state.set_target(0, 0)
        print("VR client disconnected - target zeroed.")


def serve_https():
    handler = http.server.SimpleHTTPRequestHandler
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"HTTPS serving on :{HTTPS_PORT}")
    httpd.serve_forever()


async def main():
    driver = M2Driver()
    state = ControlState()
    print("DRY RUN - no serial will be sent." if DRY_RUN else f"Serial open on {SERIAL_PORT}.")

    threading.Thread(target=serve_https, daemon=True).start()
    asyncio.create_task(control_loop(driver, state))

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)

    async def handler(ws):
        await ws_handler(ws, state)

    async with websockets.serve(handler, "0.0.0.0", WSS_PORT, ssl=ssl_ctx):
        print(f"WSS serving on :{WSS_PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())