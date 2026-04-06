import asyncio
import urllib.parse
import urllib.request

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .auth import check_login, client_key, is_locked, prune_attempts, register_failed_attempt, require_session
from .config import (
    APP_NAME,
    PUBLIC_READ_TOKEN,
    SESSION_SECRET,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    _cache,
    _console_history,
    _console_policy,
    _scheduler,
    _ws_tickets,
    now_ts,
    save_scheduler,
    state,
)
from .services.config_service import PropertiesService
from .services.log_analytics_service import AnalyticsService, LogService
from .services.player_service import PlayerService
from .services.plugin_service import PluginService
from .services.server_service import ServerService
from .services.snapshot_service import build_snapshot, get_snapshot
from .services.world_service import SeedService, WorldService
from .services.join_watcher_service import JoinWatcherService
from .services.op_assist_service import OpAssistService
from .ui import dash_html, login_html, public_html

app = FastAPI(title=APP_NAME)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 12,
    same_site='lax',
    https_only=False,
)


async def _send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        qs = urllib.parse.urlencode({'chat_id': TELEGRAM_CHAT_ID, 'text': text})
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage?{qs}"
        with urllib.request.urlopen(url, timeout=8) as _r:
            _r.read(64)
    except Exception:
        pass


async def _on_player_join(username: str) -> None:
    await _send_telegram_message(f"{username} joined mc server")


@app.get('/login', response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get('user'):
        return RedirectResponse('/', status_code=302)
    return login_html()


@app.post('/api/login')
async def api_login(request: Request):
    data = await request.json()
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))

    now = now_ts()
    key = client_key(request, username or 'unknown')
    prune_attempts(key, now)
    if is_locked(key, now):
        return JSONResponse({'error': 'Too many failed attempts. Try again later.'}, status_code=429)

    if not check_login(username, password):
        register_failed_attempt(key, now)
        return JSONResponse({'error': 'Invalid username or password'}, status_code=401)

    request.session['user'] = username
    request.session['login_at'] = int(now)
    return {'ok': True}


@app.post('/api/logout')
async def api_logout(request: Request):
    request.session.clear()
    return {'ok': True}


@app.get('/', response_class=HTMLResponse)
async def home(request: Request):
    if not request.session.get('user'):
        return RedirectResponse('/login', status_code=302)
    return dash_html()


@app.get('/public/{token}', response_class=HTMLResponse)
async def public_page(token: str):
    if token != PUBLIC_READ_TOKEN:
        raise HTTPException(status_code=404, detail='Not found')
    return public_html()


@app.get('/api/state')
async def api_state(request: Request):
    require_session(request)
    return get_snapshot()


@app.get('/api/public/state/{token}')
async def api_public_state(token: str):
    if token != PUBLIC_READ_TOKEN:
        return JSONResponse({'error': 'forbidden'}, status_code=403)
    s = get_snapshot()
    return {
        'running': s['running'],
        'server_info': s['server_info'],
        'metrics': s['metrics'],
    }


@app.post('/api/start')
async def api_start(request: Request):
    require_session(request)
    return {'ok': True, 'message': ServerService.start()}


@app.post('/api/stop')
async def api_stop(request: Request):
    require_session(request)
    return {'ok': True, 'message': ServerService.stop()}


@app.post('/api/restart')
async def api_restart(request: Request):
    require_session(request)
    return {'ok': True, 'message': ServerService.restart()}


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
    ticket = __import__('secrets').token_urlsafe(24)
    _ws_tickets[ticket] = now_ts() + 30
    return {'ticket': ticket}


