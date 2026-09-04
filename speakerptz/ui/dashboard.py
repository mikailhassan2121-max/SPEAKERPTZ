from __future__ import annotations

import copy
import json
import queue
import secrets
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


ALLOWED_ACTIONS = {
    "auto_toggle",
    "auto_on",
    "auto_off",
    "emergency_stop",
    "reset_stop",
    "wide",
    "manual_preset",
}


@dataclass(frozen=True)
class DashboardCommand:
    action: str
    camera_id: int | None = None
    preset: int | None = None


class DashboardState:
    """Thread-safe bridge between the HTTP UI and the real-time main loop."""

    def __init__(self, command_limit: int = 32, event_limit: int = 200, clock=None):
        self._lock = threading.RLock()
        self._commands: queue.Queue[DashboardCommand] = queue.Queue(maxsize=command_limit)
        self._events = deque(maxlen=event_limit)
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self.control_token = secrets.token_urlsafe(24)
        self._status = {
            "version": "",
            "mode_banner": "SIMULATION / DRY RUN",
            "real_control_enabled": False,
            "auto_enabled": False,
            "emergency_stopped": False,
            "active_speaker": None,
            "candidate_speaker": None,
            "confidence": 0.0,
            "detector_reason": "starting",
            "meters": [],
            "audio": {"ok": False, "device": "", "warning": "starting", "dante_status": "UNKNOWN"},
            "cameras": [],
            "current_camera_presets": {},
            "last_camera_request": "No camera request yet",
            "warnings": [],
        }

    def update(self, **fields) -> None:
        with self._lock:
            self._status.update(copy.deepcopy(fields))

    def add_event(self, kind: str, message: str, **fields) -> None:
        item = {
            "at": round(self._clock() - self._started, 3),
            "kind": str(kind),
            "message": str(message),
            **copy.deepcopy(fields),
        }
        with self._lock:
            self._events.append(item)

    def snapshot(self) -> dict:
        with self._lock:
            result = copy.deepcopy(self._status)
            result["uptime_seconds"] = round(self._clock() - self._started, 3)
            return result

    def events(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(200, int(limit)))
        with self._lock:
            return copy.deepcopy(list(self._events)[-limit:])

    def enqueue(self, action: str, camera_id=None, preset=None) -> tuple[bool, str]:
        action = str(action or "").strip().lower()
        if action not in ALLOWED_ACTIONS:
            return False, "Unsupported dashboard action."
        if action == "manual_preset":
            try:
                camera_id = int(camera_id)
                preset = int(preset)
            except (TypeError, ValueError):
                return False, "manual_preset requires integer camera_id and preset."
            if camera_id < 1 or preset < 0:
                return False, "camera_id must be positive and preset must be non-negative."
        else:
            camera_id = None
            preset = None
        try:
            self._commands.put_nowait(DashboardCommand(action, camera_id, preset))
        except queue.Full:
            return False, "Dashboard command queue is full; no command was accepted."
        return True, "Command queued for the main control loop."

    def drain_commands(self) -> list[DashboardCommand]:
        commands = []
        while True:
            try:
                commands.append(self._commands.get_nowait())
            except queue.Empty:
                return commands


def _dashboard_html(control_token: str) -> str:
    token_json = json.dumps(control_token)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SPEAKERPTZ Operator</title>
