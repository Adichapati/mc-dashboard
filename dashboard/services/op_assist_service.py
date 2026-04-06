import asyncio
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import (
    LOG_FILE,
    WILSON_AI_BASE_URL,
    WILSON_AI_ENABLED,
    WILSON_AI_MODEL,
    WILSON_AI_TOKEN,
    WILSON_MAX_REPLY_CHARS,
    WILSON_OP_COOLDOWN_SEC,
    load_op_assist_state,
    save_op_assist_state,
)
from .player_service import PlayerService
from .server_service import ServerService

CHAT_RE = re.compile(r"\]:\s*(?:\[[^\]]+\]\s*)?<([A-Za-z0-9_]{3,16})>\s*(.+)$")


class OpAssistService:
    BLOCKED_CMD_PATTERNS = [
        r'^stop\s*$',
        r'^restart\s*$',
        r'^reload\s*$',
        r'^save-off\s*$',
        r'^op\s+',
        r'^deop\s+',
        r'^whitelist\s+off\s*$',
        r'^ban-ip\s+',
        r'^pardon-ip\s+',
        r'^debug\s+',
        r'^perf\s+',
        r'.*\b(?:rm|sudo|chmod|chown|mv|cp)\b.*',
        r'.*(?:&&|\|\||;|`|\$\().*',
        r'.*\b(?:delete\s+world|wipe\s+world|format\s+disk)\b.*',
    ]


    # runtime memory (in-process)
    _last_seen_by_user: dict[str, float] = {}
    _chat_history: dict[str, list[dict]] = {}

    @staticmethod
    def _say(text: str):
        text = (text or '').strip()
        if not text:
            return
        if len(text) > WILSON_MAX_REPLY_CHARS:
            text = text[:WILSON_MAX_REPLY_CHARS - 1] + '…'
        ServerService.send_console_command(f"say Wilson: {text}", tier='admin', unsafe_ok=True)

    @staticmethod
    def _is_blocked(cmd: str) -> bool:
        c = (cmd or '').strip()
        for pat in OpAssistService.BLOCKED_CMD_PATTERNS:
            if re.match(pat, c, flags=re.IGNORECASE):
                return True
        return False



    @staticmethod
    def _extract_after_wilson(msg: str) -> str:
        parts = re.split(r'\bwilson\b', msg, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) < 2:
            return ''
        tail = parts[1].strip()
        tail = re.sub(r'^[\s:,.!\-]+', '', tail)
        if tail.startswith('/'):
            tail = tail[1:].strip()
        return tail

    @staticmethod
    def _add_history(user: str, role: str, text: str):
        buf = OpAssistService._chat_history.setdefault(user.lower(), [])
        buf.append({'role': role, 'content': text})
        if len(buf) > 10:
            del buf[:-10]

    @staticmethod
    def _llm_call(user: str, text: str) -> dict:
        # Fallback if LLM disabled or token missing
        if not WILSON_AI_ENABLED or not WILSON_AI_TOKEN:
            explicit = OpAssistService._extract_after_wilson(text)
            if explicit:
                return {'type': 'command', 'command': explicit, 'say': f"running: {explicit}"}
            return {'type': 'chat', 'say': f"Hey {user}, I'm online. Ask me with: Wilson <command>."}

        system_prompt = (
            "You are Wilson, a Minecraft OP assistant.\n"
            "Return STRICT JSON only with schema:\n"
            "{\"type\":\"chat\",\"say\":\"...\"} OR "
            "{\"type\":\"command\",\"command\":\"...\",\"say\":\"...\"}.\n"
            "Rules:\n"
            "- Be concise and friendly.\n"
            "- If user asks a normal question, use type=chat.\n"
            "- If user asks for action, produce one valid minecraft server command in command field (no slash prefix).\n"
            f"- The current player name is '{user}'. Use that exact name when targeting the player.\n"
            "- Commands run from server console context (not player chat), so target the user explicitly where needed.\n"
            f"- Example: for gamemode use 'gamemode creative {user}'.\n"
            f"- Example: for teleport to nether use 'execute in minecraft:the_nether run tp {user} 0 80 0'.\n"
            "- Never use placeholders like <playername>, <player>, {player}, playername.\n"
            "- Never output host shell commands.\n"
            "- Never include 'confirm' flow.\n"
        )

        # conversation memory per user
        hist = OpAssistService._chat_history.get(user.lower(), [])
        messages = [{'role': 'system', 'content': system_prompt}] + hist + [{'role': 'user', 'content': text}]

        payload = {
            'model': WILSON_AI_MODEL,
            'messages': messages,
            'temperature': 0.2,
        }
        body = json.dumps(payload).encode('utf-8')

        # Copilot-compatible endpoint requires api-version query param.
        url = WILSON_AI_BASE_URL
        if 'api.githubcopilot.com' in url and 'api-version=' not in url:
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}api-version=2025-04-01-preview"

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {WILSON_AI_TOKEN}',
                'User-Agent': 'OpenClawDashboard/Wilson',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            txt = e.read().decode('utf-8', errors='replace') if hasattr(e, 'read') else str(e)
            return {'type': 'chat', 'say': f"I hit API error ({e.code}). Try again."}
        except Exception:
            return {'type': 'chat', 'say': "I'm having connection issues right now. Try again in a moment."}

        # parse OpenAI-like response
        try:
            data = json.loads(raw)
            content = data['choices'][0]['message']['content']
        except Exception:
            return {'type': 'chat', 'say': "I couldn't parse the AI response. Try rephrasing."}

        # enforce JSON output parsing
        try:
            # strip code fences if any
            content = re.sub(r'^```(?:json)?\s*', '', content.strip(), flags=re.IGNORECASE)
            content = re.sub(r'\s*```$', '', content.strip())
            obj = json.loads(content)
            if not isinstance(obj, dict) or obj.get('type') not in ('chat', 'command'):
                raise ValueError('bad schema')
            return obj
        except Exception:
            # fallback: treat as chat
            return {'type': 'chat', 'say': content[:WILSON_MAX_REPLY_CHARS]}

    @staticmethod
    async def run_loop():
        state = load_op_assist_state()
        if LOG_FILE.exists() and state.get('log_offset', 0) <= 0:
            try:
                state['log_offset'] = LOG_FILE.stat().st_size
                save_op_assist_state(state)
            except Exception:
                pass

        while True:
            try:
                if not LOG_FILE.exists():
                    await asyncio.sleep(2)
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
                    save_op_assist_state(state)

                    ops = set(name.lower() for name in PlayerService.list_ops())
                    now = time.time()

                    for line in chunk.splitlines():
                        m = CHAT_RE.search(line)
                        if not m:
                            continue
                        user = m.group(1)
                        msg = m.group(2).strip()

                        if user.lower() not in ops:
                            continue
                        if 'wilson' not in msg.lower():
                            continue

                        # OP cooldown
                        last = OpAssistService._last_seen_by_user.get(user.lower(), 0.0)
                        if now - last < WILSON_OP_COOLDOWN_SEC:
                            continue
                        OpAssistService._last_seen_by_user[user.lower()] = now

                        OpAssistService._add_history(user, 'user', msg)
                        decision = OpAssistService._llm_call(user, msg)

                        if decision.get('type') == 'chat':
                            text = str(decision.get('say', f"Hey {user}."))
                            OpAssistService._add_history(user, 'assistant', text)
                            OpAssistService._say(text)
                            continue

                        # command path
                        cmd = str(decision.get('command', '')).strip()
                        if not cmd:
                            OpAssistService._say(f"{user}, I couldn't derive a valid command.")
                            continue

                        if cmd.startswith('/'):
                            cmd = cmd[1:].strip()

                        # normalize common player-target aliases/placeholders from AI output
                        cmd = re.sub(r'\b@p\b', user, cmd)
                        cmd = re.sub(r'\b(me|myself|self)\b', user, cmd, flags=re.IGNORECASE)
                        # Replace common LLM placeholders like <playername>, <player>, {player}
                        cmd = re.sub(r'(?i)<\s*player\s*name\s*>', user, cmd)
                        cmd = re.sub(r'(?i)<\s*player\s*>', user, cmd)
                        cmd = re.sub(r'(?i)\{\s*player\s*name\s*\}', user, cmd)
                        cmd = re.sub(r'(?i)\{\s*player\s*\}', user, cmd)
                        cmd = re.sub(r'(?i)\bplayername\b', user, cmd)
                        cmd = re.sub(r'(?i)\bplayer_name\b', user, cmd)

                        # normalize dimension wording typo from AI
                        cmd = cmd.replace('minecraft:nether', 'minecraft:the_nether')

                        # smart rewrite for natural teleport-to-dimension attempts
                        m_tp_dim = re.match(r'^tp\s+([A-Za-z0-9_@]+)\s+minecraft:(the_nether|the_end|overworld)\s*$', cmd, flags=re.IGNORECASE)
                        if m_tp_dim:
                            who = m_tp_dim.group(1)
                            dim = m_tp_dim.group(2).lower()
                            target = {
                                'the_nether': '0 80 0',
                                'the_end': '0 80 0',
                                'overworld': '0 80 0',
                            }[dim]
                            cmd = f'execute in minecraft:{dim} run tp {who} {target}'

                        # ensure gamemode commands target a player when omitted
                        m_gm = re.match(r'^gamemode\s+(survival|creative|adventure|spectator)\s*$', cmd, flags=re.IGNORECASE)
                        if m_gm:
                            mode = m_gm.group(1).lower()
                            cmd = f'gamemode {mode} {user}'

                        # refuse unresolved placeholders instead of pretending success
                        if re.search(r'<[^>]*>|\{[^}]*\}', cmd):
                            OpAssistService._say(f"{user}, I couldn't build a valid command yet. Please rephrase.")
                            continue

                        if OpAssistService._is_blocked(cmd):
                            OpAssistService._say(f"sorry {user}, that command is blocked for safety.")
                            continue

                        res = ServerService.send_console_command(cmd, tier='admin', unsafe_ok=True)
                        if res.get('ok'):
                            say = str(decision.get('say', f"done {user} -> {cmd}"))
                            OpAssistService._add_history(user, 'assistant', say)
                            OpAssistService._say(say)
                        else:
                            OpAssistService._say(f"sorry {user}, command failed.")

            except Exception:
                pass

            await asyncio.sleep(2)