@app.websocket('/ws')
async def ws_feed(ws: WebSocket):
    ticket = ws.query_params.get('ticket', '')
    exp = _ws_tickets.pop(ticket, 0)
    if not exp or exp < now_ts():
        await ws.close(code=4401)
        return

    await ws.accept()
    log_offset = 0
    try:
        from .config import LOG_FILE
        if LOG_FILE.exists():
            log_offset = max(0, LOG_FILE.stat().st_size - 4096)
        while True:
            await ws.send_json({'type': 'snapshot', 'data': get_snapshot()})
            diff = LogService.diff_from(log_offset)
            log_offset = diff['next_offset']
            if diff['chunk']:
                await ws.send_json({'type': 'log', 'chunk': diff['chunk']})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@app.post('/api/console/send')
async def api_console_send(request: Request):
    require_session(request)
    data = await request.json()
    command = str(data.get('command', '')).strip()
    tier = str(data.get('tier', _console_policy.get('tier', 'safe'))).strip().lower()
    if tier not in ('safe', 'moderate', 'admin'):
        return JSONResponse({'error': 'Invalid tier'}, status_code=400)
    _console_policy['tier'] = tier
    res = ServerService.send_console_command(command, tier=tier)
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'failed')}, status_code=400)
    return {'ok': True, 'message': res.get('message', 'sent')}


@app.get('/api/console/history')
async def api_console_history(request: Request):
    require_session(request)
    return {'history': list(_console_history), 'tier': _console_policy.get('tier', 'safe')}


@app.get('/api/players/state')
async def api_players_state(request: Request):
    require_session(request)
    props = PropertiesService.read_all()
    snap = get_snapshot()
    return {
        'ops': PlayerService.list_ops(),
        'whitelist': PlayerService.list_whitelist(),
        'banned': PlayerService.list_banned(),
        'whitelist_enabled': props.get('white-list', 'false'),
        'online_players': snap.get('server_info', {}).get('player_names', []),
        'online_count': snap.get('server_info', {}).get('players_online', 0),
    }


@app.post('/api/players/action')
async def api_players_action(request: Request):
    require_session(request)
    data = await request.json()
    action = str(data.get('action', '')).strip()
    name = str(data.get('name', '')).strip()
    reason = str(data.get('reason', '')).strip()

    if action not in ('op', 'deop', 'whitelist_add', 'whitelist_remove', 'ban', 'pardon', 'kick'):
        return JSONResponse({'error': 'Unsupported action'}, status_code=400)

    try:
        name = PlayerService.validate_name(name)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)

    cmd = {
        'op': f'op {name}',
        'deop': f'deop {name}',
        'whitelist_add': f'whitelist add {name}',
        'whitelist_remove': f'whitelist remove {name}',
        'ban': f'ban {name} {reason}'.strip(),
        'pardon': f'pardon {name}',
        'kick': f'kick {name} {reason}'.strip(),
    }[action]

    res = ServerService.send_console_command(cmd, tier='admin')
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'failed')}, status_code=400)
    return {'ok': True, 'message': f'{action} sent for {name}'}


@app.post('/api/players/whitelist/toggle')
async def api_whitelist_toggle(request: Request):
    require_session(request)
    props = PropertiesService.read_all()
    enabled = props.get('white-list', 'false').lower() == 'true'
    new_val = 'false' if enabled else 'true'
    props['white-list'] = new_val
    props['enforce-whitelist'] = new_val
    PropertiesService.write_all(props)

    if ServerService.is_running() and ServerService.tmux_session_exists():
        ServerService.send_console_command(f'whitelist {"on" if new_val=="true" else "off"}', tier='admin')

    return {'ok': True, 'message': f'Whitelist now {new_val}'}


@app.get('/api/properties')
async def api_properties(request: Request):
    require_session(request)
    return {'values': PropertiesService.get_editable_view(), 'schema': PropertiesService.ALLOWED_EDIT_KEYS}


@app.post('/api/properties')
async def api_properties_save(request: Request):
    require_session(request)
    data = await request.json()
    updates = data.get('updates') or {}
    if not isinstance(updates, dict):
        return JSONResponse({'error': 'updates must be object'}, status_code=400)

    try:
        clean = PropertiesService.validate_updates(updates)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)

    props = PropertiesService.read_all()
    props.update(clean)
    PropertiesService.write_all(props)
    return {'ok': True, 'message': f'Applied {len(clean)} property changes'}


