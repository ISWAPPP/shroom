"""Narrow HTTP bridge to supported Hermes TUI JSON-RPC stdio."""

import json, os, subprocess, threading, time, uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from interactions import Interactions

ROOT = '/root/.hermes/hermes-agent'
TOKEN = Path('/srv/hermes-web/bridge.key').read_text().strip()
import re as _re

PROFILE = os.environ.get('PORTAL_PROFILE', 'default')
if not _re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', PROFILE):
    raise RuntimeError('bad profile')
HOME = '/root/.hermes' if PROFILE == 'default' else '/root/.hermes/profiles/' + PROFILE
SUFFIX = '' if PROFILE == 'default' else '-' + PROFILE
PORTAL_ENV = {**os.environ, 'HERMES_HOME': HOME, 'HERMES_MANAGED_DIR': '/srv/hermes-web/managed-policy', 'HERMES_YOLO_MODE': '0'}
# Native managed-scope loading fails open on a missing/malformed file. Refuse startup instead.
for key, expected in [('approvals.mode', 'manual'), ('command_allowlist', '[]'), ('security.redact_secrets', 'true')]:
    checked = subprocess.run(['/root/.local/bin/hermes', 'config', 'get', key], env=PORTAL_ENV, capture_output=True, text=True, timeout=30)
    if checked.returncode or checked.stdout.strip().lower() != expected:
        raise RuntimeError('Portal safety policy is unavailable; refusing to start')
proc = subprocess.Popen(
    ['/root/.local/bin/hermes', '--run-module', 'tui_gateway.entry'],
    cwd=ROOT,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=open('/srv/hermes-web/bridge-runtime' + SUFFIX + '.log', 'a'),
    text=True,
    bufsize=1,
    env=PORTAL_ENV,
)
lock = threading.Lock()
pending = {}
events = deque(maxlen=2000)
serial = 0
epoch = uuid.uuid4().hex
outcomes = {}
ALLOWED = {
    'session.create',
    'session.resume',
    'session.history',
    'session.status',
    'session.interrupt',
    'prompt.submit',
    'file.attach',
    'image.attach_bytes',
    'image.detach',
    'session.events.since',
    'client.capabilities',
    'complete.slash',
    'slash.exec',
    'command.dispatch',
    'model.options',
    'session.undo',
    'session.title',
    'prompt.btw',
    'session.close',
    'session.delete',
    'skills.reload',
    'model.save_key',
    'model.disconnect',
    'llm.oneshot',
    'config.set',
    'session.steer',
    'prompt.background',
}


def send(obj):
    with lock:
        proc.stdin.write(json.dumps(obj) + '\n')
        proc.stdin.flush()


interactions = Interactions(send)


def read():
    global serial
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if 'id' in msg and 'method' not in msg:
            item = pending.get(str(msg['id']))
            if item:
                item['value'] = msg
                item['ready'].set()
        elif msg.get('method') == 'event':
            with lock:
                serial += 1
                event = {**msg.get('params', {}), 'seq': serial}
                events.append(event)
                if event.get('type') == 'message.complete':
                    outcomes[event.get('session_id')] = event.get('payload', {}).get('status', 'complete')
            if event.get('type') == 'request.cancel':
                interactions.cancel(event.get('payload', {}).get('id'))
        elif 'id' in msg:
            interactions.receive(msg)
    for item in list(pending.values()):
        item['value'] = {'error': {'message': 'Hermes process exited'}}
        item['ready'].set()


threading.Thread(target=read, daemon=True).start()
send({'jsonrpc': '2.0', 'id': 'capabilities', 'method': 'client.capabilities', 'params': {'server_requests': True}})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            return self.reply(403, {'error': 'forbidden'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 15000000:
                return self.reply(413, {'error': 'too large'})
            obj = json.loads(self.rfile.read(size))
            if self.path == '/admin':
                if PROFILE != 'default':
                    return self.reply(403, {'error': 'admin ops only on owner bridge'})
                import profile_admin

                op = profile_admin.OPS.get(obj.get('op'))
                if not op:
                    return self.reply(400, {'error': 'unknown op'})
                try:
                    return self.reply(200, {'result': op(obj.get('args', {}))})
                except (ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                    return self.reply(400, {'error': str(exc)})
            if self.path == '/events':
                sid = obj['session_id']
                after = int(obj.get('after', 0))
                with lock:
                    cursor = serial
                    result = [e for e in events if after < e['seq'] <= cursor and e.get('session_id') == sid]
                return self.reply(
                    200,
                    {
                        'events': result,
                        'cursor': cursor,
                        'epoch': epoch,
                        'outcome': outcomes.get(sid),
                        'truncated': bool(events and after and after < events[0]['seq'] - 1),
                        **interactions.snapshot(sid),
                    },
                )
            if self.path == '/respond':
                try:
                    return self.reply(200, interactions.respond(obj['session_id'], obj['request_id'], obj['result']))
                except ValueError as exc:
                    return self.reply(409, {'error': str(exc)})
            if self.path != '/rpc' or obj.get('method') not in ALLOWED:
                return self.reply(403, {'error': 'method not allowed'})
            if obj['method'] == 'config.set':  # only per-session yolo / model / reasoning; never global or other keys
                p = obj.get('params') or {}
                key = p.get('key')
                val = str(p.get('value') or '')
                ok = (
                    bool(p.get('session_id'))
                    and (p.get('scope') or 'session') == 'session'
                    and (
                        key == 'yolo'
                        or (key == 'model' and _re.fullmatch(r'[A-Za-z0-9._/@+-]{1,60}:[A-Za-z0-9._:/@+-]{1,120} --session', val))
                        or (key == 'reasoning' and val in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh'))
                    )
                )
                if not ok:
                    return self.reply(403, {'error': 'config key not allowed'})
            if obj['method'] == 'prompt.submit':
                outcomes.pop(obj.get('params', {}).get('session_id'), None)
            rid = uuid.uuid4().hex
            item = {'ready': threading.Event()}
            pending[rid] = item
            send({'jsonrpc': '2.0', 'id': rid, 'method': obj['method'], 'params': obj.get('params', {})})
            if not item['ready'].wait(180):
                pending.pop(rid, None)
                return self.reply(504, {'error': 'Hermes RPC timeout'})
            pending.pop(rid, None)
            self.reply(200, item['value'])
        except Exception as exc:
            self.reply(502, {'error': str(exc)})

    def reply(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


import socketserver


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


socket_path = '/srv/hermes-web/bridge-ipc/bridge' + SUFFIX + '.sock'
Path(socket_path).unlink(missing_ok=True)
try:
    server = UnixHTTPServer(socket_path, Handler)
    os.chown(socket_path, 0, 10001)
    os.chmod(socket_path, 0o660)
    server.serve_forever()
finally:
    proc.terminate()
