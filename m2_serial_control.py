"""
CuGoMEGA M2 - RS232 motor driver control skeleton
==================================================

Driver: Keya KYDBL4850-2E dual-channel BLDC controller.
Protocol confirmed from CuboRex/Keya's official manuals ("Serial Port RS232
Protocol.pdf" and "KYDBL4850-2E_manual.pdf") - no longer inferred.

Confirmed serial settings: 115200 baud, 8 data bits, 1 stop bit, no parity.
Commands are ASCII, terminated with \\r, and not case-sensitive.

Confirmed acknowledgement behaviour:
  - Commands that produce no reply (e.g. a speed command) get back "+\\r"
    on success.
  - Any rejected/unrecognised command gets back "-\\r".
  - Queries get back "KEY=value\\r" (e.g. "V=135:246:4730").

BEFORE THIS WILL WORK ON THE ROBOT:
  The driver's "Priority 1" signal source must be set to RS232 using the
  KeyaMotorMonitor tool (one-time RS232 connection from a Windows PC),
  otherwise it will keep listening to the RC receiver instead of you.
  Do this, and save to controller, before wiring up your ESP32/RPi.

Test order, wheels OFF THE GROUND first:
  1. read_firmware_id() or read_volts() - confirms comms are alive and the
     reply format matches what's expected here.
  2. drive() with a small value (e.g. +/-50) - confirm direction/behaviour
     before scaling up.

Hardware chain: your ESP32/RPi UART (3.3V TTL) --> MAX3232-type level
shifter --> M2's DB25 control connector, pins 2 (Tx), 3 (Rx), 5 (GND).
Do not connect UART pins directly to RS232 - the voltage levels are
incompatible and will damage something.
"""

import serial
import threading
import time

BAUD_RATE = 115200          # Confirmed in Keya's RS232 Protocol manual
SERIAL_PORT = "COM3"  # or /dev/serial0 (for linux), COM3 (for windows), etc.
WATCHDOG_INTERVAL = 0.2     # seconds between repeated drive commands


class M2Driver:
    def __init__(self, port=SERIAL_PORT, baud=BAUD_RATE, timeout=0.5):
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self._lock = threading.Lock()

    def _send(self, cmd: str) -> str:
        """Send a raw command string (without \\r) and return the raw reply."""
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write((cmd + "\r").encode("ascii"))
            time.sleep(0.02)
            reply = self.ser.read(64)
        return reply.decode("ascii", errors="replace")

    def read_firmware_id(self) -> str:
        """Harmless first test - confirms serial comms are alive."""
        return self._send("?FID")

    def drive(self, left: int, right: int):
        """
        Send a combined speed command to both channels in one line.
        left/right: signed values, 0 to 1000 = forward, 0 to -1000 = reverse
        (confirmed range, per Keya's RS232 Protocol manual).
        Still start with very small numbers (e.g. +/-50) on your first test.
        """
        self._send(f"!M {left} {right}")

    def stop(self):
        self._send("!M 0 0")

    def estop(self):
        self._send("!EX")

    def release_estop(self):
        self._send("!MG")

    def read_volts(self) -> str:
        return self._send("?V")

    def read_amps(self, channel: int) -> str:
        return self._send(f"?A {channel}")


class DriveWatchdog:
    """
    Motor controllers like this one are expected to stop the motors if no
    command arrives for a while (a serial watchdog timeout). That's a
    genuine safety feature for a WiFi-controlled robot: if the WiFi link
    drops, you WANT the driver to stop the motors on its own rather than
    keep coasting on the last command. This class just re-sends the
    current target speed on a steady interval so the watchdog never trips
    during normal use. Confirm the actual timeout value/behaviour on your
    hardware via KeyaMotorMonitor or by testing (unplug the serial cable
    mid-drive, wheels off the ground, and see how quickly it stops).
    """
    def __init__(self, driver: M2Driver):
        self.driver = driver
        self.left = 0
        self.right = 0
        self._running = False
        self._thread = None

    def set_target(self, left: int, right: int):
        self.left, self.right = left, right

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.driver.stop()

    def _loop(self):
        while self._running:
            self.driver.drive(self.left, self.right)
            time.sleep(WATCHDOG_INTERVAL)


# --- Example WiFi bridge (very minimal TCP server) --------------------
# Run this on the RPi/ESP32 that's wired to the M2's RS232 port.
# From your phone/laptop on the same WiFi network, send lines like:
#   L:200,R:200      (drive forward)
#   L:0,R:0           (stop)
#   ESTOP             (emergency stop)
if __name__ == "__main__":
    import socket

    driver = M2Driver()
    print("Firmware ID reply:", driver.read_firmware_id())

    watchdog = DriveWatchdog(driver)
    watchdog.start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 5000))
    srv.listen(1)
    print("Listening on TCP 5000...")

    try:
        while True:
            conn, addr = srv.accept()
            print("Connected:", addr)
            with conn:
                buf = ""
                while True:
                    data = conn.recv(64)
                    if not data:
                        break
                    buf += data.decode("ascii", errors="ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line == "ESTOP":
                            driver.estop()
                        elif line.startswith("L:") and ",R:" in line:
                            l_str, r_str = line.split(",R:")
                            l_val = int(l_str[2:])
                            r_val = int(r_str)
                            watchdog.set_target(l_val, r_val)
            # WiFi client disconnected - stop driving for safety
            watchdog.set_target(0, 0)
    except KeyboardInterrupt:
        pass
    finally:
        watchdog.stop()
        driver.estop()
