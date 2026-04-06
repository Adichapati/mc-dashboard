import hashlib
import json
import os
import urllib.request
from pathlib import Path

from ..config import PLUGINS_DIR, load_plugins_index, now_ts, save_plugins_index


class PluginService:
    # Safe curated skeleton list (can be expanded)
    CATALOG = [
        {
            'id': 'luckperms-bukkit',
            'name': 'LuckPerms (Bukkit)',
            'url': 'https://download.luckperms.net/1575/bukkit/loader/LuckPerms-Bukkit-5.4.121.jar',
            'kind': 'plugin',
        },
        {
            'id': 'vault',
            'name': 'Vault',
            'url': 'https://github.com/MilkBowl/Vault/releases/download/1.7.3/Vault.jar',
            'kind': 'plugin',
        },
        {
            'id': 'fabric-api-modrinth',
            'name': 'Fabric API (Modrinth)',
            'url': 'https://cdn.modrinth.com/data/P7dR8mSH/versions/latest/download',
            'kind': 'mod',
        },
    ]

    @staticmethod
    def catalog() -> list[dict]:
        return PluginService.CATALOG

    @staticmethod
    def staged() -> list[dict]:
        return load_plugins_index()

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def stage_from_catalog(item_id: str) -> dict:
        found = next((x for x in PluginService.CATALOG if x['id'] == item_id), None)
        if not found:
            return {'ok': False, 'error': 'Unknown catalog item'}

        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        out_name = f"{item_id}-{int(now_ts())}.jar"
        out_path = PLUGINS_DIR / out_name

        req = urllib.request.Request(found['url'], headers={'User-Agent': 'OpenClawDashboard/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read(120 * 1024 * 1024)
        except Exception as e:
            return {'ok': False, 'error': f'Download failed: {e}'}

        if not data or len(data) < 1024:
            return {'ok': False, 'error': 'Downloaded file is too small or invalid'}

        out_path.write_bytes(data)
        sha = PluginService._sha256(out_path)
        size_mb = round(len(data) / (1024 * 1024), 2)

        idx = load_plugins_index()
        entry = {
            'id': item_id,
            'name': found['name'],
            'kind': found['kind'],
            'url': found['url'],
            'file': out_name,
            'sha256': sha,
            'size_mb': size_mb,
            'staged_at': int(now_ts()),
            'status': 'staged',
        }
        idx.insert(0, entry)
        save_plugins_index(idx[:80])

        return {'ok': True, 'message': f"Staged {found['name']}", 'entry': entry}

    @staticmethod
    def remove_staged(file_name: str) -> dict:
        if '/' in file_name or '..' in file_name:
            return {'ok': False, 'error': 'Invalid file name'}
        p = PLUGINS_DIR / file_name
        if p.exists():
            os.remove(p)

        idx = [x for x in load_plugins_index() if x.get('file') != file_name]
        save_plugins_index(idx)
        return {'ok': True, 'message': 'Removed staged file'}
