#!/usr/bin/env python3
"""
DarkSec-Chat for WiFi Pineapple Pager
Mesh networking + web bridge chat client using pagerctl LCD UI.

Controls:
  UP/DOWN      Scroll message history
  A (Green)    Open keyboard to send message
  B (Red)      Pause menu (brightness, info, exit)
  PWR          Exit

Dependencies: python3, python3-ctypes, pagerctl
HTTP transport: urllib.request with an automatic curl fallback
"""

import os, sys, json, time, socket, threading, shutil, subprocess, traceback
import base64, hashlib, hmac, secrets, struct
from datetime import datetime
from collections import deque
from urllib.parse import urlencode, urlsplit, urlunsplit

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "3.1.0"


def _rotl32(value, count):
    return ((value << count) & 0xffffffff) | (value >> (32 - count))


def _chacha20_block(key, counter, nonce):
    """RFC 8439 ChaCha20 block function using only the Python standard library."""
    constants = (0x61707865, 0x3320646e, 0x79622d32, 0x6b206574)
    state = list(constants + struct.unpack('<8I', key) +
                 (counter,) + struct.unpack('<3I', nonce))
    working = list(state)

    def quarter(a, b, c, d):
        working[a] = (working[a] + working[b]) & 0xffffffff
        working[d] = _rotl32(working[d] ^ working[a], 16)
        working[c] = (working[c] + working[d]) & 0xffffffff
        working[b] = _rotl32(working[b] ^ working[c], 12)
        working[a] = (working[a] + working[b]) & 0xffffffff
        working[d] = _rotl32(working[d] ^ working[a], 8)
        working[c] = (working[c] + working[d]) & 0xffffffff
        working[b] = _rotl32(working[b] ^ working[c], 7)

    for _ in range(10):
        quarter(0, 4, 8, 12); quarter(1, 5, 9, 13)
        quarter(2, 6, 10, 14); quarter(3, 7, 11, 15)
        quarter(0, 5, 10, 15); quarter(1, 6, 11, 12)
        quarter(2, 7, 8, 13); quarter(3, 4, 9, 14)
    return struct.pack('<16I', *(
        (working[i] + state[i]) & 0xffffffff for i in range(16)))


def _chacha20_xor(key, nonce, data):
    output = bytearray(len(data))
    for offset in range(0, len(data), 64):
        block = _chacha20_block(key, 1 + offset // 64, nonce)
        chunk = data[offset:offset + 64]
        for index, value in enumerate(chunk):
            output[offset + index] = value ^ block[index]
    return bytes(output)

PAGERCTL_SEARCH_DIRS = []
if len(sys.argv) >= 2 and not sys.argv[1].startswith("--"):
    PAGERCTL_SEARCH_DIRS.append(sys.argv[1])
PAGERCTL_SEARCH_DIRS += [
    os.path.join(SCRIPT_DIR, 'lib'),
    SCRIPT_DIR,
    "/root/payloads/user/utilities/PAGERCTL",
    "/mmc/root/payloads/user/utilities/PAGERCTL",
]

PAGERCTL_DIR = None
for d in PAGERCTL_SEARCH_DIRS:
    if (
        os.path.isfile(os.path.join(d, "pagerctl.py")) and
        os.path.isfile(os.path.join(d, "libpagerctl.so"))
    ):
        PAGERCTL_DIR = d
        break

if PAGERCTL_DIR is None:
    print("ERROR: pagerctl.py / libpagerctl.so not found")
    print("Searched:", PAGERCTL_SEARCH_DIRS)
    sys.exit(1)

os.environ["LD_LIBRARY_PATH"] = (
    PAGERCTL_DIR + ":/mmc/usr/lib:/mmc/lib:" +
    os.environ.get("LD_LIBRARY_PATH", "")
)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, PAGERCTL_DIR)

try:
    from pagerctl import Pager
