/*
 * CuGoMEGA M2 - ESP32 VR joystick teleop (all-in-one)
 * ===================================================
 *
 * Replaces the Windows laptop entirely. The ESP32:
 *   - joins your existing WiFi network (station mode)
 *   - serves the WebXR page over HTTPS on port 443
 *   - accepts joystick data over WSS at wss://<ip>/ws  (same port)
 *   - drives the M2 over RS232 from UART2
 *
 * ---------------------------------------------------------------
 * WIRING - READ THIS FIRST
 * ---------------------------------------------------------------
 * The ESP32's UART pins are 3.3V TTL. The M2's RS232 port uses true
 * RS232 voltage levels (+/-5..12V). You MUST put a level shifter
 * between them - a MAX3232-based module is the standard part.
 * Connecting ESP32 pins directly to RS232 will damage the ESP32.
 *
 *   ESP32 GPIO17 (TX2) --> MAX3232 TTL TX in
 *   ESP32 GPIO16 (RX2) <-- MAX3232 TTL RX out
 *   ESP32 GND          --- MAX3232 GND --- M2 GND
 *   MAX3232 RS232 side --> M2 RS-232C port (DB9)
 *
 * Power the MAX3232 from the ESP32's 3.3V rail.
 *
 * ---------------------------------------------------------------
 * CERTIFICATE - DO THIS BEFORE FLASHING
 * ---------------------------------------------------------------
 * 1. Decide the ESP32's static IP and set STATIC_IP below. It must be
 *    outside your router's DHCP pool but on the same subnet.
 * 2. On your PC run:  python generate_cert.py <that same IP>
 * 3. Open cert.pem and key.pem in a text editor and paste their full
 *    contents (including the BEGIN/END lines) into the two string
 *    literals further down.
 * The cert is tied to that IP, so if you change the IP you must
 * regenerate the cert and re-flash.
 *
 * ---------------------------------------------------------------
 * BOARD SETTINGS
 * ---------------------------------------------------------------
 * TLS on ESP32 is heap-hungry. In Arduino IDE, under Tools:
 *   Partition Scheme: "Huge APP (3MB No OTA/1MB SPIFFS)"
 * A board with PSRAM is helpful but not required. If the server fails
 * to start or the handshake drops, low heap is the usual cause.
 *
 * ---------------------------------------------------------------
 * SAFETY
 * ---------------------------------------------------------------
 *   - Wheels OFF THE GROUND for the first run, always.
 *   - Centering the joystick is what stops the robot; there is no
 *     grip-button dead-man's switch.
 *   - If joystick data stops arriving for STALE_TIMEOUT_MS (WiFi drop,
 *     headset removed, tab closed), the control loop commands zero.
 *     The Keya driver has no documented watchdog of its own, so keep a
 *     way to physically cut power within reach during testing.
 */

#include <WiFi.h>
#include <esp_https_server.h>
#include <esp_tls.h>

// ================= USER CONFIG =================

const char *WIFI_SSID = "TP-Link_FAF4_5G";
const char *WIFI_PASS = "27559710";

// Must match the IP you generated the certificate for.
IPAddress STATIC_IP(192, 168, 0, 200);
IPAddress GATEWAY(192, 168, 0, 1);
IPAddress SUBNET(255, 255, 255, 0);
IPAddress DNS1(8, 8, 8, 8);

// RS232 via MAX3232 on UART2
#define RS232_RX_PIN 16
#define RS232_TX_PIN 17
#define RS232_BAUD   115200

// Motion tuning
static const int   MAX_SPEED        = 600;   // driver max is 1000
static const float DEADZONE         = 0.12f; // ignore stick drift
static const int   CONTROL_HZ       = 10;    // serial writes per second
static const unsigned long STALE_TIMEOUT_MS = 500;
static const bool  VERBOSE          = true;  // echo commands to USB serial

// Channel mapping, derived from testing on the real robot:
//   Channel 1 = LEFT motor, INVERTED
//   Channel 2 = RIGHT motor, normal
// Forward therefore sends "!M -600 600".
static const int CH1_SIGN = -1;
static const int CH2_SIGN =  1;

// ============ PASTE YOUR CERTIFICATE HERE ============

