import json
import re
from pathlib import Path

from ..config import BANNED_PLAYERS_FILE, OPS_FILE, WHITELIST_FILE


class PlayerService:
    NAME_RE = re.compile(r'^[A-Za-z0-9_]{3,16}$')

    @staticmethod
    def validate_name(name: str) -> str:
        n = (name or '').strip()
        if not PlayerService.NAME_RE.match(n):
            raise ValueError('Invalid player name (3-16 chars, letters/numbers/_)')
        return n

    @staticmethod
    def read_json_list(path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    @staticmethod
    def _list_names(path: Path) -> list[str]:
        items = PlayerService.read_json_list(path)
        names = [str(x.get('name', '')).strip() for x in items if str(x.get('name', '')).strip()]
        return sorted(set(names), key=str.lower)

    @staticmethod
    def list_ops() -> list[str]:
        return PlayerService._list_names(OPS_FILE)

    @staticmethod
    def list_whitelist() -> list[str]:
        return PlayerService._list_names(WHITELIST_FILE)

    @staticmethod
    def list_banned() -> list[str]:
        return PlayerService._list_names(BANNED_PLAYERS_FILE)
