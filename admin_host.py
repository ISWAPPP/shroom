#!/usr/bin/env python3
"""Shroom admin host: the portal's host-side operations (profile_admin.OPS) as a small root service, separate from
the owner's Hermes bridge. It holds no Hermes agent, so it stays ~30-50 MB and can be restarted at any time without
touching anyone's chat.

Socket: bridge-ipc/admin.sock (root:10001 0660, same Bearer token as the bridges). Endpoints:
  POST /admin  {"op": str, "args": {...}}  -> {"result": ...} | 400 {"error": ...}
  GET  /health                           -> {"ok": true, "ops": n, "loaded": <profile_admin mtime>}

Debugging:
  journalctl -u hermes-web-admin -f            one line per op: name, duration, ok/error (args are never logged)
  python3 admin_host.py call <op> '<json>'     run one op directly in this shell, no service needed
  python3 admin_host.py ops                    list op names
profile_admin.py is re-imported automatically when the file changes, so new or fixed ops go live without a restart.
Unit file: ops/hermes-web-admin.service (installed with `systemctl link`), code in git with the rest of the portal.
"""
import importlib, json, logging, os, socketserver, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TOKEN = (HERE / 'bridge.key').read_text().strip()
SOCKET = HERE / 'bridge-ipc' / 'admin.sock'
MODULE = HERE / 'profile_admin.py'
log = logging.getLogger('admin')
_lock = threading.Lock()
_mod, _mtime = None, 0.0


def admin_module():
    """profile_admin, re-imported when the file on disk changed (checked on every call; cheap stat)."""
    global _mod, _mtime
    m = MODULE.stat().st_mtime
    with _lock:
        if _mod is None or m != _mtime:
            if _mod is None:
                import profile_admin as fresh
            else:
                fresh = importlib.reload(_mod)
            _mod, _mtime = fresh, m
            log.info('loaded profile_admin (%d ops)', len(fresh.OPS))
        return _mod


def run(op, args):
    fn = admin_module().OPS.get(op)
    if not fn:
        raise KeyError('unknown op')
    return fn(args or {})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        return self.headers.get('Authorization') == 'Bearer ' + TOKEN

    def do_GET(self):
        if self.path != '/health':
            return self.reply(404, {'error': 'not found'})
        mod = admin_module()
        return self.reply(200, {'ok': True, 'ops': len(mod.OPS), 'loaded': _mtime, 'pid': os.getpid()})

    def do_POST(self):
        if not self.authorized():
            return self.reply(403, {'error': 'forbidden'})
        if self.path != '/admin':
            return self.reply(404, {'error': 'not found'})
        op, t = '?', time.time()
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 15_000_000:
                return self.reply(413, {'error': 'too large'})
            obj = json.loads(self.rfile.read(size))
            op = str(obj.get('op'))
            result = run(op, obj.get('args'))
            log.info('%s ok %.2fs', op, time.time() - t)
            return self.reply(200, {'result': result})
        except KeyError as exc:
            log.warning('%s error %.2fs: %s', op, time.time() - t, exc)
            return self.reply(400, {'error': 'unknown op' if str(exc) == "'unknown op'" else str(exc)})
        except (ValueError, subprocess.TimeoutExpired) as exc:
            log.warning('%s error %.2fs: %s', op, time.time() - t, str(exc)[:200])
            return self.reply(400, {'error': str(exc)})
        except Exception as exc:  # a bug in an op: full traceback to the journal, short message to the caller
            log.exception('%s crashed after %.2fs', op, time.time() - t)
            return self.reply(500, {'error': f'{type(exc).__name__}: {exc}'[:300]})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve():
    SOCKET.unlink(missing_ok=True)
    server = Server(str(SOCKET), Handler)
    os.chown(SOCKET, 0, 10001)
    os.chmod(SOCKET, 0o660)
    admin_module()
    log.info('listening on %s', SOCKET)
    server.serve_forever()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stdout)
    if len(sys.argv) > 1 and sys.argv[1] == 'ops':
        print('\n'.join(sorted(admin_module().OPS)))
    elif len(sys.argv) > 2 and sys.argv[1] == 'call':
        print(json.dumps(run(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}), ensure_ascii=False, indent=2, default=str))
    else:
        serve()
