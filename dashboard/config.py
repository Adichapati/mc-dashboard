import json
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict

from dotenv import load_dotenv

load_dotenv('/root/openclaw-dashboard/.env')

APP_NAME = 'OpenClaw-style MC Dashboard'
BIND_HOST = os.environ.get('BIND_HOST', '0.0.0.0')
BIND_PORT = int(os.environ.get('BIND_PORT', '18789'))

MINECRAFT_DIR = Path(os.environ.get('MINECRAFT_DIR', '/root/minecraft-1.21.11')).resolve()
LOG_FILE = MINECRAFT_DIR / 'logs/latest.log'
SERVER_PROPERTIES_PATH = MINECRAFT_DIR / 'server.properties'
OPS_FILE = MINECRAFT_DIR / 'ops.json'
WHITELIST_FILE = MINECRAFT_DIR / 'whitelist.json'
BANNED_PLAYERS_FILE = MINECRAFT_DIR / 'banned-players.json'
BACKUPS_DIR = MINECRAFT_DIR / 'backups'

DATA_DIR = Path('/root/openclaw-dashboard/data')
SCHEDULES_PATH = DATA_DIR / 'schedules.json'
PLUGINS_DIR = DATA_DIR / 'plugin_staging'
PLUGINS_INDEX_PATH = DATA_DIR / 'plugins-staged.json'
KNOWN_PLAYERS_PATH = DATA_DIR / 'known_players.json'
JOIN_WATCH_STATE_PATH = DATA_DIR / 'join_watch_state.json'
OP_ASSIST_STATE_PATH = DATA_DIR / 'op_assist_state.json'

MC_HOST = os.environ.get('MC_HOST', '127.0.0.1')
MC_PORT = int(os.environ.get('MC_PORT', '25565'))
TMUX_SESSION = os.environ.get('MC_TMUX_SESSION', 'mcserver')

AUTH_USERNAME = os.environ.get('AUTH_USERNAME', 'sprake')
AUTH_PASSWORD_HASH = os.environ.get('AUTH_PASSWORD_HASH', '')
AUTH_GUEST_USERNAME = os.environ.get('AUTH_GUEST_USERNAME', 'guest')
AUTH_GUEST_PASSWORD_HASH = os.environ.get('AUTH_GUEST_PASSWORD_HASH', '')
SESSION_SECRET = os.environ.get('SESSION_SECRET', secrets.token_urlsafe(32))
PUBLIC_READ_TOKEN = os.environ.get('PUBLIC_READ_TOKEN', 'public-readonly-change-me')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

WILSON_AI_ENABLED = os.environ.get('WILSON_AI_ENABLED', 'true').lower() == 'true'
WILSON_AI_PROVIDER = os.environ.get('WILSON_AI_PROVIDER', 'copilot')
WILSON_AI_BASE_URL = os.environ.get('WILSON_AI_BASE_URL', 'https://api.githubcopilot.com/chat/completions')
WILSON_AI_MODEL = os.environ.get('WILSON_AI_MODEL', 'gpt-4o-mini')
WILSON_AI_TOKEN = os.environ.get('WILSON_AI_TOKEN', os.environ.get('COPILOT_GITHUB_TOKEN', ''))
WILSON_OP_COOLDOWN_SEC = float(os.environ.get('WILSON_OP_COOLDOWN_SEC', '2.5'))
WILSON_CONFIRM_TTL_SEC = int(os.environ.get('WILSON_CONFIRM_TTL_SEC', '45'))
WILSON_MAX_REPLY_CHARS = int(os.environ.get('WILSON_MAX_REPLY_CHARS', '220'))

MAX_ATTEMPTS = 5
ATTEMPT_WINDOW_SEC = 300
LOCKOUT_SEC = 900
_attempts: Dict[str, Deque[float]] = defaultdict(deque)
_lockouts: Dict[str, float] = {}

_ws_tickets: Dict[str, float] = {}

state: Dict[str, Any] = {
    'auto_start': True,
    'auto_stop': True,
    'last_action': 'none',
    'last_status_note': 'dashboard started',
    'no_player_since': None,
}

_cache: Dict[str, Any] = {
    'snapshot': None,
    'logs': 'No logs yet.',
    'updated_at': 0.0,
}

_metrics_hist: Deque[Dict[str, float]] = deque(maxlen=180)
_player_hist: Deque[Dict[str, float]] = deque(maxlen=180)
_public_ip_cache = {'value': '127.0.0.1', 'expires_at': 0.0}
_console_history: Deque[str] = deque(maxlen=200)

_scheduler: Dict[str, Any] = {
    'restart_minutes': 0,
    'backup_minutes': 0,
    'last_restart_at': 0.0,
    'last_backup_at': 0.0,
}

_console_policy: Dict[str, Any] = {
    'tier': 'safe',  # safe | moderate | admin
}


def now_ts() -> float:
    return time.time()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)


def load_scheduler() -> None:
    if not SCHEDULES_PATH.exists():
        return
    try:
        data = json.loads(SCHEDULES_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            _scheduler.update({
                'restart_minutes': int(data.get('restart_minutes', 0) or 0),
                'backup_minutes': int(data.get('backup_minutes', 0) or 0),
                'last_restart_at': float(data.get('last_restart_at', 0) or 0),
                'last_backup_at': float(data.get('last_backup_at', 0) or 0),
            })
    except Exception:
        pass


def save_scheduler() -> None:
    SCHEDULES_PATH.write_text(json.dumps(_scheduler, indent=2), encoding='utf-8')


def load_plugins_index() -> list[dict]:
    if not PLUGINS_INDEX_PATH.exists():
        return []
    try:
        data = json.loads(PLUGINS_INDEX_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_plugins_index(items: list[dict]) -> None:
    PLUGINS_INDEX_PATH.write_text(json.dumps(items, indent=2), encoding='utf-8')


def load_known_players() -> list[str]:
    if not KNOWN_PLAYERS_PATH.exists():
        return []
    try:
        data = json.loads(KNOWN_PLAYERS_PATH.read_text(encoding='utf-8'))
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except Exception:
        pass
    return []


def save_known_players(players: list[str]) -> None:
    KNOWN_PLAYERS_PATH.write_text(json.dumps(sorted(set(players)), indent=2), encoding='utf-8')


def load_join_watch_state() -> dict:
    if not JOIN_WATCH_STATE_PATH.exists():
        return {'log_offset': 0}
    try:
        data = json.loads(JOIN_WATCH_STATE_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return {'log_offset': int(data.get('log_offset', 0) or 0)}
    except Exception:
        pass
    return {'log_offset': 0}


def save_join_watch_state(state: dict) -> None:
    JOIN_WATCH_STATE_PATH.write_text(json.dumps({'log_offset': int(state.get('log_offset', 0) or 0)}, indent=2), encoding='utf-8')


def load_op_assist_state() -> dict:
    if not OP_ASSIST_STATE_PATH.exists():
        return {'log_offset': 0}
    try:
        data = json.loads(OP_ASSIST_STATE_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return {'log_offset': int(data.get('log_offset', 0) or 0)}
    except Exception:
        pass
    return {'log_offset': 0}


def save_op_assist_state(state: dict) -> None:
    OP_ASSIST_STATE_PATH.write_text(json.dumps({'log_offset': int(state.get('log_offset', 0) or 0)}, indent=2), encoding='utf-8')
