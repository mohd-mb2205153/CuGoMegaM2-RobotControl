"""
CuGoMEGA M2 - Simple local keyboard test script (no WiFi/networking)
======================================================================

Run this directly on the PC/Pi that is physically wired via RS232 to the
M2. This is the simplest possible test: type a letter, press Enter, see
what the robot does. No WiFi bridge, no background threads.

IMPORTANT SAFETY NOTE:
  The official Keya manuals do NOT document any serial watchdog/timeout
  behaviour (unlike some other motor controller brands). That means if
  you send a drive command and then your script crashes, your serial
  cable comes loose, or you just walk away - the motors may keep running
  the LAST command you sent, indefinitely. There is no assumed auto-stop.
  Always explicitly stop the robot (the "x" command) before disconnecting
  or ending a session. Keep your hand near Enter+"x" at all times during
  testing.

SETUP:
  1. pip install pyserial --break-system-packages
  2. Set SERIAL_PORT below to your actual port (see m2_serial_control.py
     for how to find it).
  3. Confirm on the driver side that Priority 1 = RS232 has already been
     set and saved via KeyaMotorMonitor - otherwise it'll ignore you.
  4. Wheels OFF THE GROUND for your first run.

Commands (type the letter, press Enter):
  w        drive forward at current test speed
  s        drive backward
  a        turn left in place (wheels spin opposite directions)
  d        turn right in place
  x        stop  <-- your safety command, use it often
  e        emergency stop (latches - motor stays off until 'g')
  g        release emergency stop
  +        increase test speed
  -        decrease test speed
  v        read battery volts (sanity check the link is alive)
  q        stop and quit
"""

import serial
import time

SERIAL_PORT = "COM6"   # Linux/Mac example. On Windows, use "COM3"
                                # (check Device Manager > Ports (COM & LPT))
BAUD_RATE = 115200             # confirmed in Keya's RS232 Protocol manual
SPEED_STEP = 25
START_SPEED = 100              # deliberately conservative; range is 0-1000


class M2Driver:
    def __init__(self, port=SERIAL_PORT, baud=BAUD_RATE, timeout=0.5):
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def _send(self, cmd: str) -> str:
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii"))
        time.sleep(0.02)
        return self.ser.read(64).decode("ascii", errors="replace")

    def read_firmware_id(self) -> str:
        return self._send("?FID")

    def drive(self, left: int, right: int) -> str:
        # Per CuGoMEGA M2 assembly manual: Channel 1 (nn) = RIGHT motor,
        # Channel 2 (mm) = LEFT motor. Callers here think in left/right;
        # this swap is the only place that needs to know the wire order.
        return self._send(f"!M {right} {left}")

    def stop(self) -> str:
        return self._send("!M 0 0")

    def estop(self) -> str:
        return self._send("!EX")

    def release_estop(self) -> str:
        return self._send("!MG")

    def read_volts(self) -> str:
        return self._send("?V")


def main():
    speed = START_SPEED
    driver = M2Driver()

    print("Connecting...")
    reply = driver.read_firmware_id()
    print(f"Firmware ID reply: {reply!r}")
    if not reply.strip():
        print("WARNING: empty reply. Check wiring, baud rate, and that")
        print("Priority 1 = RS232 has been set and saved on the driver.")
    print(__doc__)

    try:
        while True:
            cmd = input(f"[speed={speed}] > ").strip().lower()

            if cmd == "a":
                print(driver.drive(speed, speed))
            elif cmd == "d":
                print(driver.drive(-speed, -speed))
            elif cmd == "s":
                print(driver.drive(-speed, speed))
            elif cmd == "w":
                print(driver.drive(speed, -speed))
            elif cmd == "x":
                print(driver.stop())
            elif cmd == "e":
                print(driver.estop())
                print("EMERGENCY STOP sent - send 'g' to release when safe.")
            elif cmd == "g":
                print(driver.release_estop())
            elif cmd == "+":
                speed = min(1000, speed + SPEED_STEP)
                print(f"Speed now {speed}")
            elif cmd == "-":
                speed = max(0, speed - SPEED_STEP)
                print(f"Speed now {speed}")
            elif cmd == "v":
                print(driver.read_volts())
            elif cmd == "q":
                driver.stop()
                print("Stopped. Exiting.")
                break
            else:
                print("Unknown command. w/s/a/d/x/e/g/+/-/v/q")
    except KeyboardInterrupt:
        driver.stop()
        print("\nInterrupted - sent stop. Exiting.")


if __name__ == "__main__":
    main()
