"""
Generate a self-signed HTTPS certificate for local WebXR testing.

The Meta Quest Browser requires a secure context (HTTPS) before it will
allow WebXR at all. Since we're serving from a local IP address, not a
real domain, a self-signed certificate is the standard workaround - you
click through one "not private" warning in the Quest browser, once.

Usage:
    python generate_cert.py 192.168.1.42

Replace with your PC's actual LAN IP (run `ipconfig` on Windows, look
for IPv4 Address under your WiFi adapter).

Produces: cert.pem, key.pem  (used by vr_teleop_server.py)
Requires: pip install cryptography
"""

import sys
import datetime
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

if len(sys.argv) != 2:
    print("Usage: python generate_cert.py <your-pc-lan-ip>")
    sys.exit(1)

ip_str = sys.argv[1]
ip_addr = ipaddress.ip_address(ip_str)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ip_str)])
now = datetime.datetime.now(datetime.timezone.utc)

cert = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(
        x509.SubjectAlternativeName([x509.IPAddress(ip_addr)]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

with open("key.pem", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

with open("cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print(f"Wrote cert.pem and key.pem for {ip_str}")
print("Keep both files in the same folder as vr_teleop_server.py")