const char server_cert_pem[] = R"EOF(
-----BEGIN CERTIFICATE-----
MIIC0TCCAbmgAwIBAgIUK6e3rMAIw9slVcEhMpJOfy/UW9IwDQYJKoZIhvcNAQEL
BQAwGDEWMBQGA1UEAwwNMTkyLjE2OC4wLjIwMDAeFw0yNjA4MjQwOTA1MjVaFw0y
NzA4MjQwOTA1MjVaMBgxFjAUBgNVBAMMDTE5Mi4xNjguMC4yMDAwggEiMA0GCSqG
SIb3DQEBAQUAA4IBDwAwggEKAoIBAQCc010Y6/ApLLlXEXshSPKPjw5fesf+Qotw
hZbUe6CyIbSLtANh6woiFUJtODAoJzXgjZmwBUn9TMh8MaCiJiWQiR0QSPcG8PFV
ECst7UIw5WJZbidM0i3571zdsy7P6V6bjCk/Y1pQvCwXIwa3wr3XcdjC2SkhfOqh
VmNHlDgXCHfRuULxEVzck61SmIA6Zwhar5Jbk0hpd9uIC7rZPkEPCs94zULHCu1k
ohp+FAyy66wgkms3hcDnt1O1Cx1DOT6JpN5qJ3kh66TVUP2GFjY1mUqljOkO0HZS
yNZUMb28aGzFXrxKiWoMWvI+/yTk/tqqji8qTmKyhonjpTU+5TujAgMBAAGjEzAR
MA8GA1UdEQQIMAaHBMCoAMgwDQYJKoZIhvcNAQELBQADggEBAAjs1+nrzQ/SqfBi
mYE2Uo/mJxUh0TBrYUCJUweinYGMr64yic6HXvg8smr8nbn3D5npspeXE+WtrGIE
dYTpUuVPEtKv4hw9vsYe0qjVNnrAi2974M64Og87K6+yO60KgRft5d9VAWEglGyZ
MorFsh9JNNF2eqHclD8WpkDJzwHzipe/PpRKo4EkAGaoE0TJeL4auVEsAnjm1fvR
D7JVPGPS17ghOCZWUGf7jcB39XxKkiP9fL9hPzCB+FdijKtOf+vDWuaAZyYZIADs
tetuzuKR3ujsxxzwN9X+9B+VFNjBKNGMVffaaUdL+I+AoFc3tvwhME3UUcR2KVJB
Miw8u2w=
-----END CERTIFICATE-----
)EOF";

const char server_key_pem[] = R"EOF(
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAnNNdGOvwKSy5VxF7IUjyj48OX3rH/kKLcIWW1HugsiG0i7QD
YesKIhVCbTgwKCc14I2ZsAVJ/UzIfDGgoiYlkIkdEEj3BvDxVRArLe1CMOViWW4n
TNIt+e9c3bMuz+lem4wpP2NaULwsFyMGt8K913HYwtkpIXzqoVZjR5Q4Fwh30blC
8RFc3JOtUpiAOmcIWq+SW5NIaXfbiAu62T5BDwrPeM1CxwrtZKIafhQMsuusIJJr
N4XA57dTtQsdQzk+iaTeaid5Ieuk1VD9hhY2NZlKpYzpDtB2UsjWVDG9vGhsxV68
SolqDFryPv8k5P7aqo4vKk5isoaJ46U1PuU7owIDAQABAoIBAAvzR0rY38ojcFQk
Lt/QcTtjSVMZRhgn9fwzEdVLPmmUi++BXiieAn2qZQ9xkqncowxjfeyd2o+ExFpC
Zd01TvN+n0pYZQqQXbN/seqkA8E6GY57CF+gPISpKshyGQUa4Wy094evCHjSfgGd
V6u1GUZLlJr0dV/p5u84aARSVRvcGMN8KTmlbIbpgcwONpHObtpAWOWlYxLNghPc
xWkSXfZpOlJCJOeSMwcwRLvppvDHkscoGlx+7IJIZ1BFt38DyZF4pBd1nZfxQIR+
3vEpCRlo4kokJQ6vy0m3UWz5Isd7szueSNRy776MlZh5AV26xQlOF1lABRGOWmts
3hFDQ1ECgYEA0deH05VaJ5IRghpDIBvqLm1Q3xG1ux6z4ri7AuyRR8azetwXDZFN
eaVgMYqM/rAqBeeYfcVr7BTr7DkGkYefVQKwu5+Y7hyZwgDXqx4YkAj59HkUE2in
F0Sw474mplzYdbe6pcjinWu4T9CIJ0gh/9ziyFmzQt/bKn0P/mdI6k0CgYEAv1Jr
BDtI/K5dOWQB/gDo4HQgTra69vvLADlH1hMH29GO9oW5BNVqEfi0152X7WLljhec
c4PfwHZFoeNO4wuA3eCmjGKCzSu5ACocq39DwvXgP8VqAoLz2wfO/sV7kl6DNypF
Bq4olWTY9ts1/9Sg1udYUw/K4jpzznHLX1UH1a8CgYB1JBVd5w0J8/+0GkcIoKyt
ODciH7fMeoo+8ZLsQfWkFOdSmZSA7XFLjCdT4J1u/BapbyzwYQorI07Ect0Y1pX6
leLlCmYL3olzBJdgng9mMKygbgrn/s7wLVd1+0uGKWRo6qTWMXtYF68vVyD6lMju
FXfAElsA5QhrAp+wDCZnLQKBgBpQhbOhS9qlSOE55iQ/j8g/cKoi6/hIjZVMS5sg
JvaPDjDOF7KYf+xU3trBLEJUVeqDSNuCieX43n7zusfzrxfVbFLmwcLifqGNKUBV
Usaf9uYOixQpWs0Hd+sG0oZBRZ7yy2et0JsrscPSRs0XO8ATNczG4UrYa1E7yZMl
KNy1AoGBAL+mHB3IkEyHp1OqK2+Lr/NafdwWCMpQ8iFwWcB1surX28UO1OLVQ39y
rx8MIYF385VLSbR1mN3G6xqRzBcVdT7lMVzLn2Jg2nJ5j3lEbJYxx720ISwEHyo9
PH5w6PqlQL/FqfSXKG5uqhEST18gmKyVaT8w6dumTBHSspSRe6To
-----END RSA PRIVATE KEY-----
)EOF";

