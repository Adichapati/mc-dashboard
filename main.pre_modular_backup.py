import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import subprocess
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict

import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from mcstatus import JavaServer
from starlette.middleware.sessions import SessionMiddleware

load_dotenv('/root/openclaw-dashboard/.env')

APP_NAME = 'OpenClaw-style MC Dashboard'
BIND_HOST = os.environ.get('BIND_HOST', '0.0.0.0')
BIND_PORT = int(os.environ.get('BIND_PORT', '18789'))

MINECRAFT_DIR = '/root/minecraft-1.21.11'
LOG_FILE = f'{MINECRAFT_DIR}/logs/latest.log'
MC_HOST = '127.0.0.1'
MC_PORT = 25565

AUTH_USERNAME = os.environ.get('AUTH_USERNAME', 'sprake')
AUTH_PASSWORD_HASH = os.environ.get('AUTH_PASSWORD_HASH', '')
SESSION_SECRET = os.environ.get('SESSION_SECRET', secrets.token_urlsafe(32))
PUBLIC_READ_TOKEN = os.environ.get('PUBLIC_READ_TOKEN', 'public-readonly-change-me')

# Login hardening
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW_SEC = 300
LOCKOUT_SEC = 900
_attempts: Dict[str, Deque[float]] = defaultdict(deque)
_lockouts: Dict[str, float] = {}

# One-time WS tickets
_ws_tickets: Dict[str, float] = {}

# Runtime state
state: Dict[str, Any] = {
    'auto_start': False,
    'auto_stop': True,
    'last_action': 'none',
    'last_status_note': 'dashboard started',
    'no_player_since': None,
}

# Cached data to keep CPU/network overhead low
_cache: Dict[str, Any] = {
    'snapshot': None,
    'logs': 'No logs yet.',
    'updated_at': 0.0,
}
_metrics_hist: Deque[Dict[str, float]] = deque(maxlen=30)
_public_ip_cache = {'value': '127.0.0.1', 'expires_at': 0.0}


app = FastAPI(title=APP_NAME)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 12,
    same_site='lax',
    https_only=False,
)


def run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True, capture_output=True)


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        iterations = int(iters)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def client_key(request: Request, username: str) -> str:
    ip = request.headers.get('x-forwarded-for', '').split(',')[0].strip() or (request.client.host if request.client else 'unknown')
    return f'{ip}:{username.lower()}'


def prune_attempts(key: str, now: float) -> None:
    q = _attempts[key]
    while q and now - q[0] > ATTEMPT_WINDOW_SEC:
        q.popleft()


def is_locked(key: str, now: float) -> bool:
    until = _lockouts.get(key)
    if until and now < until:
        return True
    if until and now >= until:
        _lockouts.pop(key, None)
    return False


def register_failed_attempt(key: str, now: float) -> None:
    q = _attempts[key]
    q.append(now)
    prune_attempts(key, now)
    if len(q) >= MAX_ATTEMPTS:
        _lockouts[key] = now + LOCKOUT_SEC
        q.clear()


def require_session(request: Request) -> str:
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail='Unauthorized')
    return user


def mc_running() -> bool:
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = (proc.info.get('name') or '').lower()
            cmd = ' '.join(proc.info.get('cmdline') or [])
            if 'java' in name and 'server.jar' in cmd:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def mc_query() -> Dict[str, Any]:
    try:
        server = JavaServer(MC_HOST, MC_PORT, timeout=0.6)
        status = server.status()
        return {
            'online': True,
            'latency_ms': round(status.latency, 1),
            'version': getattr(status.version, 'name', 'unknown'),
            'players_online': int(getattr(status.players, 'online', 0)),
            'players_max': int(getattr(status.players, 'max', 20)),
        }
    except Exception:
        return {
            'online': False,
            'latency_ms': None,
            'version': '1.21.11',
            'players_online': 0,
            'players_max': 20,
        }


def public_ip_cached() -> str:
    now = time.time()
    if _public_ip_cache['expires_at'] > now:
        return _public_ip_cache['value']
    try:
        ip = subprocess.check_output('curl -s https://api.ipify.org', shell=True, text=True, timeout=3).strip()
        if ip:
            _public_ip_cache['value'] = ip
            _public_ip_cache['expires_at'] = now + 600  # refresh every 10 min
            return ip
    except Exception:
        pass
    _public_ip_cache['expires_at'] = now + 120
    return _public_ip_cache['value']


