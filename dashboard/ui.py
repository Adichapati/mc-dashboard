def login_html() -> str:
    return """
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


def public_html() -> str:
    return """
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
<div class='card'><div class='k'>ONLINE PLAYERS</div><div class='mono' id='onlinePlayersPublic' style='margin-top:8px'>Loading...</div></div>
<div class='grid'><div class='card'><div class='k'>CPU</div><div class='big' id='cpu'>...</div></div><div class='card'><div class='k'>RAM</div><div class='big' id='ram'>...</div><div class='k mono' id='ramd'></div></div></div>
</div>
<script>
const tok = location.pathname.split('/').pop();
function renderPublicPlayers(serverInfo){
 const names = (serverInfo && Array.isArray(serverInfo.player_names)) ? serverInfo.player_names : [];
 const count = Number(serverInfo?.players_online || 0);
 const el = document.getElementById('onlinePlayersPublic');
 if(names.length){
   el.textContent = names.join(', ');
   return;
 }
 if(count > 0){
   el.textContent = `(${count} online, names unavailable from status ping right now)`;
   return;
 }
 el.textContent = 'No players online right now.';
}
async function refresh(){
 const r=await fetch(`/api/public/state/${encodeURIComponent(tok)}`);
 const d=await r.json();
 if(!r.ok){ throw new Error(d.error || 'forbidden'); }
 document.getElementById('running').textContent = d.running ? 'RUNNING' : 'STOPPED';
 document.getElementById('running').style.color = d.running ? '#0b7f35' : '#b00020';
 document.getElementById('serverinfo').textContent = `${d.server_info.public} | Version: ${d.server_info.version} | Players: ${d.server_info.players}`;
 renderPublicPlayers(d.server_info || {});
 document.getElementById('cpu').textContent = `${d.metrics.cpu_percent}%`;
 document.getElementById('ram').textContent = `${d.metrics.memory_percent}%`;
 document.getElementById('ramd').textContent = `${d.metrics.memory_used_gb} GB / ${d.metrics.memory_total_gb} GB`;
}
refresh(); setInterval(refresh,10000);
</script></body></html>
"""


def dash_html() -> str:
    return """
