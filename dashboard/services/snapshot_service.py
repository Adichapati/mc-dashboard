import subprocess

import psutil

from ..config import (
    BIND_HOST,
    BIND_PORT,
    MC_PORT,
    PUBLIC_READ_TOKEN,
    _cache,
    _metrics_hist,
    _player_hist,
    _public_ip_cache,
    _scheduler,
    now_ts,
    state,
)
from .server_service import ServerService


def public_ip_cached() -> str:
    now = now_ts()
    if _public_ip_cache['expires_at'] > now:
        return _public_ip_cache['value']

    try:
        ip = subprocess.check_output('curl -s https://api.ipify.org', shell=True, text=True, timeout=3).strip()
        if ip:
            _public_ip_cache['value'] = ip
            _public_ip_cache['expires_at'] = now + 600
            return ip
    except Exception:
        pass

    _public_ip_cache['expires_at'] = now + 120
    return _public_ip_cache['value']


def build_snapshot() -> dict:
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=None)
    mq = ServerService.mc_query()
    ip = public_ip_cached()

    _metrics_hist.append({'cpu': round(cpu, 1), 'ram': round(vm.percent, 1), 't': now_ts()})
    _player_hist.append({'players': mq['players_online'], 'running': 1 if ServerService.is_running() else 0, 't': now_ts()})

    return {
        'running': ServerService.is_running(),
        'server_info': {
            'host': f'127.0.0.1:{MC_PORT}',
            'public': f'{ip}:{MC_PORT}',
            'version': mq['version'],
            'players': f"{mq['players_online']}/{mq['players_max']}",
            'players_online': mq['players_online'],
            'players_max': mq['players_max'],
            'player_names': mq.get('player_names', []),
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
        },
        'automation': {
            'auto_start': state['auto_start'],
            'auto_stop': state['auto_stop'],
            'last_status_note': state['last_status_note'],
            'last_action': state['last_action'],
            'restart_minutes': _scheduler.get('restart_minutes', 0),
            'backup_minutes': _scheduler.get('backup_minutes', 0),
        },
    }


def get_snapshot() -> dict:
    if _cache['snapshot'] is None:
        _cache['snapshot'] = build_snapshot()
        _cache['updated_at'] = now_ts()
    return _cache['snapshot']