except (ImportError, OSError) as e:
    print(f"ERROR: Failed to import pagerctl: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------
FONT_SEARCH_PATHS = [
    os.path.join(SCRIPT_DIR, 'fonts', 'DejaVuSansMono.ttf'),
    os.path.join(SCRIPT_DIR, 'fonts', 'DejaVuSans.ttf'),
    os.path.join(SCRIPT_DIR, '..', '..', 'reconnaissance', 'loki', 'resources', 'fonts', 'DejaVuSansMono.ttf'),
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/mmc/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/mmc/root/payloads/user/reconnaissance/loki/resources/fonts/DejaVuSansMono.ttf',
]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CHAT_DIR = "/root/loot/darksec-chat"
MESSAGES_FILE = os.path.join(CHAT_DIR, 'messages.json')
USERNAME_FILE = os.path.join(CHAT_DIR, 'username.txt')
THEME_FILE = os.path.join(CHAT_DIR, 'theme.txt')
APP_LOG_FILE = os.path.join(CHAT_DIR, 'darksec_chat_app.log')
INPUT_REQUEST_FILE = os.path.join(SCRIPT_DIR, 'data', 'input_request')
PENDING_MESSAGE_FILE = os.path.join(SCRIPT_DIR, 'data', 'pending_message.txt')
INPUT_REQUEST_EXIT = 43

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
def rgb(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

C = {
    'BG':           0x0000,
    'HEADER_BG':    rgb(8, 16, 32),
    'FOOTER_BG':    rgb(8, 16, 32),
    'MSG_TEXT':     0xFFFF,
    'TIME':         rgb(140, 140, 140),
    'SELF_NAME':    rgb(0, 200, 80),
    'PEER_NAME':    rgb(255, 180, 0),
    'SYS_NAME':     rgb(140, 140, 140),
    'WEB_LABEL':    rgb(80, 200, 255),
    'TITLE':        rgb(120, 200, 255),
    'STATUS_ON':    rgb(0, 220, 0),
    'STATUS_OFF':   rgb(80, 0, 0),
    'SCROLL_BAR':   rgb(60, 60, 60),
    'SEPARATOR':    rgb(30, 40, 50),
    'PAUSE_BG':     rgb(10, 10, 20),
    'PAUSE_ACCENT': rgb(60, 120, 200),
    'BRIGHT_FILL':  rgb(0, 200, 100),
    'BRIGHT_EMPTY': rgb(40, 40, 40),
    'HIGHLIGHT':    rgb(100, 200, 255),
    'KEY_BG':       rgb(20, 30, 40),
    'KEY_SEL':      rgb(40, 100, 60),
    'KEY_TEXT':     0xFFFF,
    'OVERLAY_BG':   rgb(10, 10, 20),
    'LABEL':        rgb(160, 160, 160),
    'WARNING':      rgb(255, 100, 0),
}

THEME_ORDER = ['darksec', 'amber', 'matrix', 'ice']

THEMES = {
    'darksec': {
        'name': 'DarkSec',
        'BG': rgb(0, 0, 0),
        'PANEL': rgb(8, 16, 32),
        'PANEL_2': rgb(4, 10, 18),
        'TEXT': rgb(235, 255, 245),
        'MUTED': rgb(140, 160, 170),
        'TITLE': rgb(90, 220, 255),
        'SELF': rgb(0, 220, 100),
        'PEER': rgb(255, 190, 40),
        'WEB': rgb(80, 210, 255),
        'SYSTEM': rgb(150, 150, 150),
        'OK': rgb(0, 220, 80),
        'OFF': rgb(90, 20, 20),
        'ACCENT': rgb(60, 120, 200),
        'HIGHLIGHT': rgb(100, 220, 255),
        'KEY_BG': rgb(18, 28, 38),
        'KEY_SEL': rgb(38, 110, 70),
    },
    'amber': {
        'name': 'Amber CRT',
        'BG': rgb(5, 3, 0),
        'PANEL': rgb(28, 16, 0),
        'PANEL_2': rgb(18, 10, 0),
        'TEXT': rgb(255, 232, 170),
        'MUTED': rgb(170, 120, 55),
        'TITLE': rgb(255, 190, 65),
        'SELF': rgb(255, 220, 110),
        'PEER': rgb(255, 155, 40),
        'WEB': rgb(255, 205, 80),
        'SYSTEM': rgb(160, 110, 45),
        'OK': rgb(255, 180, 55),
        'OFF': rgb(70, 25, 0),
        'ACCENT': rgb(120, 65, 10),
        'HIGHLIGHT': rgb(255, 210, 90),
        'KEY_BG': rgb(32, 18, 2),
        'KEY_SEL': rgb(105, 58, 8),
    },
    'matrix': {
        'name': 'Matrix',
        'BG': rgb(0, 4, 0),
        'PANEL': rgb(0, 20, 8),
        'PANEL_2': rgb(0, 12, 5),
        'TEXT': rgb(200, 255, 205),
        'MUTED': rgb(85, 150, 90),
        'TITLE': rgb(60, 255, 105),
        'SELF': rgb(90, 255, 130),
        'PEER': rgb(170, 255, 120),
        'WEB': rgb(80, 230, 160),
        'SYSTEM': rgb(80, 130, 85),
        'OK': rgb(0, 240, 70),
        'OFF': rgb(0, 55, 20),
        'ACCENT': rgb(10, 90, 35),
        'HIGHLIGHT': rgb(120, 255, 155),
        'KEY_BG': rgb(0, 24, 10),
        'KEY_SEL': rgb(10, 95, 40),
    },
    'ice': {
        'name': 'Ice',
        'BG': rgb(2, 8, 18),
        'PANEL': rgb(14, 28, 48),
        'PANEL_2': rgb(8, 18, 34),
        'TEXT': rgb(235, 245, 255),
        'MUTED': rgb(130, 160, 190),
        'TITLE': rgb(145, 215, 255),
        'SELF': rgb(125, 235, 210),
        'PEER': rgb(210, 220, 255),
        'WEB': rgb(110, 190, 255),
        'SYSTEM': rgb(120, 140, 165),
        'OK': rgb(90, 230, 180),
        'OFF': rgb(35, 55, 80),
        'ACCENT': rgb(55, 100, 160),
        'HIGHLIGHT': rgb(175, 225, 255),
        'KEY_BG': rgb(12, 28, 48),
        'KEY_SEL': rgb(45, 95, 145),
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def wrap_pixel(text, max_w, pager, font, font_size):
    if not text:
        return ['']
    words = text.split()
    lines = []
    cur = ''
    for w in words:
        test = cur + (' ' if cur else '') + w
        tw = pager.ttf_width(test, font, font_size)
        if tw <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            while pager.ttf_width(w, font, font_size) > max_w:
                for sl in range(len(w)-1, 0, -1):
                    if pager.ttf_width(w[:sl], font, font_size) <= max_w:
                        lines.append(w[:sl])
                        w = w[sl:]
                        break
                else:
                    break
            cur = w
    if cur:
        lines.append(cur)
    return lines


def display_time(value=None):
    if value:
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).strftime('%H:%M')
        except (AttributeError, ValueError):
            pass
    return datetime.now().strftime('%H:%M')


def app_log(message):
    try:
        os.makedirs(CHAT_DIR, exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(APP_LOG_FILE, 'a') as f:
            f.write(f"[{ts}] {message}\n")
    except OSError:
        pass


def request_system_text(kind):
    try:
        os.makedirs(os.path.dirname(INPUT_REQUEST_FILE), exist_ok=True)
        with open(INPUT_REQUEST_FILE, 'w') as f:
            f.write(kind)
        app_log(f"request_system_text kind={kind}")
    except OSError as e:
        app_log(f"request_system_text failed kind={kind} error={e}")
    raise SystemExit(INPUT_REQUEST_EXIT)


def read_pending_message():
    try:
        with open(PENDING_MESSAGE_FILE) as f:
            text = f.read().strip()
        os.remove(PENDING_MESSAGE_FILE)
        return text
    except (FileNotFoundError, OSError):
        return ''


def valid_theme_name(name):
    return name if name in THEMES else 'darksec'


def load_theme_name(path=THEME_FILE):
    try:
        with open(path) as f:
            return valid_theme_name(f.read().strip())
    except (FileNotFoundError, OSError):
        return 'darksec'


def save_theme_name(path, name):
    with open(path, 'w') as f:
        f.write(valid_theme_name(name))


def next_theme_name(current, direction=1):
    if current not in THEME_ORDER:
        return 'darksec'
    idx = THEME_ORDER.index(current)
    return THEME_ORDER[(idx + direction) % len(THEME_ORDER)]


class DarkSecHTTP:
    """Small JSON HTTP client for OpenWrt: urllib first, curl second."""

    def __init__(self, timeout=20):
        self.timeout = timeout

    def request(self, method, url, data=None, headers=None):
        headers = dict(headers or {})
        headers.setdefault('Accept', 'application/json')
        headers.setdefault('User-Agent', 'DarkSec-Chat-Pager/' + APP_VERSION)
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            headers.setdefault('Content-Type', 'application/json')
        try:
            return self._urllib_request(method.upper(), url, body, headers)
        except (ImportError, ModuleNotFoundError):
            return self._curl_request(method.upper(), url, body, headers)
        except Exception as error:
            if shutil.which('curl'):
                return self._curl_request(method.upper(), url, body, headers)
            return {'ok': False, 'status': 0, 'data': None, 'error': str(error)}

    def get(self, url, headers=None):
        return self.request('GET', url, headers=headers)

    def post(self, url, data, headers=None):
        return self.request('POST', url, data=data, headers=headers)

    def _urllib_request(self, method, url, body, headers):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode('utf-8', errors='replace')
                return self._result(response.getcode(), raw)
        except urllib.error.HTTPError as error:
            raw = error.read().decode('utf-8', errors='replace')
            result = self._result(error.code, raw)
            result['error'] = 'HTTP %s: %s' % (error.code, error.reason)
            return result
        except urllib.error.URLError as error:
            return {'ok': False, 'status': 0, 'data': None,
                    'error': 'Connection error: %s' % error.reason}

    def _curl_request(self, method, url, body, headers):
        curl = shutil.which('curl')
        if not curl:
            return {'ok': False, 'status': 0, 'data': None,
                    'error': 'Neither urllib.request nor curl is available'}
        marker = '\n__DARKSEC_STATUS__:'
        command = [curl, '--silent', '--show-error', '--location', '--max-time',
                   str(self.timeout), '--request', method]
        for key, value in headers.items():
            command.extend(['--header', '%s: %s' % (key, value)])
        if body is not None:
            command.extend(['--data-binary', body.decode('utf-8')])
        command.extend(['--write-out', marker + '%{http_code}', url])
        try:
            completed = subprocess.run(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       timeout=self.timeout + 5, check=False)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'status': 0, 'data': None, 'error': 'Request timed out'}
        if completed.returncode != 0:
            return {'ok': False, 'status': 0, 'data': None,
                    'error': completed.stderr.strip() or 'curl request failed'}
        raw_body, separator, raw_status = completed.stdout.rpartition(marker)
        try:
            status = int(raw_status.strip()) if separator else 0
        except ValueError:
            status = 0
        return self._result(status, raw_body if separator else completed.stdout)

    @staticmethod
    def _decode(raw):
        raw = raw.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    @classmethod
    def _result(cls, status, raw):
        ok = 200 <= status < 300
        return {'ok': ok, 'status': status, 'data': cls._decode(raw),
                'error': None if ok else 'HTTP %s' % status}


# ===================================================================
# Config
# ===================================================================

def parse_config():
    cfg = {
        'web_api_url': '',
        'username': 'PagerUser',
        'udp_port': 9999,
        'tcp_port': 9998,
        'mesh_shared_key': '',
    }
    config_path = os.path.join(SCRIPT_DIR, 'config.sh')
    try:
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('export '):
                    line = line[7:]
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    v = v.strip('"\' ')
                    if k == 'WEB_API_URL':
                        cfg['web_api_url'] = v
                    elif k == 'USERNAME':
                        cfg['username'] = v or 'PagerUser'
                    elif k == 'UDP_PORT':
                        cfg['udp_port'] = int(v) if v.isdigit() else 9999
                    elif k == 'TCP_PORT':
                        cfg['tcp_port'] = int(v) if v.isdigit() else 9998
                    elif k == 'MESH_SHARED_KEY':
                        cfg['mesh_shared_key'] = v
    except FileNotFoundError:
        pass
    return cfg


# ===================================================================
# ChatBackend
# ===================================================================

class ChatBackend:
    """Mesh + web bridge networking. Thread-safe message/peer state."""

    DARKSEC_URL = "https://darksec.uk/api/chat"

    def __init__(self, username, cfg):
        self.username = username
        self.udp_port = cfg['udp_port']
        self.tcp_port = cfg['tcp_port']
        self._mesh_key = cfg.get('mesh_shared_key', '').encode('utf-8')
        self._mesh_enabled = len(self._mesh_key) >= 32
        self._mesh_enc_key = hashlib.sha256(b'darksec-enc\0' + self._mesh_key).digest()
        self._mesh_mac_key = hashlib.sha256(b'darksec-mac\0' + self._mesh_key).digest()
        self.running = False

        self._msgs = deque(maxlen=500)
        self._msg_lock = threading.Lock()
        self._message_revision = 0
        self._peers = {}
        self._peer_lock = threading.Lock()
        self._mesh_ok = False
        self._seen_nonces = {}
        self._nonce_lock = threading.Lock()

        url = cfg['web_api_url']
        if not url or 'example.com' in url:
            url = self.DARKSEC_URL
        self._web_url = url
        self._web_ok = False
        self._web_enabled = bool(url)
        self._web_seen = set()
        self._web_last_id = 0
        self._pending_web_echoes = deque(maxlen=50)
        self._web_echo_lock = threading.Lock()
        self._http = DarkSecHTTP(timeout=5)

    def start(self):
        self.running = True
        if self._mesh_enabled:
            t = threading.Thread(target=self._mesh_broadcast, daemon=True)
            t.start()
            t = threading.Thread(target=self._mesh_listener, daemon=True)
            t.start()
            t = threading.Thread(target=self._mesh_tcp_server, daemon=True)
            t.start()
        else:
            app_log("mesh disabled: MESH_SHARED_KEY must be at least 32 characters")
        if self._web_enabled:
            t = threading.Thread(target=self._web_poll, daemon=True)
            t.start()

    def stop(self):
        self.running = False

    def messages(self):
        with self._msg_lock:
            return list(self._msgs)

    def message_revision(self):
        with self._msg_lock:
            return self._message_revision

    def peer_count(self):
        with self._peer_lock:
            return len(self._peers)

    def web_connected(self):
        return self._web_enabled and self._web_ok

    def mesh_connected(self):
        return self._mesh_ok

    def _secure_packet(self, packet):
        """Encrypt then authenticate one versioned mesh packet."""
        timestamp = int(time.time())
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(
            packet, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ciphertext = _chacha20_xor(self._mesh_enc_key, nonce, plaintext)
        nonce_text = base64.b64encode(nonce).decode('ascii')
        ciphertext_text = base64.b64encode(ciphertext).decode('ascii')
        authenticated = ('1|%s|%s|%s' % (
            timestamp, nonce_text, ciphertext_text)).encode('ascii')
        mac = hmac.new(
            self._mesh_mac_key, authenticated, hashlib.sha256).hexdigest()
        return {'v': 1, 'ts': timestamp, 'nonce': nonce_text,
                'ciphertext': ciphertext_text, 'mac': mac}

    def _verify_packet(self, packet):
        if not self._mesh_enabled or not isinstance(packet, dict):
            return False
        mac = packet.get('mac')
        nonce_text = packet.get('nonce')
        ciphertext_text = packet.get('ciphertext')
        timestamp = packet.get('ts')
        if (packet.get('v') != 1 or not isinstance(mac, str) or
                not isinstance(nonce_text, str) or
                not isinstance(ciphertext_text, str) or
                not isinstance(timestamp, int)):
            return None
        now = int(time.time())
        if abs(now - timestamp) > 30:
            return None
        authenticated = ('1|%s|%s|%s' % (
            timestamp, nonce_text, ciphertext_text)).encode('ascii')
        expected = hmac.new(
            self._mesh_mac_key, authenticated, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return None
        with self._nonce_lock:
            if nonce_text in self._seen_nonces:
                return None
            self._seen_nonces[nonce_text] = timestamp
            if len(self._seen_nonces) > 512:
                cutoff = now - 30
                self._seen_nonces = {
                    n: ts for n, ts in self._seen_nonces.items() if ts >= cutoff}
        try:
            nonce = base64.b64decode(nonce_text, validate=True)
            ciphertext = base64.b64decode(ciphertext_text, validate=True)
            if len(nonce) != 12 or len(ciphertext) > 8192:
                return None
            plaintext = _chacha20_xor(self._mesh_enc_key, nonce, ciphertext)
            decoded = json.loads(plaintext.decode('utf-8'))
            return decoded if isinstance(decoded, dict) else None
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def restore_messages(self, saved):
        if not isinstance(saved, list):
            return
        with self._msg_lock:
            for m in saved:
                if isinstance(m, dict):
                    sender = m.get('sender', '?')
                    text = m.get('text', '')
                    self._msgs.append({
                        'sender': (sender if isinstance(sender, str) else str(sender))[:32],
                        'text': (text if isinstance(text, str) else str(text))[:1000],
                        'time': m.get('time', '') if isinstance(m.get('time', ''), str) else '',
                        'source': m.get('source', 'system')
                        if m.get('source') in ('self', 'web', 'mesh', 'system') else 'system',
                    })
                    self._message_revision += 1

    def add_message(self, sender, text, source, when=None):
        sender = sender if isinstance(sender, str) else str(sender)
        text = text if isinstance(text, str) else str(text)
        msg = {
            'sender': sender[:32],
            'text': text[:1000],
            'time': display_time(when),
            'source': source,
        }
        with self._msg_lock:
            self._msgs.append(msg)
            self._message_revision += 1

    def send_message(self, text):
        t = text.strip()
        if not t:
            return
        app_log(f"send_message start len={len(t)} web_enabled={self._web_enabled} peers={self.peer_count()}")
        self.add_message(self.username, t, 'self')
        app_log("send_message after_add_self")
        # Never make the display/input loop wait for mesh sockets or HTTPS.
        # The local message appears immediately while delivery completes in
        # the background.
        threading.Thread(target=self._send_worker, args=(t,), daemon=True).start()

    def _send_worker(self, text):
        try:
            self._mesh_send(text)
            app_log("send_message after_mesh")
            if self._web_enabled and not self._web_post(text):
                self.add_message("System", "Web send failed - check connection.", "system")
            app_log("send_message done")
        except Exception as error:
            app_log(f"send_message worker_error={error}")
            self.add_message("System", "Send failed - check logs.", "system")

    # -- Mesh --

    def _mesh_broadcast(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(1)
        while self.running:
            try:
                data = json.dumps(self._secure_packet(
                    {"type":"presence","username":self.username,"ip":get_local_ip()}))
                s.sendto(data.encode(), ('<broadcast>', self.udp_port))
            except OSError:
                pass
            time.sleep(5)

    def _mesh_listener(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', self.udp_port))
        s.settimeout(1)
        local = get_local_ip()
        while self.running:
            try:
                d, addr = s.recvfrom(4096)
                if addr[0] == local:
                    continue
                m = json.loads(d.decode())
                m = self._verify_packet(m)
                if (m and m.get('type') == 'presence' and
                        m.get('username') != self.username):
                    # Never trust a claimed address inside a broadcast packet.
                    ip = addr[0]
                    name = m.get('username', '?')
                    with self._peer_lock:
                        if ip not in self._peers:
                            try:
                                tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                tcp.settimeout(5)
                                tcp.connect((ip, self.tcp_port))
                                tcp.send(json.dumps(self._secure_packet(
                                    {"type":"handshake","username":self.username})).encode())
                                self._peers[ip] = (tcp, name)
                                self._mesh_ok = True
                                t = threading.Thread(target=self._mesh_peer, args=(tcp, ip, name), daemon=True)
                                t.start()
                            except (ConnectionRefusedError, OSError, socket.timeout):
                                pass
            except (json.JSONDecodeError, socket.timeout, OSError):
                pass

    def _mesh_tcp_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', self.tcp_port))
        s.listen(5)
        s.settimeout(1)
        while self.running:
            try:
                c, addr = s.accept()
                c.settimeout(3)
                accepted = False
                with self._peer_lock:
                    if addr[0] not in self._peers:
                        try:
                            d = c.recv(4096).decode()
                            h = json.loads(d)
                            h = self._verify_packet(h)
                            if h and h.get('type') == 'handshake':
                                name = h.get('username', '?')
                                self._peers[addr[0]] = (c, name)
                                self._mesh_ok = True
                                t = threading.Thread(target=self._mesh_peer, args=(c, addr[0], name), daemon=True)
                                t.start()
                                accepted = True
                        except (json.JSONDecodeError, OSError):
                            pass
                if not accepted:
                    c.close()
            except socket.timeout:
                pass

    def _mesh_peer(self, sock, ip, name):
        sock.settimeout(1)
        while self.running:
            try:
                d = sock.recv(4096).decode()
                if not d:
                    break
                m = json.loads(d)
                m = self._verify_packet(m)
                if m and m.get('type') == 'chat':
                    self.add_message(name, m['text'], 'mesh')
            except (socket.timeout, json.JSONDecodeError):
                continue
            except OSError:
                break
        with self._peer_lock:
            self._peers.pop(ip, None)
            self._mesh_ok = bool(self._peers)

    def _mesh_send(self, text):
        app_log(f"mesh_send start len={len(text)}")
        if not self._mesh_enabled:
            return
        p = json.dumps(self._secure_packet({"type":"chat","text":text}))
        with self._peer_lock:
            dead = []
            for ip, (sock, _) in self._peers.items():
                try:
                    sock.send(p.encode())
                except OSError:
                    app_log(f"mesh_send peer_failed ip={ip}")
                    dead.append(ip)
            for ip in dead:
                self._peers.pop(ip, None)
            self._mesh_ok = bool(self._peers)
        app_log(f"mesh_send done peers={self.peer_count()}")

    # -- Web --

    def _web_poll(self):
        while self.running:
            self._poll_web_once()
            time.sleep(1)

    def _web_poll_url(self):
        if self._web_last_id <= 0:
            return self._web_url
        parts = urlsplit(self._web_url)
        query = parts.query
        after = urlencode({'after': self._web_last_id})
        query = f"{query}&{after}" if query else after
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _consume_local_web_echo(self, sender, text):
        """Suppress only exact recent echoes of messages posted by this Pager."""
        if sender != self.username or not isinstance(text, str):
            return False
        now = time.monotonic()
        with self._web_echo_lock:
            fresh = deque(maxlen=50)
            matched = False
            while self._pending_web_echoes:
                pending_text, sent_at = self._pending_web_echoes.popleft()
                if now - sent_at > 60:
                    continue
                if not matched and pending_text == text:
                    matched = True
                    continue
                fresh.append((pending_text, sent_at))
            self._pending_web_echoes = fresh
        return matched

    def _poll_web_once(self):
        try:
            response = self._http.get(self._web_poll_url())
            if not response['ok']:
                self._web_ok = False
                app_log("web_poll failed status=%s error=%s" %
                        (response['status'], response['error']))
                return
            self._web_ok = True
            data = response['data']
            if isinstance(data, list):
                msgs = data
            elif isinstance(data, dict):
                msgs = data.get('messages', [])
            else:
                app_log("web_poll invalid response type=%s" % type(data).__name__)
                self._web_ok = False
                return
            if not isinstance(msgs, list):
                app_log("web_poll invalid messages type=%s" % type(msgs).__name__)
                self._web_ok = False
                return
            initial_sync = self._web_last_id <= 0
            # The live endpoint can return hundreds of long news messages.
            # Advance past the full history but only materialize the newest
            # screenful on first connection so startup and buttons stay fast.
            if initial_sync and len(msgs) > 20:
                for old_msg in msgs[:-20]:
                    try:
                        self._web_last_id = max(self._web_last_id, int(old_msg.get('id', 0)))
                    except (TypeError, ValueError):
                        pass
                msgs = msgs[-20:]
            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                mid = msg.get('id')
                if isinstance(mid, str) and mid.isdigit():
                    mid = int(mid)
                if isinstance(mid, int):
                    self._web_last_id = max(self._web_last_id, mid)
                    dedupe_key = f"id:{mid}"
                else:
                    dedupe_key = f"fallback:{msg.get('username','')}|{msg.get('message','')}|{msg.get('created_at', msg.get('timestamp',''))}"
                sender = msg.get('username', 'Web')
                sender = sender if isinstance(sender, str) else 'Web'
                t = msg.get('message','')
                if dedupe_key in self._web_seen:
                    continue
                self._web_seen.add(dedupe_key)
                if len(self._web_seen) > 2000:
                    # IDs older than _web_last_id will not be requested again.
                    self._web_seen.clear()
                    self._web_seen.add(dedupe_key)
                if isinstance(t, str) and t:
                    if self._consume_local_web_echo(sender, t):
                        continue
                    self.add_message(sender, t, 'web', msg.get('created_at'))
                    # Do not flood mesh peers with website backlog on startup.
                    if not initial_sync:
                        self._mesh_send(f"[Web] {sender}: {t}")
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            app_log(f"web_poll error={e}")
            self._web_ok = False
        except Exception as e:
            app_log(f"web_poll unexpected_error={e}")
            self._web_ok = False

    def _web_post(self, text):
        try:
            app_log(f"web_post start len={len(text)} url={self._web_url}")
            response = self._http.post(
                self._web_url, {"username": self.username, "message": text})
            if response['ok']:
                with self._web_echo_lock:
                    self._pending_web_echoes.append((text, time.monotonic()))
                app_log("web_post ok")
                return True
            else:
                app_log("web_post failed status=%s error=%s" %
                        (response['status'], response['error']))
                return False
        except (OSError, ValueError, TypeError) as e:
            app_log(f"web_post error={e}")
            return False
        except Exception as e:
            app_log(f"web_post unexpected_error={e}")
            return False


# ===================================================================
# ChatDisplay
# ===================================================================

class ChatDisplay:
    """Pager LCD with inline keyboard, pause menu, auto-dim, LEDs."""

    KBD_KEYS = [
        ['Q','W','E','R','T','Y','U','I','O','P'],
        ['A','S','D','F','G','H','J','K','L'],
        ['Z','X','C','V','B','N','M','.',','],
        ['1','2','3','4','5','6','7','8','9','0'],
    ]
    KBD_SPECIAL = [('SHIFT','shift'), ('SPACE',' '), ('BSP','\b'), ('SEND','\n')]

    def __init__(self):
        self.p = None
        self.W = 480
        self.H = 222
        self.theme_name = load_theme_name()
        self.theme = THEMES[self.theme_name]
        self._font = None
        self._ttf = False
        self._bright = 80
        self._last_act = time.time()
        self._dimmed = False
        self._last_led = None
        self._init()

    def _discover_font(self):
        for p in FONT_SEARCH_PATHS:
            if os.path.isfile(p):
                return p
        return None

    def _init(self):
        self.p = Pager()
        self.p.init()
        self.p.set_rotation(270)
        self.W = self.p.width
        self.H = self.p.height
        fp = self._discover_font()
        self._font = fp
        self._ttf = bool(fp)
        self.p.set_brightness(self._bright)

    def set_theme(self, name):
        self.theme_name = valid_theme_name(name)
        self.theme = THEMES[self.theme_name]
        try:
            save_theme_name(THEME_FILE, self.theme_name)
        except OSError:
            pass

    def cycle_theme(self, direction=1):
        self.set_theme(next_theme_name(self.theme_name, direction))

    def cleanup(self):
        if self.p:
            try:
                self.p.cleanup()
            except Exception:
                pass
            self.p = None

    # -- Brightness / dim --

    def set_brightness(self, v):
        self._bright = max(20, min(100, v))
        try:
            self.p.set_brightness(self._bright)
        except Exception:
            pass

    def activity(self):
        self._last_act = time.time()
        if self._dimmed:
            self._dimmed = False
            try: self.p.set_brightness(self._bright)
            except: pass

    def pressed_buttons(self):
        """Consume the pagerctl event queue, with state polling as fallback."""
        _, fallback_pressed, _ = self.p.poll_input()
        pressed = 0
        try:
            while self.p.has_input_events():
                event = self.p.get_input_event()
                if not event:
                    break
                button, event_type, _ = event
                if event_type == 1:  # PAGER_EVENT_PRESS
                    pressed |= button
        except (AttributeError, OSError):
            pass
        return pressed or fallback_pressed

    def _dim_check(self):
        if self._dimmed:
            return
        if time.time() - self._last_act > 30:
            self._dimmed = True
            try: self.p.set_brightness(20)
            except: pass

    def _leds(self, pc, wo):
        s = (pc > 0, wo)
        if s == self._last_led:
            return
        self._last_led = s
        try:
            v = 0x003300 if pc > 0 else 0x000000
            self.p.led_dpad("up", v)
            self.p.led_dpad("down", v)
            self.p.led_dpad("left", v)
            self.p.led_dpad("right", v)
            self.p.led_set("a", 30 if wo else 0)
            self.p.led_set("b", 30 if pc > 0 else 0)
        except:
            pass

    # -- Draw helpers --

    def _text(self, x, y, t, c, s=1, ts=13):
        if self._ttf:
            self.p.draw_ttf(x, y, t, c, self._font, ts)
        else:
            self.p.draw_text(x, y, t, c, s)

    def _tw(self, t, s=1, ts=13):
        if self._ttf:
            return self.p.ttf_width(t, self._font, ts)
        return self.p.text_width(t, s)

    def _th(self, s=1, ts=13):
        if self._ttf:
            return self.p.ttf_height(self._font, ts)
        return 8 * s

    # -- Splash --

    def splash(self):
        t = self.theme
        self.p.clear(t['BG'])
        if self._ttf:
            title = "DARKSEC // CHAT"
            tw = self.p.ttf_width(title, self._font, 28)
            self.p.draw_ttf((self.W-tw)//2, 42, title, t['TITLE'], self._font, 28)
            subtitle = "WEB + MESH UPLINK"
            tw = self.p.ttf_width(subtitle, self._font, 15)
            self.p.draw_ttf((self.W-tw)//2, 82, subtitle, t['MUTED'], self._font, 15)
            status = "[ INITIALIZING SECURE CHANNEL ]"
            tw = self.p.ttf_width(status, self._font, 11)
            self.p.draw_ttf((self.W-tw)//2, 112, status, t['OK'], self._font, 11)
        else:
            self.p.draw_text_centered(50, "DARKSEC // CHAT", t['TITLE'], 2)
            self.p.draw_text_centered(82, "WEB + MESH UPLINK", t['MUTED'], 1)
            self.p.draw_text_centered(105, "[ INITIALIZING ]", t['OK'], 1)
        self.p.flip()
        time.sleep(0.5)

    # -- Username screen --

    def username_screen(self, cur):
        t = self.theme
        self.p.clear(t['BG'])
        if self._ttf:
            tw = self.p.ttf_width("Choose username:", self._font, 18)
            self.p.draw_ttf((self.W-tw)//2, 40, "Choose username:", t['TITLE'], self._font, 18)
            tw = self.p.ttf_width(cur or "(type below)", self._font, 14)
            self.p.draw_ttf((self.W-tw)//2, 75, cur or "(type below)", t['HIGHLIGHT'], self._font, 14)
            tw = self.p.ttf_width("Press A", self._font, 11)
            self.p.draw_ttf((self.W-tw)//2, 110, "Press A", t['MUTED'], self._font, 11)
        else:
            self.p.draw_text_centered(45, "Choose username:", t['TITLE'], 1)
            self.p.draw_text_centered(70, cur or "(type below)", t['HIGHLIGHT'], 1)
            self.p.draw_text_centered(100, "Press A", t['MUTED'], 1)
        self.p.flip()

    # -- Chat view --

    HEADER_H = 24
    FOOTER_H = 13

    def chat_view(self, msgs, scroll, pc, wo):
        self._dim_check()
        self._leds(pc, wo)
        theme = self.theme
        self.p.clear(theme['BG'])
        W, H = self.W, self.H

        # Header
        self.p.fill_rect(0, 0, W, self.HEADER_H, theme['PANEL'])
        self.p.fill_rect(0, self.HEADER_H-2, W, 2, theme['ACCENT'])
        self._text(6, 4, "DarkSec", theme['TITLE'], ts=14)

        mcol = theme['OK'] if pc > 0 else theme['OFF']
        wcol = theme['OK'] if wo else theme['OFF']
        mesh = f"MESH {pc}"
        web = "WEB OK" if wo else "WEB --"
        if self._ttf:
            for x, label, col in [(W-150, mesh, mcol), (W-76, web, wcol)]:
                self.p.fill_rect(x-4, 4, 68, 15, theme['PANEL_2'])
                self.p.rect(x-4, 4, 68, 15, col)
                self.p.draw_ttf(x, 6, label, col, self._font, 9)
        else:
            self.p.draw_text(W-112, 8, f"M:{pc} W:{'ON' if wo else '--'}", theme['MUTED'], 1)

        # Lines
        lh = self.p.ttf_height(self._font, 13)+2 if self._ttf else 9
        ah = H - self.HEADER_H - self.FOOTER_H - 2
        mv = max(1, ah // max(1, lh))
        mw = max(10, (W-12)//7) if self._ttf else (W-12)//6

        lines = []
        # Bound pixel measurement and wrapping work per frame. The complete
        # recent history remains persisted; the LCD shows the newest 50 items.
        for m in msgs[-50:]:
            s = m.get('sender','?')
            text = m.get('text','')
            tm = m.get('time','')
            src = m.get('source','mesh')
            pfx = f"[{tm}]"
            if src == 'web':    np = f"W:{s}"
            elif src == 'self': np = "You"
            else:               np = s
            lines.append((f"{pfx} {np}:", src))
            if self._ttf:
                for w in wrap_pixel(text, W-12, self.p, self._font, 13):
                    lines.append((w, src))
            else:
                for w in self._wrap_approx(text, mw):
                    lines.append((w, src))
            lines.append(('',''))

        while lines and lines[-1][0] == '':
            lines.pop()

        if not lines:
            empty = "No messages yet. Press A to send."
            if self._ttf:
                tw = self.p.ttf_width(empty, self._font, 13)
                self.p.draw_ttf((W-tw)//2, self.HEADER_H+45, empty, theme['MUTED'], self._font, 13)
            else:
                self.p.draw_text_centered(self.HEADER_H+45, empty, theme['MUTED'], 1)

        ms = max(0, len(lines)-mv)
        scroll = max(0, min(scroll, ms))
        self._max_scroll = ms

        y = self.HEADER_H + 1
        for i in range(scroll, min(scroll+mv, len(lines))):
            lt, src = lines[i]
            if not lt:
                y += max(1, lh//2)
                continue
            if src == 'self':      cl = theme['SELF']
            elif src == 'web':     cl = theme['WEB']
            elif src == 'system':  cl = theme['SYSTEM']
            elif lt.endswith(':'): cl = theme['PEER']
            else:                  cl = theme['TEXT']
            self._text(4, y, lt, cl, ts=13)
            y += lh

        if ms > 0:
            bh = max(8, ah*mv//max(1,len(lines)))
            by = self.HEADER_H + (ah-bh)*scroll//max(1,ms)
            self.p.fill_rect(W-4, by, 3, bh, theme['ACCENT'])

        self.p.fill_rect(0, H-self.FOOTER_H, W, self.FOOTER_H, theme['PANEL'])
        self.p.hline(0, H-self.FOOTER_H, W, theme['ACCENT'])
        self._text(5, H-self.FOOTER_H+2, "UP/DN scroll   A send   B menu   PWR exit", theme['MUTED'], ts=10)
        self.p.flip()
        return scroll

    def _wrap_approx(self, t, n):
        w = t.split(' ')
        r, c = [], ''
        for a in w:
            if len(c)+len(a)+(1 if c else 0) <= n:
                c += (' ' if c else '') + a
            else:
                if c: r.append(c)
                while len(a) > n:
                    r.append(a[:n]); a = a[n:]
                c = a
        if c: r.append(c)
        return r

    # -- Keyboard (inline, using poll_input) --

    def keyboard(self, prompt="Message:"):
        text = ""
        shifted = False
        r, c = 0, 0
        sp_idx = -1
        GAP = 3
        W, H = self.W, self.H
        hh = 19
        ph = 16
        # Four 32px rows plus the action row fill the Pager display closely
        # and are substantially easier to read than the previous 26px keys.
        kh = 32
        sh = kh
        sy = hh + ph + 2
        rows = len(self.KBD_KEYS)
        key_ts = 14
        action_ts = 13

        while True:
            t = self.theme
            self.p.clear(t['BG'])
            self.p.fill_rect(0, 0, W, hh, t['PANEL'])
            self.p.fill_rect(0, hh-2, W, 2, t['ACCENT'])
            self._text(5, 1, prompt, t['TITLE'], ts=12)

            pv = text[-50:] if len(text)>50 else text
            self._text(5, hh+1, pv+'_', t['TEXT'], ts=13)

            y = sy
            for ri, row in enumerate(self.KBD_KEYS):
                kw = (W - GAP*(len(row)+1)) // len(row)
                for ci, key in enumerate(row):
                    shown_key = key if shifted or not key.isalpha() else key.lower()
                    x = ci*(kw+GAP)+GAP
                    sel = (sp_idx<0 and ri==r and ci==c)
                    b = t['KEY_SEL'] if sel else t['KEY_BG']
                    self.p.fill_rect(x, y, kw, kh, b)
                    self.p.rect(x, y, kw, kh, t['ACCENT'] if sel else t['PANEL'])
                    if sel and kw > 4 and kh > 4:
                        self.p.rect(x+1, y+1, kw-2, kh-2, t['HIGHLIGHT'])
                    tw = self._tw(shown_key, ts=key_ts)
                    tx = x + (kw-tw)//2
                    ty = y + max(1, (kh-self._th(ts=key_ts))//2)
                    self._text(tx, ty, shown_key, t['TEXT'], ts=key_ts)
                y += kh + GAP

            # Specials
            sx = GAP
            for si, (label, _) in enumerate(self.KBD_SPECIAL):
                shown_label = "SHIFT^" if label == "SHIFT" and shifted else label
                sw = self._tw(shown_label, ts=action_ts)
                kw = sw + 18
                sel = (sp_idx>=0 and sp_idx==si)
                b = t['KEY_SEL'] if sel else t['KEY_BG']
                self.p.fill_rect(sx, y, kw, sh, b)
                self.p.rect(sx, y, kw, sh, t['ACCENT'] if sel else t['PANEL'])
                if sel and kw > 4 and sh > 4:
                    self.p.rect(sx+1, y+1, kw-2, sh-2, t['HIGHLIGHT'])
                tx = sx + (kw-self._tw(shown_label, ts=action_ts))//2
                ty = y + max(1, (sh-self._th(ts=action_ts))//2)
                self._text(tx, ty, shown_label, t['TEXT'], ts=action_ts)
                sx += kw + GAP

            self.p.fill_rect(0, H-self.FOOTER_H, W, self.FOOTER_H, t['PANEL'])
            self._text(4, H-self.FOOTER_H+2, "DPAD nav   A select   B backspace", t['MUTED'], ts=10)
            self.p.flip()

            # Draw once, then wait for an actual event. Repainting the entire
            # keyboard while idle makes button handling lag on the Pager.
            pressed = 0
            while not pressed:
                pressed = self.pressed_buttons()
                if not pressed:
                    self.p.delay(30)

            if sp_idx >= 0:
                if pressed & Pager.BTN_UP:
                    c = round(sp_idx * (len(self.KBD_KEYS[rows-1])-1) /
                              max(1, len(self.KBD_SPECIAL)-1))
                    sp_idx = -1
                    r = rows-1
                elif pressed & Pager.BTN_DOWN:
                    # Wrap from the action row to the top character row while
                    # keeping roughly the same horizontal position.
                    c = round(sp_idx * (len(self.KBD_KEYS[0])-1) /
                              max(1, len(self.KBD_SPECIAL)-1))
                    r = 0
                    sp_idx = -1
                elif pressed & Pager.BTN_LEFT:
                    sp_idx = (sp_idx - 1) % len(self.KBD_SPECIAL)
                elif pressed & Pager.BTN_RIGHT:
                    sp_idx = (sp_idx + 1) % len(self.KBD_SPECIAL)
                elif pressed & Pager.BTN_A:
                    _, act = self.KBD_SPECIAL[sp_idx]
                    if act == 'shift':
                        shifted = not shifted
                    elif act == '\n':
                        return text.strip()
                    elif act == '\b':
                        text = text[:-1]
                    elif act == ' ':
                        text += ' '
                elif pressed & Pager.BTN_B:
                    text = text[:-1]
            else:
                if pressed & Pager.BTN_UP:
                    if r > 0:
                        r -= 1
                        c = min(c, len(self.KBD_KEYS[r])-1)
                    else:
                        sp_idx = round(c * (len(self.KBD_SPECIAL)-1) /
                                       max(1, len(self.KBD_KEYS[r])-1))
                elif pressed & Pager.BTN_DOWN:
                    if r < rows-1:
                        r += 1
                        c = min(c, len(self.KBD_KEYS[r])-1)
                    else:
                        sp_idx = round(c * (len(self.KBD_SPECIAL)-1) /
                                       max(1, len(self.KBD_KEYS[r])-1))
                elif pressed & Pager.BTN_LEFT:
                    c = (c - 1) % len(self.KBD_KEYS[r])
                elif pressed & Pager.BTN_RIGHT:
                    c = (c + 1) % len(self.KBD_KEYS[r])
                elif pressed & Pager.BTN_A:
                    key = self.KBD_KEYS[r][c]
                    text += key if shifted or not key.isalpha() else key.lower()
                elif pressed & Pager.BTN_B:
                    text = text[:-1]

            self.p.delay(20)

    # -- Pause menu --

    def pause_menu(self, pc, wo, mc, user, ip):
        sel = 0
        bright = self._bright
        num = 4

        def draw():
            t = self.theme
            self.p.clear(t['BG'])
            W, H = self.W, self.H
            self.p.fill_rect(0, 0, W, 28, t['PANEL'])
            self.p.fill_rect(0, 26, W, 2, t['ACCENT'])
            if self._ttf:
                tw = self.p.ttf_width("DarkSec-Chat", self._font, 20)
                self.p.draw_ttf((W-tw)//2, 5, "DarkSec-Chat", t['TITLE'], self._font, 20)
            else:
                self.p.draw_text_centered(8, "DarkSec-Chat", t['TITLE'], 2)

            bw, bh = 280, 14
            bx = (W-bw)//2
            by = 45
            bl = "Brightness"
            if self._ttf:
                tw = self.p.ttf_width(bl, self._font, 13)
                self.p.draw_ttf((W-tw)//2, by-15, bl, t['HIGHLIGHT'] if sel==0 else t['MUTED'], self._font, 13)
            else:
                self.p.draw_text_centered(by-14, bl, t['HIGHLIGHT'] if sel==0 else t['MUTED'], 1)
            if sel==0:
                self.p.rect(bx-2, by-2, bw+4, bh+4, t['HIGHLIGHT'])
            self.p.fill_rect(bx, by, bw, bh, t['PANEL_2'])
            self.p.fill_rect(bx, by, int(bw*bright/100), bh, t['OK'])
            self.p.rect(bx, by, bw, bh, t['MUTED'])
            pct = f"{bright}%"
            if self._ttf:
                tw = self.p.ttf_width(pct, self._font, 12)
                self.p.draw_ttf((W-tw)//2, by+bh+2, pct, t['MUTED'], self._font, 12)
            else:
                self.p.draw_text_centered(by+bh+2, pct, t['MUTED'], 1)

            ty = by + bh + 20
            theme_line = f"Theme: {self.theme['name']}"
            theme_col = t['HIGHLIGHT'] if sel == 1 else t['MUTED']
            if self._ttf:
                tw = self.p.ttf_width(theme_line, self._font, 13)
                tx = (W - tw) // 2
                if sel == 1:
                    self.p.rect(tx-8, ty-3, tw+16, 20, t['HIGHLIGHT'])
                self.p.draw_ttf(tx, ty, theme_line, theme_col, self._font, 13)
            else:
                self.p.draw_text_centered(ty, theme_line, theme_col, 1)

            iy = ty + 24
            for i, l in enumerate([f"User: {user}", f"IP: {ip}", f"Mesh: {pc}", f"Web: {'OK' if wo else 'OFF'}", f"Msgs: {mc}"]):
                self._text(20, iy+i*14, l, t['MUTED'], ts=11)

            oy = iy + 5*14 + 4
            for i, opt in enumerate(["[  MAIN MENU  ]", "[  EXIT  ]"]):
                hs = sel == i+2
                if self._ttf:
                    tw = self.p.ttf_width(opt, self._font, 14)
                    ox = (W-tw)//2
                    self.p.fill_rect(ox-6, oy-2, tw+12, 22, t['ACCENT'] if hs else t['PANEL_2'])
                    self.p.rect(ox-6, oy-2, tw+12, 22, t['HIGHLIGHT'] if hs else t['PANEL'])
                    self.p.draw_ttf(ox, oy+1, opt, t['HIGHLIGHT'] if hs else t['MUTED'], self._font, 14)
                else:
                    self.p.draw_text_centered(oy+i*18, opt, t['HIGHLIGHT'] if hs else t['MUTED'], 1)
                oy += 28 if self._ttf else 18

            hint = "UP/DN nav   LEFT/RIGHT adjust   A select   B back"
            self.p.fill_rect(0, H-self.FOOTER_H, W, self.FOOTER_H, t['PANEL'])
            self._text(4, H-self.FOOTER_H+2, hint, t['MUTED'], ts=10)
            self.p.flip()

        draw()
        while True:
            pressed = self.pressed_buttons()
            if not pressed:
                self.p.delay(20)
                continue
            if pressed & Pager.BTN_UP:
                sel = (sel-1)%num; draw()
            elif pressed & Pager.BTN_DOWN:
                sel = (sel+1)%num; draw()
            elif pressed & Pager.BTN_LEFT:
                if sel==0:
                    bright = max(20, bright-10); self.set_brightness(bright); draw()
                elif sel==1:
                    self.cycle_theme(-1); draw()
            elif pressed & Pager.BTN_RIGHT:
                if sel==0:
                    bright = min(100, bright+10); self.set_brightness(bright); draw()
                elif sel==1:
                    self.cycle_theme(1); draw()
            elif pressed & Pager.BTN_A:
                if sel==2: return 'menu'
                if sel==3: return 'exit'
            elif pressed & Pager.BTN_B:
                return 'resume'
            self.p.delay(20)


# ===================================================================
# Main
# ===================================================================

def main():
    cfg = parse_config()
    username = cfg['username']
    os.makedirs(CHAT_DIR, exist_ok=True)
    backend = None
    display = None

    try:
        with open(USERNAME_FILE) as f:
            u = f.read().strip()
            if u:
                username = u
    except (FileNotFoundError, OSError):
        pass

    try:
        backend = ChatBackend(username, cfg)
        display = ChatDisplay()
        display.splash()

        # Use the configured/default name on first launch. Message entry is
        # exclusively handled by the native system TEXT_PICKER.
        if not username:
            username = 'PagerUser'
        if not os.path.isfile(USERNAME_FILE):
            try:
                with open(USERNAME_FILE, 'w') as f:
                    f.write(username)
            except OSError:
                pass
        backend.username = username

        backend.start()

        try:
            with open(MESSAGES_FILE) as f:
                backend.restore_messages(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        backend.add_message("System", "Chat ready. Press A to send.", "system")
        pending_message = read_pending_message()
        if pending_message:
            app_log(f"pending_message found len={len(pending_message)}")
            backend.send_message(pending_message)

        # Start at the bottom of the chronological transcript.
        scroll = 10**9
        running = True
        last_save = time.time()
        last_render = 0.0
        last_render_state = None
        last_message_revision = -1

        while running:
            msgs = backend.messages()
            pc = backend.peer_count()
            wo = backend.web_connected()
            message_revision = backend.message_revision()
            if message_revision != last_message_revision:
                # The deque can remain at 500 entries while a new web message
                # replaces the oldest one, so count changes are not a reliable
                # new-message signal. Follow revisions whenever the reader was
                # at the previous bottom; preserve deliberate history reading.
                previous_bottom = getattr(display, '_max_scroll', 0)
                if scroll >= previous_bottom:
                    scroll = 10**9
                last_message_revision = message_revision
            # LCD flips are relatively expensive on the Pager.  Render only
            # when visible state changes, plus a slow safety refresh, instead
            # of repainting the complete screen roughly 50 times per second.
            render_state = (message_revision, scroll, pc, wo,
                            msgs[-1].get('time') if msgs else None,
                            msgs[-1].get('text') if msgs else None)
            now = time.monotonic()
            if render_state != last_render_state or now - last_render >= 1.0:
                scroll = display.chat_view(msgs, scroll, pc, wo)
                last_render_state = (message_revision, scroll, pc, wo,
                                     msgs[-1].get('time') if msgs else None,
                                     msgs[-1].get('text') if msgs else None)
                last_render = now

            pressed = display.pressed_buttons()
            if not pressed:
                display.p.delay(50)
                continue
            display.activity()

            if pressed & Pager.BTN_UP:
                scroll -= 1
            elif pressed & Pager.BTN_DOWN:
                scroll += 1
            elif pressed & Pager.BTN_A:
                app_log("input A pressed; opening pagerctl keyboard")
                message = display.keyboard("DarkSec message:")
                if message:
                    app_log(f"inline keyboard accepted len={len(message)}")
                    backend.send_message(message)
                    scroll = 10**9
                    last_render_state = None
                else:
                    app_log("inline keyboard closed empty")
            elif pressed & Pager.BTN_B:
                a = display.pause_menu(pc, wo, len(msgs), backend.username, get_local_ip())
                if a in ('exit', 'menu'): running = False
            elif pressed & Pager.BTN_POWER:
                running = False

            if time.time() - last_save > 30:
                try:
                    with open(MESSAGES_FILE, 'w') as f:
                        json.dump(backend.messages(), f)
                    last_save = time.time()
                except OSError:
                    pass
            display.p.delay(50)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        app_log("fatal_error=%s\n%s" % (e, traceback.format_exc()))
        try:
            if display and display.p:
                display.p.clear(0x0000)
                display.p.draw_text_centered(60, "Error:", Pager.RED, 2)
                display.p.draw_text_centered(90, str(e)[:40], Pager.WHITE, 1)
                display.p.draw_text_centered(120, "Check logs", Pager.GRAY, 1)
                display.p.flip()
                time.sleep(3)
            else:
                print(f"Error before display init: {e}")
        except Exception:
            print(f"Error: {e}")
    finally:
        if backend:
            backend.stop()
            try:
                with open(MESSAGES_FILE, 'w') as f:
                    json.dump(backend.messages(), f)
            except OSError:
                pass
        if display:
            display.cleanup()


if __name__ == "__main__":
    main()