@app.get('/api/seed')
async def api_seed(request: Request):
    require_session(request)
    return {'seed': SeedService.get_seed()}


@app.post('/api/seed/generate')
async def api_seed_generate(request: Request):
    require_session(request)
    return {'seed': SeedService.random_seed()}


@app.post('/api/seed/apply')
async def api_seed_apply(request: Request):
    require_session(request)
    data = await request.json()
    res = SeedService.apply_seed(data.get('seed', ''))
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'failed')}, status_code=400)
    return res


@app.get('/api/world/backups')
async def api_world_backups(request: Request):
    require_session(request)
    return {'items': WorldService.list_backups()}


@app.post('/api/world/backup')
async def api_world_backup(request: Request):
    require_session(request)
    res = WorldService.create_backup()
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'backup failed')}, status_code=400)
    return {'ok': True, 'message': f"Backup created: {res['name']}", 'backup': res}


@app.post('/api/world/reset')
async def api_world_reset(request: Request):
    require_session(request)
    data = await request.json()
    return WorldService.reset_world(with_backup=bool(data.get('with_backup', True)), new_seed=data.get('new_seed', None))


@app.post('/api/world/restore')
async def api_world_restore(request: Request):
    require_session(request)
    data = await request.json()
    res = WorldService.restore_backup(str(data.get('name', '')).strip())
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'restore failed')}, status_code=400)
    return res


@app.get('/api/world/download-url')
async def api_world_download_url(request: Request):
    require_session(request)
    res = WorldService.create_backup()
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'download failed')}, status_code=400)
    return {'url': f"/api/world/download/{res['name']}"}


@app.get('/api/world/download/{name}')
async def api_world_download(name: str, request: Request):
    require_session(request)
    from .config import BACKUPS_DIR
    if '/' in name or '..' in name:
        raise HTTPException(status_code=400, detail='Invalid file')
    p = BACKUPS_DIR / name
    if not p.exists():
        raise HTTPException(status_code=404, detail='Not found')
    return FileResponse(path=str(p), filename=name, media_type='application/zip')


@app.post('/api/world/upload-b64')
async def api_world_upload_b64(request: Request):
    require_session(request)
    data = await request.json()
    res = WorldService.upload_world_zip_b64(str(data.get('archive_b64', '')), str(data.get('filename', 'uploaded-world.zip')))
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'upload failed')}, status_code=400)
    return res


@app.post('/api/world/upload')
async def api_world_upload(request: Request, file: UploadFile = File(...)):
    require_session(request)
    raw = await file.read()
    res = WorldService.upload_world_zip_bytes(raw, file.filename or 'uploaded-world.zip')
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'upload failed')}, status_code=400)
    return res


@app.get('/api/scheduler')
async def api_scheduler_get(request: Request):
    require_session(request)
    return _scheduler


@app.post('/api/scheduler')
async def api_scheduler_set(request: Request):
    require_session(request)
    data = await request.json()
    try:
        restart_minutes = int(data.get('restart_minutes', 0) or 0)
        backup_minutes = int(data.get('backup_minutes', 0) or 0)
    except Exception:
        return JSONResponse({'error': 'Invalid schedule values'}, status_code=400)

    if restart_minutes < 0 or backup_minutes < 0:
        return JSONResponse({'error': 'Schedule values must be >= 0'}, status_code=400)
    if restart_minutes > 10080 or backup_minutes > 10080:
        return JSONResponse({'error': 'Schedule values too large (max 10080 minutes)'}, status_code=400)

    _scheduler['restart_minutes'] = restart_minutes
    _scheduler['backup_minutes'] = backup_minutes
    save_scheduler()
    return {'ok': True, 'message': 'Schedule saved', 'scheduler': _scheduler}