// ================= WEB PAGE =================
// Sends "x,y" as plain text so the ESP32 needs no JSON parser.

const char INDEX_HTML[] = R"HTMLEOF(<!doctype html>
<html><head><meta charset="utf-8"><title>M2 VR Control</title>
<style>
body{background:#111;color:#eee;font-family:system-ui,sans-serif;text-align:center;padding-top:4em}
button{font-size:1.5em;padding:.6em 1.4em;border-radius:8px;border:none;background:#2e8b57;color:#fff}
#s{margin-top:2em;font-size:1.1em;white-space:pre-line}
.ok{color:#6f6}.bad{color:#f66}
</style></head><body>
<h1>M2 VR Joystick Control</h1>
<button id="go">Enter VR</button>
<div id="s">Not connected yet.</div>
<script>
const se=document.getElementById('s');
let ws=null,last=0;const IVL=50;
function log(m,c){se.textContent=m;se.className=c||''}
function conn(){
  ws=new WebSocket('wss://'+location.host+'/ws');
  ws.onopen=()=>log('Connected. Tap Enter VR.','ok');
  ws.onclose=()=>log('Disconnected.','bad');
  ws.onerror=()=>log('WebSocket error.','bad');
}
function send(x,y){if(ws&&ws.readyState===1)ws.send(x.toFixed(3)+','+y.toFixed(3))}
async function enter(){
  if(!navigator.xr){log('WebXR unavailable. Use the Quest Browser over HTTPS.','bad');return}
  if(!await navigator.xr.isSessionSupported('immersive-vr')){log('immersive-vr unsupported.','bad');return}
  const s=await navigator.xr.requestSession('immersive-vr');
  const gl=document.createElement('canvas').getContext('webgl',{xrCompatible:true});
  await gl.makeXRCompatible();
  s.updateRenderState({baseLayer:new XRWebGLLayer(s,gl)});
  await s.requestReferenceSpace('local');
  s.addEventListener('end',()=>{log('Session ended - stopping.','bad');send(0,0)});
  s.requestAnimationFrame(function f(t,fr){
    s.requestAnimationFrame(f);
    let x=0,y=0;
    for(const src of fr.session.inputSources){
      if(src.handedness==='right'&&src.gamepad){
        const a=src.gamepad.axes;
        x=a.length>=4?a[2]:(a[0]||0);
        y=a.length>=4?a[3]:(a[1]||0);
      }
    }
    const n=performance.now();
    if(n-last>IVL){send(x,y);last=n}
  });
  log('VR active.\nMove the right thumbstick to drive.\nCenter it to stop.','ok');
}
document.getElementById('go').addEventListener('click',async()=>{conn();await enter()});
</script></body></html>)HTMLEOF";

// ================= SHARED STATE =================

volatile int   g_targetLeft  = 0;
volatile int   g_targetRight = 0;
volatile unsigned long g_lastMsgMs = 0;

portMUX_TYPE g_mux = portMUX_INITIALIZER_UNLOCKED;

static inline void setTarget(int l, int r) {
  portENTER_CRITICAL(&g_mux);
  g_targetLeft = l;
  g_targetRight = r;
  g_lastMsgMs = millis();
  portEXIT_CRITICAL(&g_mux);
}

static inline void getTarget(int &l, int &r) {
  portENTER_CRITICAL(&g_mux);
  bool stale = (millis() - g_lastMsgMs) > STALE_TIMEOUT_MS;
  l = stale ? 0 : g_targetLeft;
  r = stale ? 0 : g_targetRight;
  portEXIT_CRITICAL(&g_mux);
}

// ================= MOTOR CONTROL =================

static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

static float deadzone(float v) { return fabsf(v) < DEADZONE ? 0.0f : v; }

static void mixArcade(float x, float y, int &left, int &right) {
  x = deadzone(x);
  y = deadzone(y);
  float linear  = -y * MAX_SPEED;   // stick forward (negative y) = forward
  float angular =  x * MAX_SPEED;
  left  = clampi((int)(linear + angular), -1000, 1000);
  right = clampi((int)(linear - angular), -1000, 1000);
}

static void sendDrive(int left, int right) {
  int ch1 = left  * CH1_SIGN;
  int ch2 = right * CH2_SIGN;
  char cmd[32];
  snprintf(cmd, sizeof(cmd), "!M %d %d\r", ch1, ch2);
  Serial2.print(cmd);
  // Driver replies "+\r" on success, "-\r" if it rejected the command.
  String reply = Serial2.readStringUntil('\r');
  if (VERBOSE) {
    Serial.printf("%s -> %s\n", cmd, reply.c_str());
  }
}

// ================= WEBSOCKET HANDLER =================

static esp_err_t ws_handler(httpd_req_t *req) {
  if (req->method == HTTP_GET) {
    // Opening handshake; nothing to do.
    return ESP_OK;
  }

  httpd_ws_frame_t frame;
  memset(&frame, 0, sizeof(frame));
  frame.type = HTTPD_WS_TYPE_TEXT;

  // First call with len=0 tells us how big the payload is.
  esp_err_t ret = httpd_ws_recv_frame(req, &frame, 0);
  if (ret != ESP_OK || frame.len == 0 || frame.len > 63) {
    return ret;
  }

  uint8_t buf[64] = {0};
  frame.payload = buf;
  ret = httpd_ws_recv_frame(req, &frame, frame.len);
  if (ret != ESP_OK) {
    return ret;
  }

  float x = 0, y = 0;
  if (sscanf((const char *)buf, "%f,%f", &x, &y) == 2) {
    int l, r;
    mixArcade(x, y, l, r);
    setTarget(l, r);
  }
  return ESP_OK;
}

static esp_err_t root_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static httpd_handle_t start_https_server() {
  httpd_ssl_config_t conf = HTTPD_SSL_CONFIG_DEFAULT();

  // Field names differ across ESP-IDF versions. If this block fails to
  // compile, your core uses the older names - swap servercert* for
  // cacert_pem / cacert_len.
  conf.servercert     = (const uint8_t *)server_cert_pem;
  conf.servercert_len = strlen(server_cert_pem) + 1;
  conf.prvtkey_pem    = (const uint8_t *)server_key_pem;
  conf.prvtkey_len    = strlen(server_key_pem) + 1;

  conf.httpd.max_open_sockets = 4;
  conf.httpd.stack_size       = 10240;

  httpd_handle_t server = NULL;
  esp_err_t ret = httpd_ssl_start(&server, &conf);
  if (ret != ESP_OK) {
    Serial.printf("HTTPS server failed to start: %s\n", esp_err_to_name(ret));
    Serial.println("Most common cause: not enough free heap, or a malformed certificate.");
    return NULL;
  }

  httpd_uri_t root_uri = {};
  root_uri.uri      = "/";
  root_uri.method   = HTTP_GET;
  root_uri.handler  = root_handler;
  httpd_register_uri_handler(server, &root_uri);

  httpd_uri_t ws_uri = {};
  ws_uri.uri          = "/ws";
  ws_uri.method       = HTTP_GET;
  ws_uri.handler      = ws_handler;
  ws_uri.is_websocket = true;
  httpd_register_uri_handler(server, &ws_uri);

  return server;
}

// ================= SETUP / LOOP =================

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\nCuGoMEGA M2 ESP32 teleop starting...");

  Serial2.begin(RS232_BAUD, SERIAL_8N1, RS232_RX_PIN, RS232_TX_PIN);
  Serial2.setTimeout(50);   // don't stall waiting for a reply

  if (!WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS1)) {
    Serial.println("Static IP config failed - check the addresses above.");
  }
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected. Open this in the Quest Browser:  https://");
  Serial.println(WiFi.localIP());
  Serial.println("(Accept the self-signed certificate warning once.)");

  if (start_https_server() != NULL) {
    Serial.println("HTTPS + WSS server running on port 443.");
  }

  // Make sure we start from a known stopped state.
  sendDrive(0, 0);
}

void loop() {
  static unsigned long lastSend = 0;
  static int lastL = 0, lastR = 0;
  static bool everSent = false;

  const unsigned long period = 1000UL / CONTROL_HZ;
  if (millis() - lastSend >= period) {
    lastSend = millis();

    int l, r;
    getTarget(l, r);

    // Send whenever we're moving, and once more when we return to zero,
    // rather than spamming the port while idle.
    if (l != 0 || r != 0 || !everSent || lastL != 0 || lastR != 0) {
      sendDrive(l, r);
      lastL = l;
      lastR = r;
      everSent = true;
    }
  }
}
