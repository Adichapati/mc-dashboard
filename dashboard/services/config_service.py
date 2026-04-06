from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import SERVER_PROPERTIES_PATH


class PropertiesService:
    ALLOWED_EDIT_KEYS = {
        'difficulty': {'type': 'enum', 'choices': ['peaceful', 'easy', 'normal', 'hard']},
        'gamemode': {'type': 'enum', 'choices': ['survival', 'creative', 'adventure', 'spectator']},
        'max-players': {'type': 'int', 'min': 1, 'max': 200},
        'motd': {'type': 'str', 'max_len': 120},
        'pvp': {'type': 'bool'},
        'view-distance': {'type': 'int', 'min': 3, 'max': 32},
        'simulation-distance': {'type': 'int', 'min': 3, 'max': 32},
        'allow-flight': {'type': 'bool'},
        'white-list': {'type': 'bool'},
        'spawn-protection': {'type': 'int', 'min': 0, 'max': 64},
        'level-seed': {'type': 'str', 'max_len': 64},
        'online-mode': {'type': 'bool'},
        'enforce-secure-profile': {'type': 'bool'},
    }

    @staticmethod
    def read_all() -> dict[str, str]:
        out: dict[str, str] = {}
        if not SERVER_PROPERTIES_PATH.exists():
            return out
        for line in SERVER_PROPERTIES_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
        return out

    @staticmethod
    def write_all(values: dict[str, str]) -> None:
        lines = ['#Minecraft server properties', f'#Updated by dashboard {datetime.now(timezone.utc).isoformat()}']
        for k in sorted(values.keys()):
            lines.append(f'{k}={values[k]}')
        tmp = Path(str(SERVER_PROPERTIES_PATH) + '.tmp')
        tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        tmp.replace(SERVER_PROPERTIES_PATH)

    @staticmethod
    def normalize_bool(v: Any) -> str:
        if isinstance(v, bool):
            return 'true' if v else 'false'
        s = str(v).strip().lower()
        if s in ('1', 'true', 'yes', 'on'):
            return 'true'
        if s in ('0', 'false', 'no', 'off'):
            return 'false'
        raise ValueError('Invalid boolean')

    @staticmethod
    def validate_updates(updates: dict[str, Any]) -> dict[str, str]:
        clean: dict[str, str] = {}
        for key, val in updates.items():
            spec = PropertiesService.ALLOWED_EDIT_KEYS.get(key)
            if not spec:
                raise ValueError(f'Unsupported key: {key}')

            t = spec['type']
            if t == 'enum':
                s = str(val).strip().lower()
                if s not in spec['choices']:
                    raise ValueError(f'Invalid value for {key}')
                clean[key] = s
            elif t == 'int':
                try:
                    n = int(val)
                except Exception:
                    raise ValueError(f'{key} must be integer')
                if n < spec['min'] or n > spec['max']:
                    raise ValueError(f'{key} out of range ({spec["min"]}-{spec["max"]})')
                clean[key] = str(n)
            elif t == 'bool':
                clean[key] = PropertiesService.normalize_bool(val)
            else:
                s = str(val)
                if len(s) > spec['max_len']:
                    raise ValueError(f'{key} too long')
                clean[key] = s
        return clean

    @staticmethod
    def get_editable_view() -> dict[str, Any]:
        p = PropertiesService.read_all()
        return {k: p.get(k, '') for k in PropertiesService.ALLOWED_EDIT_KEYS}
