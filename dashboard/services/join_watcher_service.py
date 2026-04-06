import asyncio
import re

from ..config import (
    LOG_FILE,
    load_join_watch_state,
    load_known_players,
    save_join_watch_state,
    save_known_players,
)
from .server_service import ServerService

JOIN_RE = re.compile(r"]:\s+([A-Za-z0-9_]{3,16})\s+joined the game")


class JoinWatcherService:
    @staticmethod
    async def run_loop(notify_callback):
        state = load_join_watch_state()
        known = set(load_known_players())

        if LOG_FILE.exists() and state.get('log_offset', 0) <= 0:
            try:
                state['log_offset'] = LOG_FILE.stat().st_size
                save_join_watch_state(state)
            except Exception:
                pass

        while True:
            try:
                if not LOG_FILE.exists():
                    await asyncio.sleep(3)
                    continue

                size = LOG_FILE.stat().st_size
                offset = int(state.get('log_offset', 0) or 0)
                if offset < 0 or offset > size:
                    offset = max(0, size - 8192)

                if size > offset:
                    with LOG_FILE.open('rb') as f:
                        f.seek(offset)
                        raw = f.read(min(131072, size - offset))
                    chunk = raw.decode('utf-8', errors='replace')
                    state['log_offset'] = offset + len(raw)
                    save_join_watch_state(state)

                    for line in chunk.splitlines():
                        m = JOIN_RE.search(line)
                        if not m:
                            continue
                        user = m.group(1)
                        is_new = user not in known
                        if is_new:
                            known.add(user)
                            save_known_players(sorted(known))

                        # Send in-game greeting
                        greet = f"Wilson: {'Hello new friend' if is_new else 'Hey welcome back'}, {user}!"
                        ServerService.send_console_command(f"say {greet}", tier='admin', unsafe_ok=True)

                        # Telegram notify via callback
                        await notify_callback(user)

            except Exception:
                pass

            await asyncio.sleep(2)