@app.get('/api/analytics')
async def api_analytics(request: Request):
    require_session(request)
    return AnalyticsService.summary(hours=6)


@app.get('/api/plugins/catalog')
async def api_plugins_catalog(request: Request):
    require_session(request)
    return {'items': PluginService.catalog()}


@app.get('/api/plugins/staged')
async def api_plugins_staged(request: Request):
    require_session(request)
    return {'items': PluginService.staged()}


@app.post('/api/plugins/stage')
async def api_plugins_stage(request: Request):
    require_session(request)
    data = await request.json()
    res = PluginService.stage_from_catalog(str(data.get('id', '')))
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'failed')}, status_code=400)
    return res


@app.post('/api/plugins/remove')
async def api_plugins_remove(request: Request):
    require_session(request)
    data = await request.json()
    res = PluginService.remove_staged(str(data.get('file', '')))
    if not res.get('ok'):
        return JSONResponse({'error': res.get('error', 'failed')}, status_code=400)
    return res


async def refresh_cache_loop():
    import psutil
    psutil.cpu_percent(interval=None)
    while True:
        try:
            _cache['snapshot'] = build_snapshot()
            _cache['updated_at'] = now_ts()
        except Exception:
            pass
        await asyncio.sleep(3)


async def refresh_logs_loop():
    while True:
        try:
            _cache['logs'] = LogService.tail(140)
        except Exception:
            pass
        await asyncio.sleep(8)


async def automation_loop():
    first_cycle = True
    while True:
        try:
            now = now_ts()
            for t, exp in list(_ws_tickets.items()):
                if exp < now:
                    _ws_tickets.pop(t, None)

            s = get_snapshot()
            running = s['running']
            players_online = s['server_info']['players_online']

            # Skip immediate auto-start on process boot; keep toggle default ON for future checks.
            if (not first_cycle) and state['auto_start'] and not running:
                ServerService.start()
                state['last_status_note'] = 'auto-start triggered (server was down)'

            if state['auto_stop'] and running:
                if players_online == 0:
                    if state['no_player_since'] is None:
                        state['no_player_since'] = now
                        state['last_status_note'] = 'No players detected, shutdown timer started'
                    elif now - state['no_player_since'] > 300:
                        ServerService.stop()
                        state['last_status_note'] = 'Auto-stop triggered after 5m with no players'
                        state['no_player_since'] = None
                else:
                    state['no_player_since'] = None

            rmin = int(_scheduler.get('restart_minutes', 0) or 0)
            if rmin > 0 and running:
                last = float(_scheduler.get('last_restart_at', 0) or 0)
                if now - last >= rmin * 60:
                    ServerService.send_console_command('say [Dashboard] Scheduled restart in 10 seconds', tier='admin', unsafe_ok=True)
                    await asyncio.sleep(10)
                    ServerService.restart()
                    _scheduler['last_restart_at'] = now_ts()
                    save_scheduler()

            bmin = int(_scheduler.get('backup_minutes', 0) or 0)
            if bmin > 0:
                lastb = float(_scheduler.get('last_backup_at', 0) or 0)
                if now - lastb >= bmin * 60:
                    WorldService.create_backup()
                    _scheduler['last_backup_at'] = now_ts()
                    save_scheduler()

            first_cycle = False
        except Exception:
            pass
        await asyncio.sleep(15)


@app.on_event('startup')
async def on_startup():
    from .config import ensure_dirs, load_scheduler
    ensure_dirs()
    load_scheduler()
    # default preference: auto-start ON, without forcing immediate startup behavior
    state['auto_start'] = True
    asyncio.create_task(refresh_cache_loop())
    asyncio.create_task(refresh_logs_loop())
    asyncio.create_task(automation_loop())
    asyncio.create_task(JoinWatcherService.run_loop(_on_player_join))
    asyncio.create_task(OpAssistService.run_loop())