def read_logs(lines: int = 120) -> str:
    if not os.path.exists(LOG_FILE):
        return 'No logs yet.'
    cp = run(f'tail -n {lines} {LOG_FILE}')
    return cp.stdout.strip() if cp.returncode == 0 else (cp.stderr.strip() or 'Failed to read logs')


def start_server() -> str:
    if mc_running():
        return 'already running'
    cp = run(f'cd {MINECRAFT_DIR} && nohup ./start.sh > /tmp/minecraft-server.out 2>&1 &')
    state['last_action'] = 'start'
    state['last_status_note'] = 'start command sent'
    return 'started' if cp.returncode == 0 else f'failed: {cp.stderr.strip()}'


def stop_server() -> str:
    cp = run("pkill -f 'server.jar' || true")
    state['last_action'] = 'stop'
    state['last_status_note'] = 'stop command sent'
    return 'stopped' if cp.returncode == 0 else f'failed: {cp.stderr.strip()}'


def restart_server() -> str:
    run("pkill -f 'server.jar' || true")
    time.sleep(1)
    cp = run(f'cd {MINECRAFT_DIR} && nohup ./start.sh > /tmp/minecraft-server.out 2>&1 &')
    state['last_action'] = 'restart'
    state['last_status_note'] = 'restart command sent'
    return 'restarted' if cp.returncode == 0 else f'failed: {cp.stderr.strip()}'


def build_snapshot() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=None)
    mq = mc_query()
    ip = public_ip_cached()

    _metrics_hist.append({'cpu': round(cpu, 1), 'ram': round(vm.percent, 1), 't': time.time()})

    return {
        'running': mc_running(),
        'server_info': {
            'host': f'{MC_HOST}:{MC_PORT}',
            'public': f'{ip}:{MC_PORT}',
            'version': mq['version'],
            'players': f"{mq['players_online']}/{mq['players_max']}",
            'players_online': mq['players_online'],
            'players_max': mq['players_max'],
            'latency_ms': mq['latency_ms'],
        },
        'dashboard': {
            'bind': f'{BIND_HOST}:{BIND_PORT}',
            'private_link': f'http://{ip}:{BIND_PORT}/',
            'public_readonly_link': f'http://{ip}:{BIND_PORT}/public/{PUBLIC_READ_TOKEN}',
        },
        'metrics': {
            'cpu_percent': round(cpu, 1),
            'memory_percent': round(vm.percent, 1),
            'memory_used_gb': round((vm.total - vm.available) / (1024 ** 3), 2),
            'memory_total_gb': round(vm.total / (1024 ** 3), 2),
            'cpu_hist': [p['cpu'] for p in _metrics_hist],
            'ram_hist': [p['ram'] for p in _metrics_hist],
        },
        'automation': {
            'auto_start': state['auto_start'],
            'auto_stop': state['auto_stop'],
            'last_status_note': state['last_status_note'],
            'last_action': state['last_action'],
        }
    }


def get_snapshot() -> Dict[str, Any]:
    if _cache['snapshot'] is None:
        _cache['snapshot'] = build_snapshot()
        _cache['updated_at'] = time.time()
    return _cache['snapshot']


def get_logs() -> str:
    return _cache['logs']


def spark(values: list[float]) -> str:
    bars = '▁▂▃▄▅▆▇█'
    if not values:
        return ''
    out = []
    for v in values:
        # Use absolute 0..100 scale so graph reflects real utilization,
        # not relative min/max of the current window.
        vv = max(0.0, min(100.0, float(v)))
        idx = int((vv / 100.0) * (len(bars) - 1))
        out.append(bars[idx])
    return ''.join(out[-30:])


