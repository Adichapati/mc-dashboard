import base64
import os
import shutil
import zipfile
from pathlib import Path

from ..config import BACKUPS_DIR, MINECRAFT_DIR, PLUGINS_DIR, utc_stamp
from .config_service import PropertiesService
from .server_service import ServerService


class SeedService:
    @staticmethod
    def random_seed() -> str:
        import random
        return str(random.randint(-(2**63) + 1, (2**63) - 1))

    @staticmethod
    def get_seed() -> str:
        return PropertiesService.read_all().get('level-seed', '')

    @staticmethod
    def apply_seed(seed: str) -> dict:
        s = str(seed).strip()
        if len(s) > 64:
            return {'ok': False, 'error': 'Seed too long (max 64)'}
        props = PropertiesService.read_all()
        props['level-seed'] = s
        PropertiesService.write_all(props)
        return {'ok': True, 'message': 'Seed updated.', 'seed': s}


class WorldService:
    @staticmethod
    def level_name() -> str:
        return PropertiesService.read_all().get('level-name', 'world') or 'world'

    @staticmethod
    def world_path() -> Path:
        return MINECRAFT_DIR / WorldService.level_name()

    @staticmethod
    def dimensions_paths(base_world: Path) -> list[Path]:
        return [base_world, MINECRAFT_DIR / f'{base_world.name}_nether', MINECRAFT_DIR / f'{base_world.name}_the_end']

    @staticmethod
    def ensure_backup_dir() -> None:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def create_backup() -> dict:
        world = WorldService.world_path()
        if not world.exists():
            return {'ok': False, 'error': f'World not found: {world}'}

        WorldService.ensure_backup_dir()
        out_path = BACKUPS_DIR / f'{world.name}-{utc_stamp()}.zip'

        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for base in WorldService.dimensions_paths(world):
                if not base.exists():
                    continue
                for root, _dirs, files in os.walk(base):
                    for fn in files:
                        fp = Path(root) / fn
                        arc = fp.relative_to(MINECRAFT_DIR)
                        zf.write(fp, arcname=str(arc))

        return {'ok': True, 'path': str(out_path), 'name': out_path.name}

    @staticmethod
    def list_backups(limit: int = 30) -> list[dict]:
        if not BACKUPS_DIR.exists():
            return []
        files = sorted(BACKUPS_DIR.glob('*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        return [{'name': p.name, 'size_mb': round(p.stat().st_size / (1024 * 1024), 2), 'updated_at': int(p.stat().st_mtime)} for p in files]

    @staticmethod
    def delete_world_files() -> None:
        world = WorldService.world_path()
        for p in WorldService.dimensions_paths(world):
            if p.exists():
                shutil.rmtree(p)

    @staticmethod
    def reset_world(with_backup: bool = True, new_seed: str | None = None) -> dict:
        was_running = ServerService.is_running()
        if was_running:
            ServerService.stop()

        backup_info = WorldService.create_backup() if with_backup else None
        if new_seed is not None:
            SeedService.apply_seed(new_seed)
        WorldService.delete_world_files()

        if was_running:
            ServerService.start()

        return {'ok': True, 'backup': backup_info, 'message': 'World reset complete'}

    @staticmethod
    def restore_backup(backup_name: str) -> dict:
        if '/' in backup_name or '..' in backup_name:
            return {'ok': False, 'error': 'Invalid backup name'}
        backup_path = BACKUPS_DIR / backup_name
        if not backup_path.exists():
            return {'ok': False, 'error': 'Backup not found'}

        was_running = ServerService.is_running()
        if was_running:
            ServerService.stop()

        WorldService.delete_world_files()
        with zipfile.ZipFile(backup_path, 'r') as zf:
            zf.extractall(MINECRAFT_DIR)

        if was_running:
            ServerService.start()

        return {'ok': True, 'message': f'Restored backup {backup_name}'}

    @staticmethod
    def upload_world_zip_b64(archive_b64: str, filename: str = 'uploaded-world.zip') -> dict:
        try:
            raw = base64.b64decode(archive_b64)
        except Exception:
            return {'ok': False, 'error': 'Invalid base64 payload'}
        return WorldService.upload_world_zip_bytes(raw, filename)

    @staticmethod
    def upload_world_zip_bytes(raw: bytes, filename: str = 'uploaded-world.zip') -> dict:
        if len(raw) > 200 * 1024 * 1024:
            return {'ok': False, 'error': 'Upload too large'}

        WorldService.ensure_backup_dir()
        safe_name = ''.join(c for c in filename if c.isalnum() or c in ('-', '_', '.')) or 'uploaded-world.zip'
        tmp_zip = BACKUPS_DIR / f'upload-{utc_stamp()}-{safe_name}'
        tmp_zip.write_bytes(raw)

        try:
            with zipfile.ZipFile(tmp_zip, 'r') as zf:
                test = zf.testzip()
                if test:
                    return {'ok': False, 'error': f'Corrupt zip member: {test}'}
        except Exception:
            return {'ok': False, 'error': 'Invalid zip archive'}

        was_running = ServerService.is_running()
        if was_running:
            ServerService.stop()

        WorldService.delete_world_files()
        with zipfile.ZipFile(tmp_zip, 'r') as zf:
            zf.extractall(MINECRAFT_DIR)

        if was_running:
            ServerService.start()

        return {'ok': True, 'message': 'World uploaded and applied', 'stored_as': tmp_zip.name}