<style>
:root {{ color-scheme: dark; font-family: Inter,Segoe UI,sans-serif; background:#071014; color:#e9f5f5; }}
* {{ box-sizing:border-box; }} body {{ margin:0; min-height:100vh; background:radial-gradient(circle at top,#12323a,#071014 45%); }}
header {{ position:sticky; top:0; z-index:2; padding:16px 22px; background:#071014ee; border-bottom:1px solid #28505b; }}
.top {{ display:flex; justify-content:space-between; align-items:center; gap:16px; }}
h1 {{ font-size:20px; letter-spacing:.16em; margin:0; }} #mode {{ margin-top:12px; padding:13px; text-align:center; font-weight:900; letter-spacing:.12em; border-radius:8px; }}
.sim {{ background:#123f4b; color:#7de7ff; border:2px solid #2e9ab3; }} .real {{ background:#751b1b; color:#fff; border:3px solid #ff4d4d; animation:pulse 1.4s infinite; }}
@keyframes pulse {{ 50% {{ box-shadow:0 0 24px #ff333388; }} }}
main {{ max-width:1400px; margin:auto; padding:18px; display:grid; grid-template-columns:repeat(12,1fr); gap:14px; }}
.card {{ background:#0b1c22ee; border:1px solid #21434c; border-radius:10px; padding:16px; box-shadow:0 12px 30px #0005; }}
.controls {{ grid-column:span 12; }} .speaker {{ grid-column:span 4; }} .meters {{ grid-column:span 8; }} .health {{ grid-column:span 6; }} .events {{ grid-column:span 6; }}
h2 {{ margin:0 0 12px; font-size:13px; color:#82b9c5; letter-spacing:.11em; text-transform:uppercase; }}
button {{ border:1px solid #347284; background:#123842; color:white; border-radius:7px; padding:11px 15px; margin:4px; font-weight:700; cursor:pointer; }}
button:hover {{ background:#1a5260; }} .danger {{ background:#8c1818; border-color:#ff5a5a; }} .danger:hover {{ background:#b21f1f; }}
.primary {{ background:#126b53; border-color:#2bd6a2; }} input {{ width:90px; padding:10px; background:#061015; color:white; border:1px solid #35606a; border-radius:6px; }}
.big {{ font-size:29px; font-weight:800; }} .muted {{ color:#8aabb3; }} .warn {{ color:#ffbd59; }}
.meter {{ display:grid; grid-template-columns:130px 1fr 72px; gap:10px; align-items:center; margin:10px 0; }}
.track {{ height:13px; background:#061014; border-radius:7px; overflow:hidden; }} .fill {{ height:100%; background:linear-gradient(90deg,#1bb79a,#ffcf57,#ff5a5a); }}
table {{ width:100%; border-collapse:collapse; }} td,th {{ text-align:left; padding:8px; border-bottom:1px solid #17343c; }}
#eventList {{ max-height:300px; overflow:auto; font-family:Consolas,monospace; font-size:12px; }} .event {{ padding:7px 0; border-bottom:1px solid #17343c; }}
@media(max-width:900px) {{ .speaker,.meters,.health,.events {{ grid-column:span 12; }} }}
</style>
</head>
<body>
<header><div class="top"><h1>SPEAKERPTZ <span id="version"></span></h1><span id="uptime"></span></div><div id="mode" class="sim">SIMULATION / DRY RUN</div></header>
<main>
<section class="card controls"><h2>Operator controls</h2>
<button class="primary" onclick="send('auto_on')">AUTO ON</button><button class="danger" onclick="send('auto_off')">AUTO OFF</button><button onclick="send('wide')">WIDE</button>
<button class="danger" onclick="send('emergency_stop')">EMERGENCY STOP</button><button onclick="send('reset_stop')">RESET STOP</button>
<span style="margin-left:16px">Camera <input id="camera" type="number" min="1" value="1"> Preset <input id="preset" type="number" min="0" value="1">
<button onclick="manualPreset()">MANUAL PRESET</button></span></section>
<section class="card speaker"><h2>Speaker decision</h2><div id="active" class="big">NONE</div><p>Candidate: <b id="candidate">NONE</b></p><p>Confidence: <b id="confidence">0%</b></p><p id="reason" class="muted">starting</p><p>AUTO: <b id="auto">OFF</b></p></section>
<section class="card meters"><h2>Microphone meters</h2><div id="meters"></div></section>
<section class="card health"><h2>System health</h2><div id="warnings"></div><p id="audio"></p><p id="dante"></p><table><thead><tr><th>Camera</th><th>Status</th><th>Preset</th></tr></thead><tbody id="cameras"></tbody></table><p>Last request: <span id="last"></span></p></section>
<section class="card events"><h2>Recent events</h2><div id="eventList"></div></section>
</main>
<script>
const token={token_json}; let isReal=false;
const el=id=>document.getElementById(id); const text=(id,v)=>el(id).textContent=v;
const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]));
function duration(s){{s=Math.floor(s||0);return `${{Math.floor(s/3600)}}h ${{Math.floor((s%3600)/60)}}m ${{s%60}}s`;}}
async function send(action,data={{}}){{
 if(isReal && ['auto_toggle','auto_on','wide','manual_preset'].includes(action) && !confirm('REAL PTZ CONTROL IS ENABLED. Send this operator command?')) return;
 const response=await fetch('/api/command',{{method:'POST',headers:{{'Content-Type':'application/json','X-SpeakerPTZ-Token':token}},body:JSON.stringify({{action,...data}})}});
 const result=await response.json(); if(!response.ok) alert(result.error||'Command rejected');
}}
function manualPreset(){{send('manual_preset',{{camera_id:Number(el('camera').value),preset:Number(el('preset').value)}});}}
async function refresh(){{try{{const s=await (await fetch('/api/status',{{cache:'no-store'}})).json(); isReal=!!s.real_control_enabled;
 text('version','v'+s.version); text('uptime','UPTIME '+duration(s.uptime_seconds)); text('mode',s.mode_banner); el('mode').className=isReal?'real':'sim';
 text('active',s.active_speaker?.name||'NONE'); text('candidate',s.candidate_speaker?.name||'NONE'); text('confidence',Math.round((s.confidence||0)*100)+'%'); text('reason',s.detector_reason||''); text('auto',s.auto_enabled?'ON':'OFF');
 el('meters').innerHTML=(s.meters||[]).map(m=>`<div class="meter"><span>MIC ${{Number(m.channel)}} · ${{esc(m.name)}}</span><div class="track"><div class="fill" style="width:${{Math.max(0,Math.min(100,(m.level_db+70)*2))}}%"></div></div><span>${{Number(m.level_db).toFixed(1)}} dB<br>VAD ${{Math.round((m.speech_probability||0)*100)}}%</span></div>`).join('')||'<span class="muted">No audio data</span>';
 text('audio','Audio: '+(s.audio?.ok?'OK':'NOT READY')+' · '+(s.audio?.device||'')); text('dante','Dante/DVS: '+(s.audio?.dante_status||'UNKNOWN')); text('last',s.last_camera_request||'');
 el('warnings').innerHTML=(s.warnings||[]).map(w=>`<p class="warn">⚠ ${{esc(w)}}</p>`).join('');
 el('cameras').innerHTML=(s.cameras||[]).map(c=>`<tr><td>${{Number(c.id)}} · ${{esc(c.name)}}</td><td>${{esc(c.state)}}</td><td>${{s.current_camera_presets?.[c.id]??'—'}}</td></tr>`).join('');
 }}catch(e){{text('audio','Dashboard connection lost');}}}}
async function refreshEvents(){{try{{const rows=await (await fetch('/api/events?limit=60',{{cache:'no-store'}})).json();el('eventList').innerHTML=rows.map(e=>`<div class="event">+${{Number(e.at).toFixed(1)}}s [${{esc(e.kind)}}] ${{esc(e.message)}}</div>`).reverse().join('');}}catch(e){{}}}}
refresh();refreshEvents();setInterval(refresh,250);setInterval(refreshEvents,1000);
</script></body></html>"""


class DashboardServer:
    def __init__(self, state: DashboardState, host: str = "127.0.0.1", port: int = 8765):
        self.state = state
        self.host = str(host)
        self.port = int(port)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        port = self._server.server_port if self._server else self.port
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        display_host = f"[{host}]" if ":" in host else host
        return f"http://{display_host}:{port}"

    def _handler(self):
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            server_version = "SPEAKERPTZ/0.8"

            def log_message(self, format, *args):
                return

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'",
                )
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload) -> None:
                self._send(status, json.dumps(payload, separators=(",", ":")).encode(), "application/json")

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send(HTTPStatus.OK, _dashboard_html(state.control_token).encode(), "text/html; charset=utf-8")
                elif parsed.path == "/api/status":
                    self._json(HTTPStatus.OK, state.snapshot())
                elif parsed.path == "/api/events":
                    try:
                        query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
                        limit = int(query.get("limit", 50))
                    except ValueError:
                        limit = 50
                    self._json(HTTPStatus.OK, state.events(limit))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

            def do_POST(self):
                if urlparse(self.path).path != "/api/command":
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                    return
                if not secrets.compare_digest(self.headers.get("X-SpeakerPTZ-Token", ""), state.control_token):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid dashboard control token"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > 4096:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request size"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
                    return
                if not isinstance(payload, dict):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "Request must be an object"})
                    return
                accepted, message = state.enqueue(
                    payload.get("action"), payload.get("camera_id"), payload.get("preset")
                )
                if accepted:
                    self._json(HTTPStatus.ACCEPTED, {"accepted": True, "message": message})
                else:
                    self._json(HTTPStatus.BAD_REQUEST, {"accepted": False, "error": message})

        return Handler

    def start(self) -> str:
        if self._server is not None:
            return self.url
        server_class = ThreadingHTTPServer
        if ":" in self.host:
            class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
                address_family = socket.AF_INET6

            server_class = IPv6ThreadingHTTPServer
        self._server = server_class((self.host, self.port), self._handler())
        # Dashboard clients must never delay camera fail-safe shutdown. Request
        # threads are disposable views into state, not control owners.
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self._thread = threading.Thread(target=self._server.serve_forever, name="speakerptz-dashboard", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