LOGIN_HTML = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Sign in</title>
<style>
:root{--bg:#ffe66d;--ink:#111;--paper:#fff;--accent:#7cf29a;--blue:#77b8ff}
*{box-sizing:border-box} body{font-family:'Space Grotesk',Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink);display:grid;place-items:center;min-height:100vh;margin:0;padding:20px}
.stack{width:min(94vw,420px)} .card{background:var(--paper);border:4px solid var(--ink);border-radius:18px;padding:22px;box-shadow:8px 8px 0 var(--ink)}
.badge{display:inline-block;background:var(--blue);border:3px solid var(--ink);border-radius:999px;padding:5px 10px;font-weight:800;font-size:12px;transform:rotate(-2deg)}
h2{margin:10px 0 14px 0;font-size:34px;line-height:1} label{font-weight:800;font-size:13px;display:block;margin:7px 0 6px}
input{width:100%;padding:12px 13px;border-radius:12px;border:3px solid var(--ink);background:#fff;color:#111;font-size:15px;outline:none;box-shadow:4px 4px 0 var(--ink)}
input:focus{transform:translate(-1px,-1px);box-shadow:6px 6px 0 var(--ink)}
button{width:100%;padding:12px;border-radius:12px;border:3px solid var(--ink);background:var(--accent);color:#111;font-weight:900;cursor:pointer;box-shadow:4px 4px 0 var(--ink);font-size:15px}
button:active{transform:translate(2px,2px);box-shadow:2px 2px 0 var(--ink)}
.err{min-height:22px;font-weight:700;color:#b00020} .note{font-size:12px;font-weight:700;opacity:.85}
</style>
<link href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700;800&display=swap' rel='stylesheet'>
</head><body><div class='stack'><div class='card'>
<span class='badge'>MC CONTROL</span><h2>Sign in</h2><div class='err' id='err'></div>
<label>Username</label><input id='u' placeholder='sprake' autocomplete='username'/>
<label>Password</label><input id='p' type='password' placeholder='••••••••' autocomplete='current-password'/>
<button onclick='login()'>LET ME IN</button>
<p class='note'>Protected dashboard • brute-force lockout enabled</p>
</div></div>
<script>
async function login(){
 const username=document.getElementById('u').value;
 const password=document.getElementById('p').value;
 const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
 const j=await r.json().catch(()=>({error:'login failed'}));
 if(r.ok){ location.href='/'; } else { document.getElementById('err').textContent=j.error||'Login failed'; }
}
document.getElementById('p').addEventListener('keydown',(e)=>{if(e.key==='Enter')login();});
</script></body></html>
"""


DASH_HTML = """
<!doctype html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width, initial-scale=1'/><title>MC Dashboard</title>
<link href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700;800&display=swap' rel='stylesheet'>
<style>
:root{--bg:#ffe66d;--ink:#101010;--paper:#fff;--mint:#7cf29a;--pink:#ff8fab;--blue:#77b8ff;--orange:#ffb347;--purple:#b29bff}
*{box-sizing:border-box} body{font-family:'Space Grotesk',Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink);margin:0}
.wrap{max-width:1120px;margin:18px auto;padding:0 14px}.card{background:var(--paper);border:4px solid var(--ink);border-radius:18px;padding:14px;margin-bottom:14px;box-shadow:8px 8px 0 var(--ink)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:980px){.grid,.grid3{grid-template-columns:1fr}}
.btn{border:3px solid var(--ink);padding:10px 14px;border-radius:12px;font-weight:900;cursor:pointer;margin-right:8px;margin-top:8px;box-shadow:4px 4px 0 var(--ink);color:#111}
.btn:active{transform:translate(2px,2px);box-shadow:2px 2px 0 var(--ink)} .start{background:var(--mint)}.stop{background:#ff7b7b}.restart{background:var(--blue)}.ghost{background:#fff}
.tag{display:inline-block;padding:5px 11px;border-radius:999px;border:3px solid var(--ink);font-weight:800;font-size:12px;box-shadow:3px 3px 0 var(--ink)}
.tag.status{background:var(--purple)}.tag.logs{background:var(--orange)}.tag.live{background:var(--pink)}
.k{font-weight:700;opacity:.86}.big{font-size:28px;font-weight:900;letter-spacing:.4px}.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}
pre{background:#fff;border:3px solid var(--ink);border-radius:12px;padding:10px;max-height:300px;overflow:auto;box-shadow:4px 4px 0 var(--ink);font-family:ui-monospace,Consolas,monospace}
.spark{font-family:ui-monospace,Consolas,monospace;font-size:16px;letter-spacing:0;opacity:.9;display:block;height:22px;line-height:22px;white-space:nowrap;overflow:hidden;text-overflow:clip}
.linkline{margin-top:8px;display:flex;gap:8px;align-items:flex-start}
.linklabel{font-weight:800;min-width:86px;flex:0 0 86px}
.linkvalue{flex:1;min-width:0;word-break:break-word;overflow-wrap:anywhere;line-height:1.35;color:#0a4ea3;text-decoration:underline}
</style></head><body><div class='wrap'>
<div class='card'><div style='display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap'>
<div><h2 style='margin:8px 0 0 0;font-size:32px'>Minecraft Dashboard</h2><div class='k'>Low-overhead live control panel</div></div>
<button class='btn ghost' onclick='logout()'>Logout</button></div></div>

<div class='card'><span class='tag status'>MINECRAFT STATUS</span>
<div class='big' id='running' style='margin-top:8px'>...</div><div class='k' id='serverinfo'>...</div>
<div style='margin-top:10px'><button class='btn start' onclick="act('start')">Start</button><button class='btn stop' onclick="act('stop')">Stop</button><button class='btn restart' onclick="act('restart')">Restart</button><button class='btn ghost' onclick="toggle('auto_start')">Auto-start</button><button class='btn ghost' onclick="toggle('auto_stop')">Auto-stop</button></div>
<div style='margin-top:8px' class='k' id='automsg'></div></div>

<div class='grid3'>
 <div class='card'><span class='tag' style='background:var(--blue)'>CPU</span><div class='big' id='cpu' style='margin-top:8px'>...</div></div>
 <div class='card'><span class='tag' style='background:var(--mint)'>RAM</span><div class='big' id='ram' style='margin-top:8px'>...</div><div class='k mono' id='ramd'></div></div>
 <div class='card'><span class='tag' style='background:var(--pink)'>LINKS</span><div class='mono linkline'><span class='linklabel'>Private:</span><a class='linkvalue' id='plink' href='#' target='_blank' rel='noopener noreferrer'></a></div><div class='mono linkline'><span class='linklabel'>Public RO:</span><a class='linkvalue' id='publicRead' href='#' target='_blank' rel='noopener noreferrer'></a></div></div>
</div>

<div class='card'><span class='tag logs'>SERVER LOGS</span><pre id='logs' style='margin-top:10px'>Loading...</pre></div>
</div>
<script>
let ws;
async function api(path,method='GET',body=null){
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
 if(r.status===401){location.href='/login';throw new Error('unauthorized');}
 const j=await r.json(); if(!r.ok) throw new Error(j.error||'request failed'); return j;
}
async function act(a){ await api(`/api/${a}`,'POST'); }
async function toggle(name){ await api(`/api/toggle/${name}`,'POST'); }
async function logout(){ await api('/api/logout','POST'); location.href='/login'; }
function render(d){
 document.getElementById('running').textContent = d.running ? 'RUNNING' : 'STOPPED';
 document.getElementById('running').style.color = d.running ? '#0b7f35' : '#b00020';
 document.getElementById('serverinfo').textContent = `${d.server_info.public} | Version: ${d.server_info.version} | Players: ${d.server_info.players}`;
 document.getElementById('cpu').textContent = `${d.metrics.cpu_percent}%`;
 document.getElementById('ram').textContent = `${d.metrics.memory_percent}%`;
 document.getElementById('ramd').textContent = `${d.metrics.memory_used_gb} GB / ${d.metrics.memory_total_gb} GB`;

 document.getElementById('automsg').textContent = `Auto-start: ${d.automation.auto_start ? 'ON':'OFF'} | Auto-stop: ${d.automation.auto_stop ? 'ON':'OFF'} | ${d.automation.last_status_note}`;
 const p=document.getElementById('plink');
 const pr=document.getElementById('publicRead');
 p.textContent = d.dashboard.private_link;
 p.href = d.dashboard.private_link;
 pr.textContent = d.dashboard.public_readonly_link;
 pr.href = d.dashboard.public_readonly_link;
}
async function refreshLogs(){ try{ const l=await api('/api/logs'); document.getElementById('logs').textContent=l.logs; }catch(e){} }
async function connectWS(){
 try{
  const t=await api('/api/ws-ticket');
  const scheme=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(`${scheme}://${location.host}/ws?ticket=${encodeURIComponent(t.ticket)}`);
  ws.onmessage=(ev)=>{ try{ render(JSON.parse(ev.data)); }catch(_){} };
  ws.onclose=()=>setTimeout(connectWS,3000);
 }catch(e){ setTimeout(connectWS,3000); }
}
connectWS(); setInterval(refreshLogs,12000); refreshLogs();
</script></body></html>
"""


PUBLIC_HTML = """
<!doctype html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width, initial-scale=1'/><title>Minecraft Public Status</title>
<link href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700;800&display=swap' rel='stylesheet'>
<style>
:root{--bg:#ffe66d;--ink:#101010;--paper:#fff;--blue:#77b8ff;--mint:#7cf29a;--purple:#b29bff}
*{box-sizing:border-box} body{font-family:'Space Grotesk',Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink);margin:0}
.wrap{max-width:900px;margin:18px auto;padding:0 14px}.card{background:var(--paper);border:4px solid var(--ink);border-radius:18px;padding:14px;margin-bottom:14px;box-shadow:8px 8px 0 var(--ink)}
.tag{display:inline-block;padding:5px 11px;border-radius:999px;border:3px solid var(--ink);font-weight:800;font-size:12px;box-shadow:3px 3px 0 var(--ink);background:var(--purple)}
.big{font-size:30px;font-weight:900;margin-top:8px}.k{font-weight:700;opacity:.9}.mono{font-family:ui-monospace,Consolas,monospace}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
</style></head><body><div class='wrap'>
<div class='card'><span class='tag'>PUBLIC • READ ONLY</span><h2 style='margin:8px 0 0 0'>Minecraft Server Status</h2></div>
<div class='card'><div class='big' id='running'>...</div><div class='k' id='serverinfo'>...</div></div>
<div class='grid'><div class='card'><div class='k'>CPU</div><div class='big' id='cpu'>...</div></div><div class='card'><div class='k'>RAM</div><div class='big' id='ram'>...</div><div class='k mono' id='ramd'></div></div></div>
</div>
<script>
const tok = location.pathname.split('/').pop();
async function refresh(){
 const r=await fetch(`/api/public/state/${encodeURIComponent(tok)}`);
 const d=await r.json();
 if(!r.ok){ throw new Error(d.error || 'forbidden'); }
 document.getElementById('running').textContent = d.running ? 'RUNNING' : 'STOPPED';
 document.getElementById('running').style.color = d.running ? '#0b7f35' : '#b00020';
 document.getElementById('serverinfo').textContent = `${d.server_info.public} | Version: ${d.server_info.version} | Players: ${d.server_info.players}`;
 document.getElementById('cpu').textContent = `${d.metrics.cpu_percent}%`;
 document.getElementById('ram').textContent = `${d.metrics.memory_percent}%`;
 document.getElementById('ramd').textContent = `${d.metrics.memory_used_gb} GB / ${d.metrics.memory_total_gb} GB`;
}
refresh(); setInterval(refresh,10000);
</script></body></html>
"""


@app.get('/login', response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get('user'):
        return RedirectResponse('/', status_code=302)
    return LOGIN_HTML


@app.post('/api/login')
async def api_login(request: Request):
    data = await request.json()
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))

    now = time.time()
    key = client_key(request, username or 'unknown')
    prune_attempts(key, now)
    if is_locked(key, now):
        return JSONResponse({'error': 'Too many failed attempts. Try again later.'}, status_code=429)

    user_ok = username == AUTH_USERNAME
    pass_ok = verify_password(password, AUTH_PASSWORD_HASH) if AUTH_PASSWORD_HASH else False

    if not (user_ok and pass_ok):
        register_failed_attempt(key, now)
        return JSONResponse({'error': 'Invalid username or password'}, status_code=401)

    request.session['user'] = username
    request.session['login_at'] = int(now)
    _attempts.pop(key, None)
    _lockouts.pop(key, None)
    return {'ok': True}


@app.post('/api/logout')
async def api_logout(request: Request):
    request.session.clear()
    return {'ok': True}


@app.get('/', response_class=HTMLResponse)
async def home(request: Request):
    if not request.session.get('user'):
        return RedirectResponse('/login', status_code=302)
    return DASH_HTML


@app.get('/public/{token}', response_class=HTMLResponse)
async def public_page(token: str):
    if token != PUBLIC_READ_TOKEN:
        raise HTTPException(status_code=404, detail='Not found')
    return PUBLIC_HTML


@app.get('/api/state')
async def api_state(request: Request):
    require_session(request)
    s = dict(get_snapshot())
    m = dict(s['metrics'])
    m['cpu_spark'] = spark(m.get('cpu_hist', []))
    m['ram_spark'] = spark(m.get('ram_hist', []))
    s['metrics'] = m
    return s


@app.get('/api/public/state/{token}')
async def api_public_state(token: str):
    if token != PUBLIC_READ_TOKEN:
        return JSONResponse({'error': 'forbidden'}, status_code=403)
    s = get_snapshot()
    return {
        'running': s['running'],
        'server_info': s['server_info'],
        'metrics': {
            'cpu_percent': s['metrics']['cpu_percent'],
            'memory_percent': s['metrics']['memory_percent'],
            'memory_used_gb': s['metrics']['memory_used_gb'],
            'memory_total_gb': s['metrics']['memory_total_gb'],
        },
    }


@app.get('/api/logs')
async def api_logs(request: Request):
    require_session(request)
    return {'logs': get_logs()}


@app.post('/api/start')
async def api_start(request: Request):
    require_session(request)
    return {'ok': True, 'message': start_server()}


@app.post('/api/stop')
async def api_stop(request: Request):
    require_session(request)
    return {'ok': True, 'message': stop_server()}


@app.post('/api/restart')
async def api_restart(request: Request):
    require_session(request)
    return {'ok': True, 'message': restart_server()}


@app.post('/api/toggle/{name}')
async def api_toggle(name: str, request: Request):
    require_session(request)
    if name not in ('auto_start', 'auto_stop'):
        return JSONResponse({'ok': False, 'error': 'unknown toggle'}, status_code=400)
    state[name] = not bool(state[name])
    state['last_action'] = f'toggle:{name}'
    state['last_status_note'] = f'{name} -> {state[name]}'
    return {'ok': True, 'name': name, 'value': state[name]}


@app.get('/api/ws-ticket')
async def api_ws_ticket(request: Request):
    require_session(request)
    ticket = secrets.token_urlsafe(24)
    _ws_tickets[ticket] = time.time() + 30
    return {'ticket': ticket}


@app.websocket('/ws')
async def ws_feed(ws: WebSocket):
    ticket = ws.query_params.get('ticket', '')
    exp = _ws_tickets.pop(ticket, 0)
    if not exp or exp < time.time():
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            s = dict(get_snapshot())
            m = dict(s['metrics'])
            m['cpu_spark'] = spark(m.get('cpu_hist', []))
            m['ram_spark'] = spark(m.get('ram_hist', []))
            s['metrics'] = m
            await ws.send_json(s)
            await asyncio.sleep(4)
    except WebSocketDisconnect:
        return


async def refresh_cache_loop():
    # Warm up non-blocking cpu counter
    psutil.cpu_percent(interval=None)
    while True:
        try:
            _cache['snapshot'] = build_snapshot()
            _cache['updated_at'] = time.time()
        except Exception:
            pass
        await asyncio.sleep(5)


async def refresh_logs_loop():
    while True:
        try:
            _cache['logs'] = read_logs(120)
        except Exception:
            pass
        await asyncio.sleep(8)


async def automation_loop():
    while True:
        try:
            now = time.time()
            # clean old ws tickets
            for t, exp in list(_ws_tickets.items()):
                if exp < now:
                    _ws_tickets.pop(t, None)

            s = get_snapshot()
            running = s['running']
            players_online = s['server_info']['players_online']

            if state['auto_start'] and not running:
                start_server()
                state['last_status_note'] = 'auto-start triggered (server was down)'

            if state['auto_stop'] and running:
                if players_online == 0:
                    if state['no_player_since'] is None:
                        state['no_player_since'] = now
                        state['last_status_note'] = 'No players detected, shutdown timer started'
                    elif now - state['no_player_since'] > 300:
                        stop_server()
                        state['last_status_note'] = 'Auto-stop triggered after 5m with no players'
                        state['no_player_since'] = None
                else:
                    state['no_player_since'] = None
                    state['last_status_note'] = 'Players online, auto-stop idle timer reset'
        except Exception:
            pass
        await asyncio.sleep(15)


@app.on_event('startup')
async def on_startup():
    asyncio.create_task(refresh_cache_loop())
    asyncio.create_task(refresh_logs_loop())
    asyncio.create_task(automation_loop())
