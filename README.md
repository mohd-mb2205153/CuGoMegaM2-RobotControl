# CuGoMEGA M2 — VR Joystick Teleoperation

Control a CuboRex CuGoMEGA M2 tracked robot from a Meta Quest 3 controller, over WiFi, without the supplied RC transmitter.

A Raspberry Pi (or any Linux/Windows machine) connects to the robot's motor driver over RS232 and serves a WebXR page. The Quest opens that page in its browser, reads the right thumbstick, and streams joystick values back over a WebSocket. The server mixes them into left/right track speeds and sends them to the driver.

```
Quest 3  ──WiFi/WSS──►  Raspberry Pi  ──RS232──►  Keya KYDBL4850-2E  ──►  Robot motors
```

## Contents

| File | Purpose |
|---|---|
| `vr_teleop_server.py` | Main server — HTTPS page, WebSocket, serial control loop |
| `webxr_joystick.html` | WebXR page loaded by the Quest browser |
| `generate_cert.py` | Creates the self-signed certificate WebXR requires |
| `m2_local_test.py` | Keyboard driving test, no headset needed |
| `m2-teleop.service` | systemd unit for starting the server on boot |

## Hardware

- CuGoMEGA M2 with its Keya **KYDBL4850-2E** dual-channel BLDC driver
- Raspberry Pi 4 (or any machine with Python 3)
- **A genuine USB-to-RS232 adapter**, not USB-to-TTL. Other cables might not work. https://www.unitek-products.com/products/usb-to-serial-adapter
- Meta Quest 3 on the same WiFi network

Connect the adapter to the **RS-232C DB9 port on the green interface board** inside the M2's electrical enclosure.

## One-time robot setup

The driver arbitrates between input sources by priority. Out of the box it may be listening to the RC receiver.

1. Connect the driver to a Windows PC and open `KeyaMotorMonitor.exe`.
2. **Save the factory configuration first** — Read from controller → Save to file. Keep this backup.
3. Go to **Other → Run item** and set **Priority 1 = RS232**.
4. Click **Save to controller**.

## Install

On Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y python3-serial python3-websockets python3-cryptography
sudo usermod -a -G dialout $USER
sudo reboot
```

The `dialout` group is required to open the serial port. The reboot is what makes it take effect.

Find your serial port after plugging in the adapter:

```bash
ls /dev/ttyUSB*
```

## Configure

Give the machine a **static IP** — the certificate is bound to one address and breaks if DHCP changes it. Then edit `vr_teleop_server.py`:

```python
SERIAL_PORT = "/dev/ttyUSB0"   # or "COM6" on Windows
MAX_SPEED   = 600              # driver maximum is 1000
```

Generate the certificate for that static IP:

```bash
python3 generate_cert.py 192.168.1.201
```

This writes `cert.pem` and `key.pem` into the current folder. Keep all files in one directory.

## Run

```bash
python3 vr_teleop_server.py
```

On the Quest 3, joined to the same network, open:

```
https://192.168.1.201:8443/webxr_joystick.html
```

Accept the "not private" warning — expected for a self-signed certificate — then tap **Enter VR**. The right thumbstick drives; centering it stops.

**Put the tracks on blocks for the first run.**

## Start on boot

Edit `m2-teleop.service` so `User`, `WorkingDirectory` and `ExecStart` match your setup (`whoami`, `pwd`, `which python3`), then:

```bash
sudo cp m2-teleop.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable m2-teleop.service
sudo systemctl start m2-teleop.service
```

Check it and watch live output:

```bash
systemctl status m2-teleop.service
journalctl -u m2-teleop.service -f
```

## Keyboard test

To verify the serial link without the headset:

```bash
python3 m2_local_test.py
```

`w`/`s`/`a`/`d` to drive, `x` to stop, `e`/`g` for emergency stop and release, `+`/`-` for speed, `v` to read battery volts, `q` to quit.

## Protocol notes

The driver speaks ASCII over **115200 8N1**, commands terminated with `\r`. It replies `+` on success and `-` if a command was rejected.

| Command | Meaning |
|---|---|
| `!M nn mm` | Set speed, channel 1 and channel 2, range ±1000 |
| `!EX` | Emergency stop (latches) |
| `!MG` | Release emergency stop |
| `?V` | Read voltages |
| `?S` | Read encoder speed in RPM |

**Channel mapping.** On this robot, channel 1 is the **left** motor **inverted** and channel 2 is the **right** motor. Driving straight forward sends `!M -600 600`. This is the opposite of the assembly manual's diagram plus a polarity flip, most likely because the two crawler units are mirrored. Verify on your own machine before trusting it — the signs are exposed as `CH1_SIGN` / `CH2_SIGN` at the top of the server.

## Troubleshooting

**`Permission denied` on the serial port** — not in the `dialout` group, or added but not yet rebooted.

**Empty reply to every command** — nothing is coming back over RS232. Check the adapter is genuine RS232, that the M2 is powered with the emergency stop released, and that Priority 1 is set to RS232.

**`-` replies** — the driver received the command but rejected it. Check the value range and command syntax.

**Quest browser refuses to enter VR** — WebXR requires HTTPS. Confirm you used `https://` and accepted the certificate warning.

**Certificate warning won't go away / connection refused** — the certificate was generated for a different IP than the machine currently has.

**Service shows `inactive (dead)` after boot** — the `[Install]` section is missing or malformed, so no boot symlink was created. Verify with `ls -l /etc/systemd/system/multi-user.target.wants/ | grep m2`.

**Service restart-loops with `status=1`** — read the traceback with `journalctl -u m2-teleop.service -n 50`. Usually a wrong `WorkingDirectory` (certificate not found) or a serial permission problem.