<!doctype html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width, initial-scale=1'/><title>MC Dashboard</title>
<link href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;700;800&display=swap' rel='stylesheet'>
<style>
:root{--bg:#ffe66d;--ink:#101010;--paper:#fff;--mint:#7cf29a;--pink:#ff8fab;--blue:#77b8ff;--orange:#ffb347;--purple:#b29bff;--red:#ff7b7b}
*{box-sizing:border-box} body{font-family:'Space Grotesk',Inter,system-ui,sans-serif;background:var(--bg);color:var(--ink);margin:0}
.wrap{max-width:1180px;margin:18px auto;padding:0 14px}.card{background:var(--paper);border:4px solid var(--ink);border-radius:18px;padding:14px;margin-bottom:14px;box-shadow:8px 8px 0 var(--ink)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:980px){.grid,.grid3{grid-template-columns:1fr}}
.btn{border:3px solid var(--ink);padding:10px 14px;border-radius:12px;font-weight:900;cursor:pointer;margin-right:8px;margin-top:8px;box-shadow:4px 4px 0 var(--ink);color:#111;background:#fff}
.btn:active{transform:translate(2px,2px);box-shadow:2px 2px 0 var(--ink)} .start{background:var(--mint)}.stop{background:var(--red)}.restart{background:var(--blue)}.ghost{background:#fff}
.tag{display:inline-block;padding:5px 11px;border-radius:999px;border:3px solid var(--ink);font-weight:800;font-size:12px;box-shadow:3px 3px 0 var(--ink)}
.tag.status{background:var(--purple)}.tag.logs{background:var(--orange)}.tag.live{background:var(--pink)}
.k{font-weight:700;opacity:.9}.big{font-size:28px;font-weight:900;letter-spacing:.4px}.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}
pre{background:#fff;border:3px solid var(--ink);border-radius:12px;padding:10px;max-height:340px;overflow:auto;box-shadow:4px 4px 0 var(--ink);font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.linkline{margin-top:8px;display:flex;gap:8px;align-items:flex-start}
.linklabel{font-weight:800;min-width:86px;flex:0 0 86px}
.linkvalue{flex:1;min-width:0;word-break:break-word;overflow-wrap:anywhere;line-height:1.35;color:#0a4ea3;text-decoration:underline}
.tabs{display:flex;gap:8px;flex-wrap:wrap}.tab{padding:8px 12px;border:3px solid var(--ink);border-radius:999px;background:#fff;cursor:pointer;font-weight:800;box-shadow:3px 3px 0 var(--ink)}.tab.active{background:var(--mint)}
.panel{display:none}.panel.active{display:block}
input,select,textarea{width:100%;padding:10px;border-radius:10px;border:3px solid var(--ink);font-size:14px;background:#fff}
.small{font-size:12px;opacity:.85}.pill{display:inline-block;padding:4px 8px;border:2px solid var(--ink);border-radius:999px;background:#fff;font-size:12px;font-weight:800}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.statusline{min-height:22px;font-weight:800}
.success{color:#0b7f35}.error{color:#b00020}.chip{display:inline-flex;align-items:center;gap:6px;border:2px solid var(--ink);border-radius:999px;padding:4px 10px;margin:4px;background:#fff;font-weight:700}
</style></head><body><div class='wrap'>
<div class='card'><div style='display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap'>
<div><h2 style='margin:8px 0 0 0;font-size:32px'>Minecraft Dashboard</h2><div class='k'>Modular control panel</div></div>
<button class='btn ghost' onclick='logout()'>Logout</button></div></div>

<div class='card'><span class='tag status'>MINECRAFT STATUS</span>
<div class='big' id='running' style='margin-top:8px'>...</div><div class='k' id='serverinfo'>...</div>
<div style='margin-top:10px'>
  <button class='btn start' onclick="act('start')">Start</button>
  <button class='btn stop' onclick="act('stop')">Stop</button>
  <button class='btn restart' onclick="act('restart')">Restart</button>
  <button class='btn ghost' onclick="toggle('auto_start')">Auto-start</button>
  <button class='btn ghost' onclick="toggle('auto_stop')">Auto-stop</button>
</div><div style='margin-top:8px' class='k' id='automsg'></div></div>

<div class='grid3'>
 <div class='card'><span class='tag' style='background:var(--blue)'>CPU</span><div class='big' id='cpu' style='margin-top:8px'>...</div></div>
 <div class='card'><span class='tag' style='background:var(--mint)'>RAM</span><div class='big' id='ram' style='margin-top:8px'>...</div><div class='k mono' id='ramd'></div></div>
 <div class='card'><span class='tag' style='background:var(--pink)'>LINKS</span><div class='mono linkline'><span class='linklabel'>Private:</span><a class='linkvalue' id='plink' href='#' target='_blank'></a></div><div class='mono linkline'><span class='linklabel'>Public RO:</span><a class='linkvalue' id='publicRead' href='#' target='_blank'></a></div></div>
</div>

<div class='card'><div class='tabs'>
<button class='tab active' data-tab='players'>Players</button><button class='tab' data-tab='console'>Console</button><button class='tab' data-tab='props'>Properties</button><button class='tab' data-tab='world'>World</button><button class='tab' data-tab='seed'>Seed</button><button class='tab' data-tab='automation'>Automation</button><button class='tab' data-tab='analytics'>Analytics</button><button class='tab' data-tab='plugins'>Plugins/Mods</button>
</div></div>

<div id='panel-players' class='panel active'><div class='card'><span class='tag'>PLAYER TOOLS</span><div class='row' style='margin-top:10px'><input id='nameA' placeholder='player_name'/><input id='reasonA' placeholder='reason(optional)'/><button class='btn' onclick="pa('op')">OP</button><button class='btn ghost' onclick="pa('deop')">DEOP</button><button class='btn' onclick="pa('whitelist_add')">WL+</button><button class='btn ghost' onclick="pa('whitelist_remove')">WL-</button><button class='btn stop' onclick="pa('ban')">BAN</button><button class='btn ghost' onclick="pa('pardon')">UNBAN</button><button class='btn' onclick="pa('kick')">KICK</button><button class='btn ghost' onclick='wlt()'>WL TOGGLE</button></div><div class='small' style='margin-top:8px'>Click a current player below to quick-action.</div><div id='onlinePlayers' class='small' style='margin-top:8px'>Loading online players...</div><div id='plist' class='small' style='margin-top:8px'>...</div></div></div>

<div id='panel-console' class='panel'><div class='card'><span class='tag live'>LIVE CONSOLE</span><div class='row'><input id='cmd' placeholder='say hello'/><select id='cmdTier'><option value='safe'>safe</option><option value='moderate'>moderate</option><option value='admin'>admin</option></select><button class='btn' onclick='sc()'>Send</button></div><div id='cmdStatus' class='statusline small'></div><pre id='logs'>Loading...</pre></div></div>

<div id='panel-props' class='panel'><div class='card'><span class='tag'>PROPERTIES</span><div class='grid' style='margin-top:10px'>
<div><label>difficulty</label><select id='p_difficulty'><option>peaceful</option><option>easy</option><option>normal</option><option>hard</option></select></div>
<div><label>gamemode</label><select id='p_gamemode'><option>survival</option><option>creative</option><option>adventure</option><option>spectator</option></select></div>
<div><label>max-players</label><input id='p_max' type='number'/></div><div><label>motd</label><input id='p_motd'/></div>
<div><label>online-mode (official auth)</label><select id='p_online_mode'><option value='true'>true (premium only)</option><option value='false'>false (cracked/tlauncher)</option></select></div>
<div><label>enforce-secure-profile</label><select id='p_secure_profile'><option value='true'>true</option><option value='false'>false</option></select></div>
</div><button class='btn' onclick='sp()'>Save</button><div class='small'>Turning online-mode off allows non-premium launchers (e.g., TLauncher) but is less secure and easier to impersonate usernames. Restart required.</div><div id='pstat' class='statusline small'></div></div></div>

<div id='panel-world' class='panel'><div class='card'><span class='tag'>WORLD</span><div class='row'><button class='btn' onclick='cb()'>Create Backup</button><button class='btn ghost' onclick='rb()'>Refresh Backups</button><button class='btn' onclick='dw()'>Download World ZIP</button></div><div class='row'><input id='resetSeed' placeholder='optional new seed'/><button class='btn stop' onclick='rw()'>Reset World</button></div><div class='row'><input id='restoreName' placeholder='backup name.zip'/><button class='btn' onclick='rs()'>Restore Backup</button></div><div class='row'><input id='worldZip' type='file' accept='.zip'/><button class='btn' onclick='uw()'>Upload World ZIP</button></div><div id='wstat' class='statusline small'></div><div id='blist' class='small'></div></div></div>

<div id='panel-seed' class='panel'><div class='card'><span class='tag'>SEED</span><div class='row'><input id='seed' placeholder='seed'/><button class='btn' onclick='rseed()'>Random</button><button class='btn' onclick='aseed()'>Apply</button></div><div id='sstat' class='statusline small'></div></div></div>

<div id='panel-automation' class='panel'><div class='card'><span class='tag'>SCHEDULED TASKS</span><div class='row'><input id='sr' type='number' placeholder='restart minutes'/><input id='sb' type='number' placeholder='backup minutes'/><button class='btn' onclick='ss()'>Save</button></div><div id='astat' class='statusline small'></div></div></div>

<div id='panel-analytics' class='panel'><div class='card'><span class='tag'>ANALYTICS</span><div class='row'><span class='pill' id='au'>Uptime ...</span><span class='pill' id='aa'>Avg ...</span><span class='pill' id='ap'>Peak ...</span></div></div></div>

<div id='panel-plugins' class='panel'><div class='card'><span class='tag'>PLUGIN/MOD INSTALLER (STAGED)</span><div class='row'><select id='cat'></select><button class='btn' onclick='stagePlugin()'>Download & Stage</button><button class='btn ghost' onclick='loadPlugins()'>Refresh</button></div><div id='plstat' class='statusline small'></div><div id='pllist' class='small'></div><div class='small'>Staging only (safe). Manual final install step can be added next.</div></div></div>

<script>
let ws;
function st(id,m,ok=true){const e=document.getElementById(id); if(!e)return; e.textContent=m||''; e.className='statusline small '+(ok?'success':'error');}
async function api(path,method='GET',body=null){const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null}); if(r.status===401){location.href='/login'; throw new Error('unauthorized');} const j=await r.json().catch(()=>({error:'request failed'})); if(!r.ok) throw new Error(j.error||'request failed'); return j;}
async function logout(){await api('/api/logout','POST'); location.href='/login';}
async function act(a){try{await api('/api/'+a,'POST');}catch(e){st('cmdStatus',e.message,false)}}
async function toggle(n){try{await api('/api/toggle/'+n,'POST');}catch(e){st('cmdStatus',e.message,false)}}
function render(d){running.textContent=d.running?'RUNNING':'STOPPED'; running.style.color=d.running?'#0b7f35':'#b00020'; serverinfo.textContent=`${d.server_info.public} | Version: ${d.server_info.version} | Players: ${d.server_info.players}`; cpu.textContent=d.metrics.cpu_percent+'%'; ram.textContent=d.metrics.memory_percent+'%'; ramd.textContent=`${d.metrics.memory_used_gb} GB / ${d.metrics.memory_total_gb} GB`; automsg.textContent=`Auto-start: ${d.automation.auto_start?'ON':'OFF'} | Auto-stop: ${d.automation.auto_stop?'ON':'OFF'} | ${d.automation.last_status_note}`; plink.textContent=d.dashboard.private_link; plink.href=d.dashboard.private_link; publicRead.textContent=d.dashboard.public_readonly_link; publicRead.href=d.dashboard.public_readonly_link; sr.value=d.automation.restart_minutes||0; sb.value=d.automation.backup_minutes||0;}
function ap(chunk){if(!chunk)return; logs.textContent+=chunk; if(logs.textContent.length>70000) logs.textContent=logs.textContent.slice(-50000); logs.scrollTop=logs.scrollHeight;}
async function wsconn(){try{const t=await api('/api/ws-ticket'); const scheme=location.protocol==='https:'?'wss':'ws'; ws=new WebSocket(`${scheme}://${location.host}/ws?ticket=${encodeURIComponent(t.ticket)}`); ws.onmessage=(ev)=>{try{const m=JSON.parse(ev.data); if(m.type==='snapshot') render(m.data); if(m.type==='log') ap(m.chunk||'');}catch(_){}}; ws.onclose=()=>setTimeout(wsconn,2000);}catch(_){setTimeout(wsconn,3000)}}

async function pa(a){const name=(nameA.value||'').trim(); const reason=(reasonA.value||'').trim(); try{await api('/api/players/action','POST',{action:a,name,reason}); lp();}catch(e){st('cmdStatus',e.message,false)}}
async function quickPlayerAction(action,name){
  nameA.value=name;
  if(action==='ban' || action==='kick'){
    const reason=prompt(`Reason for ${action} ${name}? (optional)`,'') || '';
    reasonA.value=reason;
  }
  await pa(action);
}
function renderOnlinePlayers(players){
  if(!players || !players.length){
    onlinePlayers.innerHTML='<span class="small">No players online right now.</span>';
    return;
  }
  onlinePlayers.innerHTML = players.map(n=>`
    <div class='chip'>
      <strong>${n}</strong>
      <button class='btn ghost' style='margin:0 0 0 6px;padding:4px 8px' onclick=\"quickPlayerAction('op','${n}')\">OP</button>
      <button class='btn ghost' style='margin:0 0 0 6px;padding:4px 8px' onclick=\"quickPlayerAction('deop','${n}')\">DEOP</button>
      <button class='btn ghost' style='margin:0 0 0 6px;padding:4px 8px' onclick=\"quickPlayerAction('whitelist_add','${n}')\">WL+</button>
      <button class='btn ghost' style='margin:0 0 0 6px;padding:4px 8px' onclick=\"quickPlayerAction('whitelist_remove','${n}')\">WL-</button>
      <button class='btn' style='margin:0 0 0 6px;padding:4px 8px' onclick=\"quickPlayerAction('kick','${n}')\">KICK</button>
      <button class='btn stop' style='margin:0 0 0 6px;padding:4px 8px' onclick=\"quickPlayerAction('ban','${n}')\">BAN</button>
    </div>`).join('');
}
async function wlt(){try{await api('/api/players/whitelist/toggle','POST'); lp();}catch(e){st('cmdStatus',e.message,false)}}
async function lp(){try{const r=await api('/api/players/state'); plist.textContent=`WL:${r.whitelist_enabled} | Ops: ${r.ops.join(', ')||'none'} | WL: ${r.whitelist.join(', ')||'none'} | Banned: ${r.banned.join(', ')||'none'} | Online: ${r.online_count||0}`; renderOnlinePlayers(r.online_players||[]);}catch(_){}}
async function sc(){try{await api('/api/console/send','POST',{command:cmd.value,tier:cmdTier.value}); cmd.value=''; st('cmdStatus','command sent',true);}catch(e){st('cmdStatus',e.message,false)}}
async function sp(){try{await api('/api/properties','POST',{updates:{difficulty:p_difficulty.value,gamemode:p_gamemode.value,'max-players':p_max.value,motd:p_motd.value,'online-mode':p_online_mode.value,'enforce-secure-profile':p_secure_profile.value}}); st('pstat','saved (restart server to apply auth mode changes)',true);}catch(e){st('pstat',e.message,false)}}
async function lpv(){try{const p=await api('/api/properties'); p_difficulty.value=p.values['difficulty']||'normal'; p_gamemode.value=p.values['gamemode']||'survival'; p_max.value=p.values['max-players']||20; p_motd.value=p.values['motd']||''; p_online_mode.value=p.values['online-mode']||'true'; p_secure_profile.value=p.values['enforce-secure-profile']||'true';}catch(_){}}
async function cb(){try{const r=await api('/api/world/backup','POST'); st('wstat',r.message,true); rb();}catch(e){st('wstat',e.message,false)}}
async function rb(){try{const r=await api('/api/world/backups'); blist.innerHTML=(r.items||[]).map(x=>`<div class='chip'>${x.name} • ${x.size_mb} MB</div>`).join('')||'No backups';}catch(_){}}
async function rw(){if(!confirm('Reset world?'))return; try{const r=await api('/api/world/reset','POST',{with_backup:true,new_seed:resetSeed.value||null}); st('wstat',r.message,true); rb();}catch(e){st('wstat',e.message,false)}}
async function rs(){if(!confirm('Restore backup?'))return; try{const r=await api('/api/world/restore','POST',{name:restoreName.value}); st('wstat',r.message,true);}catch(e){st('wstat',e.message,false)}}
async function dw(){try{const r=await api('/api/world/download-url'); window.open(r.url,'_blank');}catch(e){st('wstat',e.message,false)}}
async function uw(){const f=worldZip.files[0]; if(!f) return st('wstat','select a zip first',false); const fd=new FormData(); fd.append('file',f); try{const r=await fetch('/api/world/upload',{method:'POST',body:fd}); const j=await r.json(); if(!r.ok) throw new Error(j.error||'upload failed'); st('wstat',j.message,true);}catch(e){st('wstat',e.message,false)}}
async function rseed(){const r=await api('/api/seed/generate','POST'); seed.value=r.seed;}
async function aseed(){try{const r=await api('/api/seed/apply','POST',{seed:seed.value}); st('sstat',r.message,true);}catch(e){st('sstat',e.message,false)}}
async function ss(){try{await api('/api/scheduler','POST',{restart_minutes:parseInt(sr.value||'0',10)||0,backup_minutes:parseInt(sb.value||'0',10)||0}); st('astat','saved',true);}catch(e){st('astat',e.message,false)}}
async function la(){try{const a=await api('/api/analytics'); au.textContent='Uptime: '+a.uptime_percent+'%'; aa.textContent='Avg players: '+a.avg_players; ap.textContent='Peak players: '+a.peak_players;}catch(_){}}
async function loadPlugins(){try{const c=await api('/api/plugins/catalog'); cat.innerHTML=(c.items||[]).map(x=>`<option value='${x.id}'>${x.name} (${x.kind})</option>`).join(''); const s=await api('/api/plugins/staged'); pllist.innerHTML=(s.items||[]).map(x=>`<div class='chip'>${x.name} • ${x.size_mb}MB • ${x.file} <button onclick=\"rmPlugin('${x.file}')\">x</button></div>`).join('')||'No staged items';}catch(e){st('plstat',e.message,false)}}
async function stagePlugin(){try{const r=await api('/api/plugins/stage','POST',{id:cat.value}); st('plstat',r.message,true); loadPlugins();}catch(e){st('plstat',e.message,false)}}
async function rmPlugin(f){try{const r=await api('/api/plugins/remove','POST',{file:f}); st('plstat',r.message,true); loadPlugins();}catch(e){st('plstat',e.message,false)}}

document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); t.classList.add('active'); document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active')); document.getElementById('panel-'+t.dataset.tab).classList.add('active');});
wsconn(); lp(); lpv(); rb(); la(); loadPlugins(); setInterval(la,30000);
</script></body></html>
"""
