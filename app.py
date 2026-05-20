import subprocess, sys

# Auto-installation des dépendances
for pkg in ["flask", "twitchio", "werkzeug"]:
    try:
        __import__(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", f"{pkg}"])

import threading, asyncio, json, os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, jsonify, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import twitchio
from twitchio.ext import commands

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changez-moi-en-production')

USERS_FILE  = 'users.json'
CONFIG_FILE = 'config.json'
DEFAULT_CONFIG = {
    'bot_token':      os.environ.get('BOT_TOKEN', ''),
    'lurk_message':   '{user} part en mode lurk dans les buissons... 👀🌿',
    'unlurk_message': '👋 {user} est de retour ! Bienvenue !'
}

def load_users():
    return json.load(open(USERS_FILE)) if os.path.exists(USERS_FILE) else {}
def save_users(u):
    json.dump(u, open(USERS_FILE,'w'), indent=2, ensure_ascii=False)
def load_config():
    return {**DEFAULT_CONFIG, **json.load(open(CONFIG_FILE))} if os.path.exists(CONFIG_FILE) else DEFAULT_CONFIG.copy()
def save_config(c):
    json.dump(c, open(CONFIG_FILE,'w'), indent=2, ensure_ascii=False)

config = load_config()

def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'username' not in session: return redirect(url_for('login_page'))
        return f(*a,**k)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'username' not in session: return redirect(url_for('login_page'))
        if not load_users().get(session['username'],{}).get('admin'): return redirect(url_for('dashboard'))
        return f(*a,**k)
    return d

logs = []
def add_log(msg, level='info', channel=None):
    e = {'time': datetime.now().strftime('%H:%M:%S'), 'msg': msg, 'level': level, 'channel': channel or ''}
    logs.append(e)
    if len(logs) > 500: logs.pop(0)
    print(f"[{e['time']}] {msg}")

bot_instance = bot_thread = bot_loop = None
bot_running = False

class TwitchBot(commands.Bot):
    def __init__(self, token, channels, lurk_msg, unlurk_msg):
        super().__init__(token=token, prefix='!', initial_channels=channels or ['_placeholder_'])
        self.lurk_msg = lurk_msg; self.unlurk_msg = unlurk_msg
    async def event_ready(self):
        add_log(f'Bot connecté : {self.nick}', 'success')
        for ch in self.connected_channels: add_log(f'Canal rejoint : #{ch.name}', 'info', ch.name)
    async def event_message(self, message):
        if message.echo: return
        await self.handle_commands(message)
    @commands.command(name='addbot')
    async def addbot(self, ctx):
        users = load_users(); ch = ctx.channel.name.lower()
        for uname, data in users.items():
            if data.get('channel','').lower() == ch and data.get('status') == 'pending':
                users[uname]['status'] = 'active'; save_users(users)
                await ctx.send(f'✅ Bot activé sur #{ch} ! Commandes : !lurk / !unlurk 🎉')
                add_log(f'#{ch} activé par {ctx.author.name}', 'success', ch); return
        if any(d.get('channel','').lower()==ch and d.get('status')=='active' for d in users.values()):
            await ctx.send('ℹ️ Le bot est déjà actif ici !')
    @commands.command(name='lurk')
    async def lurk(self, ctx):
        users = load_users(); ch = ctx.channel.name.lower()
        if not any(d.get('channel','').lower()==ch and d.get('status')=='active' for d in users.values()): return
        await ctx.send(self.lurk_msg.format(user=ctx.author.name))
        add_log(f'{ctx.author.name} → !lurk', 'command', ch)
    @commands.command(name='unlurk')
    async def unlurk(self, ctx):
        users = load_users(); ch = ctx.channel.name.lower()
        if not any(d.get('channel','').lower()==ch and d.get('status')=='active' for d in users.values()): return
        await ctx.send(self.unlurk_msg.format(user=ctx.author.name))
        add_log(f'{ctx.author.name} → !unlurk', 'command', ch)
    async def event_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound): return
        add_log(f'Erreur : {error}', 'error')

def _get_channels():
    return [d['channel'] for d in load_users().values() if d.get('channel') and d.get('status') in ('pending','active')]

def _run_bot(token, channels, lurk_msg, unlurk_msg):
    global bot_instance, bot_loop, bot_running
    bot_loop = asyncio.new_event_loop(); asyncio.set_event_loop(bot_loop)
    bot_instance = TwitchBot(token, channels, lurk_msg, unlurk_msg)
    try:
        bot_running = True; bot_instance.run()
    except Exception as e: add_log(f'Erreur fatale : {e}', 'error')
    finally: bot_running = False; add_log('Bot arrêté', 'warning')

def start_bot():
    global bot_thread
    if bot_thread and bot_thread.is_alive(): return
    token = config.get('bot_token','')
    if not token: return
    bot_thread = threading.Thread(target=_run_bot,
        args=(token, _get_channels(), config['lurk_message'], config['unlurk_message']), daemon=True)
    bot_thread.start(); add_log('Bot démarré', 'info')

def join_live(ch):
    if bot_instance and bot_loop and bot_running and not bot_loop.is_closed():
        asyncio.run_coroutine_threadsafe(bot_instance.join_channels([ch]), bot_loop)
        add_log(f'Rejoint #{ch}', 'success', ch)

# ═══════════════════════════════════════════════════
#  HTML — PAGE AUTH
# ═══════════════════════════════════════════════════
AUTH_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TwitchBot — Connexion</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080c14;--surf:#0f1520;--surf2:#141c2e;--border:#1e2840;--purple:#9146ff;--pd:#7b2fff;--pg:rgba(145,70,255,.12);--green:#0dffc8;--red:#ff4757;--text:#c8d4f0;--muted:#4a5778}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:'Syne',sans-serif}
body{background-image:linear-gradient(rgba(145,70,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(145,70,255,.03) 1px,transparent 1px);background-size:32px 32px;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:1.5rem}
.card{width:100%;max-width:420px;background:var(--surf);border:1px solid var(--border);border-radius:20px;padding:2.25rem 2rem;box-shadow:0 24px 80px rgba(0,0,0,.5)}
.logo{display:flex;align-items:center;gap:.75rem;margin-bottom:2rem}
.logo-icon{width:42px;height:42px;background:var(--purple);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.3rem;box-shadow:0 0 24px rgba(145,70,255,.45);flex-shrink:0}
.logo h1{font-size:1.2rem;font-weight:800;color:#fff}.logo span{font-size:.68rem;color:var(--muted);font-family:'Space Mono',monospace;display:block}
.tabs{display:flex;margin-bottom:1.75rem;background:var(--surf2);border-radius:10px;padding:3px}
.tab{flex:1;padding:.55rem;text-align:center;border-radius:8px;font-size:.85rem;font-weight:700;cursor:pointer;color:var(--muted);border:none;background:none;font-family:'Syne',sans-serif;transition:all .2s}
.tab.active{background:var(--border);color:var(--text)}
.field{display:flex;flex-direction:column;gap:.45rem;margin-bottom:1rem}
label{font-size:.78rem;font-weight:600;color:#7a8cb0}
input{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);font-family:'Space Mono',monospace;font-size:.82rem;padding:.72rem 1rem;outline:none;transition:border-color .2s,box-shadow .2s}
input:focus{border-color:var(--purple);box-shadow:0 0 0 3px var(--pg)}
.hint{font-size:.7rem;color:var(--muted);font-family:'Space Mono',monospace;line-height:1.5;margin-top:-.25rem}
.btn{width:100%;padding:.9rem;border-radius:12px;border:none;background:var(--purple);color:#fff;font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;cursor:pointer;margin-top:.5rem;transition:all .2s;box-shadow:0 4px 20px rgba(145,70,255,.35)}
.btn:hover:not(:disabled){background:var(--pd);transform:translateY(-1px)}.btn:disabled{opacity:.4;cursor:not-allowed}
.alert{border-radius:10px;padding:.7rem 1rem;font-family:'Space Mono',monospace;font-size:.78rem;display:none;margin-top:.75rem;line-height:1.5}
.alert.err{background:rgba(255,71,87,.1);border:1px solid rgba(255,71,87,.3);color:var(--red)}
.alert.show{display:block}
.fs{display:none}.fs.active{display:block}
code{background:var(--surf2);padding:1px 6px;border-radius:4px;font-family:'Space Mono',monospace}
</style></head><body>
<div class="card">
  <div class="logo"><div class="logo-icon">🤖</div><div><h1>TwitchBot Panel</h1><span>Multi-canal · 24/7</span></div></div>
  <div class="tabs">
    <button class="tab {% if mode=='login' %}active{% endif %}" id="tL" onclick="sw('login')">Connexion</button>
    <button class="tab {% if mode=='register' %}active{% endif %}" id="tR" onclick="sw('register')">Inscription</button>
  </div>
  <div class="fs {% if mode=='login' %}active{% endif %}" id="fL">
    <div class="field"><label>Nom d'utilisateur</label><input type="text" id="lU" placeholder="ton_pseudo" autocomplete="username"></div>
    <div class="field"><label>Mot de passe</label><input type="password" id="lP" placeholder="••••••••" onkeydown="if(event.key==='Enter')login()"></div>
    <button class="btn" id="bL" onclick="login()">Se connecter</button>
    <div class="alert err" id="aL"></div>
  </div>
  <div class="fs {% if mode=='register' %}active{% endif %}" id="fR">
    <div class="field"><label>Nom d'utilisateur (panel)</label><input type="text" id="rU" placeholder="ton_pseudo"></div>
    <div class="field"><label>Mot de passe</label><input type="password" id="rP" placeholder="6 caractères minimum"></div>
    <div class="field"><label>Ton canal Twitch</label><input type="text" id="rC" placeholder="nom_du_canal (sans #)" onkeydown="if(event.key==='Enter')register()">
    <p class="hint">Tu devras taper <code>!addbot</code> dans ton chat Twitch pour activer le bot.</p></div>
    <button class="btn" id="bR" onclick="register()">Créer mon compte</button>
    <div class="alert err" id="aR"></div>
  </div>
</div>
<script>
function sw(m){['fL','fR'].forEach((id,i)=>document.getElementById(id).classList.toggle('active',m==(i==0?'login':'register')));['tL','tR'].forEach((id,i)=>document.getElementById(id).classList.toggle('active',m==(i==0?'login':'register')));history.replaceState(null,'',m=='login'?'/login':'/register');}
function alert_(id,msg){const e=document.getElementById(id);e.textContent=msg;e.classList.add('show');}
async function login(){
  const b=document.getElementById('bL');b.disabled=true;b.textContent='Connexion...';
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('lU').value,password:document.getElementById('lP').value})});
  const d=await r.json();
  if(r.ok){window.location.href=d.admin?'/admin':'/dashboard';}
  else{alert_('aL','❌ '+d.error);b.disabled=false;b.textContent='Se connecter';}
}
async function register(){
  const b=document.getElementById('bR');b.disabled=true;b.textContent='Création...';
  const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('rU').value,password:document.getElementById('rP').value,channel:document.getElementById('rC').value})});
  const d=await r.json();
  if(r.ok){window.location.href='/dashboard';}
  else{alert_('aR','❌ '+d.error);b.disabled=false;b.textContent='Créer mon compte';}
}
</script></body></html>"""

# ═══════════════════════════════════════════════════
#  HTML — DASHBOARD UTILISATEUR
# ═══════════════════════════════════════════════════
USER_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TwitchBot — Mon espace</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080c14;--surf:#0f1520;--surf2:#141c2e;--border:#1e2840;--purple:#9146ff;--pd:#7b2fff;--pg:rgba(145,70,255,.12);--green:#0dffc8;--red:#ff4757;--yellow:#ffcc00;--text:#c8d4f0;--muted:#4a5778}
html,body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;min-height:100vh}
body{background-image:linear-gradient(rgba(145,70,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(145,70,255,.03) 1px,transparent 1px);background-size:32px 32px}
.shell{max-width:680px;margin:0 auto;padding:2rem 1.5rem 4rem}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;padding-bottom:1.5rem;border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:.75rem}
.logo-icon{width:38px;height:38px;background:var(--purple);border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:1.2rem;box-shadow:0 0 18px rgba(145,70,255,.4)}
.logo h1{font-size:1.1rem;font-weight:800;color:#fff}.logo sub{font-size:.65rem;color:var(--muted);font-family:'Space Mono',monospace;display:block}
.hright{display:flex;align-items:center;gap:.6rem}
.upill{font-family:'Space Mono',monospace;font-size:.72rem;color:var(--muted);background:var(--surf);border:1px solid var(--border);border-radius:999px;padding:.3rem .8rem}
.upill strong{color:var(--text)}
.blgout{background:none;border:1px solid var(--border);border-radius:8px;padding:.3rem .7rem;color:var(--muted);font-size:.72rem;cursor:pointer;font-family:'Space Mono',monospace;transition:all .2s}
.blgout:hover{border-color:var(--red);color:var(--red)}
.card{background:var(--surf);border:1px solid var(--border);border-radius:16px;padding:1.5rem;margin-bottom:1.1rem}
.ctitle{font-size:.6rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-family:'Space Mono',monospace;margin-bottom:1.1rem}
.banner{border-radius:14px;padding:1.25rem 1.5rem;display:flex;align-items:flex-start;gap:1rem;margin-bottom:1.1rem;border:1px solid}
.banner.pending{background:rgba(255,204,0,.06);border-color:rgba(255,204,0,.25)}
.banner.active{background:rgba(13,255,200,.06);border-color:rgba(13,255,200,.2)}
.banner.idle{background:rgba(74,87,120,.08);border-color:var(--border)}
.bico{font-size:1.75rem;flex-shrink:0;margin-top:.1rem}
.btit{font-size:1rem;font-weight:700;color:#fff;margin-bottom:.3rem}
.bdesc{font-size:.82rem;color:var(--muted);line-height:1.6}
code{font-family:'Space Mono',monospace;background:var(--surf2);border:1px solid var(--border);padding:1px 7px;border-radius:5px;font-size:.82rem;color:var(--text)}
.steps{margin-top:.75rem;display:flex;flex-direction:column;gap:.55rem}
.si{display:flex;align-items:flex-start;gap:.75rem;font-size:.82rem;color:var(--muted);line-height:1.5}
.sn{width:22px;height:22px;border-radius:50%;border:1px solid var(--purple);display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;flex-shrink:0;margin-top:1px;color:var(--purple)}
.cmds{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
@media(max-width:500px){.cmds{grid-template-columns:1fr}}
.cmd{background:var(--surf2);border:1px solid var(--border);border-radius:12px;padding:1rem}
.cname{font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:var(--purple);margin-bottom:.3rem}
.cdesc{font-size:.78rem;color:var(--muted);line-height:1.5}
.lhdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:.85rem}
.lterm{background:#04070f;border:1px solid var(--border);border-radius:12px;height:220px;overflow-y:auto;padding:1rem;font-family:'Space Mono',monospace;font-size:.78rem;line-height:1.9}
.lterm::-webkit-scrollbar{width:3px}.lterm::-webkit-scrollbar-thumb{background:var(--border);border-radius:99px}
.ll{display:flex;gap:.75rem}.lt{color:var(--muted);flex-shrink:0}
.ll.info .lm{color:var(--text)}.ll.success .lm{color:var(--green)}.ll.error .lm{color:var(--red)}.ll.warning .lm{color:var(--yellow)}.ll.command .lm{color:var(--purple);font-weight:700}
.lempty{color:var(--muted);font-style:italic;text-align:center;padding-top:1.5rem;font-size:.78rem}
.lcnt{font-family:'Space Mono',monospace;font-size:.7rem;color:var(--muted)}
.bclr{background:none;border:none;color:var(--muted);font-family:'Space Mono',monospace;font-size:.7rem;cursor:pointer;padding:.2rem .5rem;border-radius:5px}
.bclr:hover{background:var(--border);color:var(--text)}
.dot-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite;margin-right:5px}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.75)}}
</style></head>
<body><div class="shell">
<header>
  <div class="logo"><div class="logo-icon">🤖</div><div><h1>Mon espace</h1><sub>TwitchBot Panel</sub></div></div>
  <div class="hright">
    <div class="upill"><strong id="hU">...</strong></div>
    <button class="blgout" onclick="location.href='/logout'">Déconnexion</button>
  </div>
</header>

<div id="banner" class="banner idle">
  <div class="bico" id="bico">⏳</div>
  <div><div class="btit" id="btit">Chargement...</div><div class="bdesc" id="bdesc"></div></div>
</div>

<div class="card" id="cmdCard" style="display:none">
  <div class="ctitle">⚡ Commandes disponibles sur ton canal</div>
  <div class="cmds">
    <div class="cmd"><div class="cname">!lurk</div><div class="cdesc">Le viewer annonce qu'il passe en mode lurk discret.</div></div>
    <div class="cmd"><div class="cname">!unlurk</div><div class="cdesc">Le viewer annonce son retour du mode lurk.</div></div>
  </div>
</div>

<div class="card">
  <div class="lhdr">
    <div class="ctitle" style="margin:0">📡 Activité de ton canal</div>
    <div style="display:flex;gap:.5rem;align-items:center"><span class="lcnt" id="lCnt">0</span><button class="bclr" onclick="clr()">Effacer</button></div>
  </div>
  <div class="lterm" id="lTerm"><div class="lempty">Aucune activité pour l'instant...</div></div>
</div>
</div>

<script>
let seen=0;
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function renderBanner(d){
  const bn=document.getElementById('banner'),ic=document.getElementById('bico'),tt=document.getElementById('btit'),ds=document.getElementById('bdesc');
  document.getElementById('cmdCard').style.display='none';
  const old=document.getElementById('stps');if(old)old.remove();
  if(d.status==='active'&&d.connected){
    bn.className='banner active';ic.textContent='✅';
    tt.textContent='Bot actif sur #'+d.channel;
    ds.innerHTML='<span class="dot-live"></span>Le bot est connecté et opérationnel dans ton chat.';
    document.getElementById('cmdCard').style.display='block';
  } else if(d.status==='active'){
    bn.className='banner idle';ic.textContent='🔄';
    tt.textContent='Connexion en cours...';
    ds.textContent='Le bot rejoint #'+d.channel+', patienter quelques secondes.';
  } else {
    bn.className='banner pending';ic.textContent='⏳';
    tt.textContent='Activation requise — #'+d.channel;
    ds.innerHTML='Tape <code>!addbot</code> dans ton chat Twitch pour activer le bot.';
    const st=document.createElement('div');st.id='stps';st.className='steps';
    st.innerHTML='<div class="si"><div class="sn">1</div><span>Ouvre ton chat : <strong style="color:var(--text)">twitch.tv/'+esc(d.channel)+'</strong></span></div><div class="si"><div class="sn">2</div><span>Tape dans le chat : <code>!addbot</code></span></div><div class="si"><div class="sn">3</div><span>Cette page se met à jour automatiquement ✅</span></div>';
    ds.after(st);
  }
}

function renderLogs(logs){
  if(!logs||!logs.length)return;
  const t=document.getElementById('lTerm'),atB=t.scrollHeight-t.scrollTop<=t.clientHeight+40;
  const empty=t.querySelector('.lempty');if(empty)empty.remove();
  logs.slice(seen).forEach(l=>{const d=document.createElement('div');d.className='ll '+(l.level||'info');d.innerHTML='<span class="lt">'+l.time+'</span><span class="lm">'+esc(l.msg)+'</span>';t.appendChild(d);});
  seen=logs.length;document.getElementById('lCnt').textContent=seen;
  if(atB)t.scrollTop=t.scrollHeight;
}

function clr(){document.getElementById('lTerm').innerHTML='<div class="lempty">Journal effacé.</div>';seen=0;document.getElementById('lCnt').textContent=0;}

async function poll(){
  try{
    const me=await fetch('/api/me').then(r=>r.json());
    document.getElementById('hU').textContent=me.username;
    renderBanner(me);renderLogs(me.logs);
  }catch(_){}
}
poll();setInterval(poll,3000);
</script></body></html>"""

# ═══════════════════════════════════════════════════
#  HTML — ADMIN PANEL
# ═══════════════════════════════════════════════════
ADMIN_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TwitchBot — Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#05080f;--surf:#0a1018;--surf2:#0f1825;--surf3:#141f2e;--border:#1a2538;--accent:#e8642c;--accentd:#c94e1a;--accentg:rgba(232,100,44,.12);--purple:#9146ff;--green:#0dffc8;--red:#ff4757;--yellow:#ffcc00;--blue:#4ea8ff;--text:#c8d8f0;--muted:#3d5070;--ui:'Syne',sans-serif;--mono:'Space Mono',monospace}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--ui)}
.layout{display:flex;min-height:100vh}

/* Sidebar */
.sidebar{width:240px;background:var(--surf);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0;position:fixed;top:0;left:0;height:100vh;z-index:10}
.sb-logo{padding:1.5rem 1.25rem;border-bottom:1px solid var(--border)}
.sb-logo-icon{width:36px;height:36px;background:var(--accent);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1.1rem;box-shadow:0 0 20px rgba(232,100,44,.4);margin-bottom:.6rem}
.sb-logo h1{font-size:1rem;font-weight:800;color:#fff;letter-spacing:-.02em}
.sb-logo span{font-size:.6rem;color:var(--muted);font-family:var(--mono);display:block;margin-top:2px}
.sb-section{padding:.75rem .75rem .25rem;font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-family:var(--mono)}
.nav-item{display:flex;align-items:center;gap:.65rem;padding:.6rem .75rem;border-radius:9px;margin:1px .5rem;font-size:.85rem;font-weight:600;color:var(--muted);cursor:pointer;border:none;background:none;width:calc(100% - 1rem);text-align:left;transition:all .2s}
.nav-item:hover{background:var(--surf2);color:var(--text)}
.nav-item.active{background:var(--accentg);color:var(--accent);border:1px solid rgba(232,100,44,.2)}
.nav-item .ni{font-size:1rem;flex-shrink:0}
.sb-bottom{margin-top:auto;padding:.75rem;border-top:1px solid var(--border)}
.user-info{display:flex;align-items:center;gap:.6rem;padding:.6rem .75rem;border-radius:9px;background:var(--surf2)}
.user-avatar{width:28px;height:28px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:700;color:#fff;flex-shrink:0}
.user-name{font-size:.78rem;font-weight:600;color:var(--text)}
.user-role{font-size:.6rem;color:var(--accent);font-family:var(--mono)}
.btn-logout-sb{margin-top:.5rem;width:100%;padding:.5rem;border-radius:8px;border:1px solid var(--border);background:none;color:var(--muted);font-family:var(--mono);font-size:.72rem;cursor:pointer;transition:all .2s}
.btn-logout-sb:hover{border-color:var(--red);color:var(--red)}

/* Main */
.main{margin-left:240px;flex:1;min-height:100vh;background:var(--bg);background-image:linear-gradient(rgba(232,100,44,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(232,100,44,.02) 1px,transparent 1px);background-size:40px 40px}
.topbar{height:56px;border-bottom:1px solid var(--border);background:var(--surf);display:flex;align-items:center;padding:0 2rem;gap:1rem;position:sticky;top:0;z-index:5}
.page-title{font-size:1rem;font-weight:700;color:#fff}
.bot-badge{display:flex;align-items:center;gap:.5rem;padding:.35rem .8rem;border-radius:999px;border:1px solid var(--border);background:var(--surf2);font-size:.72rem;font-family:var(--mono);color:var(--muted);margin-left:auto}
.bot-badge.on{border-color:rgba(13,255,200,.3);color:var(--green)}
.bdot{width:7px;height:7px;border-radius:50%;background:var(--muted)}
.bot-badge.on .bdot{background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.75)}}
.content{padding:2rem;max-width:900px}
.section{display:none}.section.active{display:block}

/* Cards */
.card{background:var(--surf);border:1px solid var(--border);border-radius:14px;padding:1.5rem;margin-bottom:1.1rem}
.card-title{font-size:.6rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-family:var(--mono);margin-bottom:1.1rem}

/* Stat cards */
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.9rem;margin-bottom:1.1rem}
@media(max-width:700px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
.stat-card{background:var(--surf);border:1px solid var(--border);border-radius:14px;padding:1.25rem 1.5rem}
.stat-label{font-size:.62rem;font-family:var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.4rem}
.stat-val{font-size:1.75rem;font-weight:800;color:#fff;line-height:1}
.stat-val.green{color:var(--green)}.stat-val.orange{color:var(--accent)}.stat-val.purple{color:var(--purple)}
.stat-sub{font-size:.7rem;color:var(--muted);font-family:var(--mono);margin-top:.3rem}

/* Users table */
.utbl{width:100%;border-collapse:collapse;font-size:.82rem}
.utbl th{text-align:left;padding:.6rem .85rem;font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-family:var(--mono);border-bottom:1px solid var(--border)}
.utbl td{padding:.65rem .85rem;border-bottom:1px solid rgba(26,37,56,.6);vertical-align:middle}
.utbl tr:last-child td{border-bottom:none}.utbl tr:hover td{background:var(--surf2)}
.spill{font-family:var(--mono);font-size:.68rem;padding:2px 9px;border-radius:999px;border:1px solid}
.spill.active{background:rgba(13,255,200,.08);border-color:rgba(13,255,200,.25);color:var(--green)}
.spill.pending{background:rgba(255,204,0,.08);border-color:rgba(255,204,0,.25);color:var(--yellow)}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:4px}
.dot.on{background:var(--green);box-shadow:0 0 5px var(--green)}.dot.off{background:var(--muted)}

/* Form fields */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:.9rem}
@media(max-width:600px){.g2{grid-template-columns:1fr}}
.field{display:flex;flex-direction:column;gap:.45rem;margin-bottom:.85rem}
label{font-size:.75rem;font-weight:600;color:#6a7fa0}
input,textarea{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:9px;color:var(--text);font-family:var(--mono);font-size:.82rem;padding:.7rem 1rem;outline:none;transition:border-color .2s,box-shadow .2s}
input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accentg)}
textarea{resize:vertical;min-height:60px;line-height:1.5}
.hint{font-size:.68rem;color:var(--muted);font-family:var(--mono);line-height:1.5}
.hint a{color:var(--accent);text-decoration:none}

/* Buttons */
.btn{padding:.65rem 1.2rem;border-radius:9px;border:none;font-family:var(--ui);font-size:.85rem;font-weight:700;cursor:pointer;transition:all .2s;display:inline-flex;align-items:center;gap:.4rem}
.bprimary{background:var(--accent);color:#fff;box-shadow:0 4px 16px rgba(232,100,44,.3)}.bprimary:hover:not(:disabled){background:var(--accentd);transform:translateY(-1px)}
.bdanger{background:transparent;border:1px solid rgba(255,71,87,.3);color:var(--red)}.bdanger:hover:not(:disabled){background:rgba(255,71,87,.1)}
.bghost{background:transparent;border:1px solid var(--border);color:var(--muted)}.bghost:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
.bgreen{background:rgba(13,255,200,.1);border:1px solid rgba(13,255,200,.2);color:var(--green)}.bgreen:hover:not(:disabled){background:rgba(13,255,200,.2)}
.btn:disabled{opacity:.35;cursor:not-allowed;transform:none}
.btn-sm{padding:.3rem .65rem;font-size:.72rem;border-radius:7px}
.ctrls{display:flex;gap:.75rem;flex-wrap:wrap;margin-top:.85rem}
.alrt{border-radius:8px;padding:.6rem .9rem;font-family:var(--mono);font-size:.78rem;display:none;margin-top:.75rem;line-height:1.4}
.alrt.err{background:rgba(255,71,87,.1);border:1px solid rgba(255,71,87,.3);color:var(--red)}
.alrt.ok{background:rgba(13,255,200,.08);border:1px solid rgba(13,255,200,.2);color:var(--green)}.alrt.show{display:block}

/* Log */
.lhdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:.85rem}
.lterm{background:#030508;border:1px solid var(--border);border-radius:10px;height:260px;overflow-y:auto;padding:1rem;font-family:var(--mono);font-size:.78rem;line-height:1.9}
.lterm::-webkit-scrollbar{width:3px}.lterm::-webkit-scrollbar-thumb{background:var(--border);border-radius:99px}
.ll{display:flex;gap:.75rem}.lt{color:var(--muted);flex-shrink:0}
.ll.info .lm{color:var(--text)}.ll.success .lm{color:var(--green)}.ll.error .lm{color:var(--red)}.ll.warning .lm{color:var(--yellow)}.ll.command .lm{color:var(--purple);font-weight:700}
.lempty{color:var(--muted);font-style:italic;text-align:center;padding-top:1.5rem;font-size:.78rem}
.lcnt{font-family:var(--mono);font-size:.7rem;color:var(--muted)}
.bclr{background:none;border:none;color:var(--muted);font-family:var(--mono);font-size:.7rem;cursor:pointer;padding:.2rem .5rem;border-radius:5px}.bclr:hover{background:var(--border);color:var(--text)}

/* Divider */
.sep{border:none;border-top:1px solid var(--border);margin:1.25rem 0}
</style></head>
<body>
<div class="layout">

<!-- SIDEBAR -->
<aside class="sidebar">
  <div class="sb-logo">
    <div class="sb-logo-icon">⚙️</div>
    <h1>Admin Panel</h1>
    <span>TwitchBot Manager</span>
  </div>
  <div class="sb-section">Navigation</div>
  <button class="nav-item active" onclick="show('overview')" id="nav-overview"><span class="ni">📊</span> Vue d'ensemble</button>
  <button class="nav-item" onclick="show('users')" id="nav-users"><span class="ni">👥</span> Utilisateurs</button>
  <button class="nav-item" onclick="show('bot')" id="nav-bot"><span class="ni">🤖</span> Contrôle du bot</button>
  <button class="nav-item" onclick="show('config')" id="nav-config"><span class="ni">🔧</span> Configuration</button>
  <button class="nav-item" onclick="show('logs')" id="nav-logs"><span class="ni">📡</span> Journaux</button>
  <div class="sb-bottom">
    <div class="user-info">
      <div class="user-avatar" id="avatarLetter">A</div>
      <div><div class="user-name" id="sbUser">...</div><div class="user-role">Administrateur</div></div>
    </div>
    <button class="btn-logout-sb" onclick="location.href='/logout'">Déconnexion</button>
  </div>
</aside>

<!-- MAIN -->
<div class="main">
  <div class="topbar">
    <span class="page-title" id="pageTitle">Vue d'ensemble</span>
    <div class="bot-badge" id="botBadge"><div class="bdot"></div><span id="botBadgeTxt">Bot hors ligne</span></div>
  </div>
  <div class="content">

    <!-- OVERVIEW -->
    <div class="section active" id="sec-overview">
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-label">Utilisateurs</div><div class="stat-val" id="stTotal">—</div><div class="stat-sub">inscrits</div></div>
        <div class="stat-card"><div class="stat-label">Actifs</div><div class="stat-val green" id="stActive">—</div><div class="stat-sub">canaux activés</div></div>
        <div class="stat-card"><div class="stat-label">En attente</div><div class="stat-val orange" id="stPending">—</div><div class="stat-sub">à activer</div></div>
        <div class="stat-card"><div class="stat-label">Connectés</div><div class="stat-val purple" id="stConn">—</div><div class="stat-sub">live maintenant</div></div>
      </div>
      <div class="card">
        <div class="card-title">Activité récente</div>
        <div class="lhdr" style="margin-bottom:.5rem"><span class="lcnt" id="ovLCnt">0 entrée(s)</span><button class="bclr" onclick="clrOv()">Effacer</button></div>
        <div class="lterm" id="ovTerm"><div class="lempty">En attente d'activité...</div></div>
      </div>
    </div>

    <!-- USERS -->
    <div class="section" id="sec-users">
      <div class="card">
        <div class="card-title">Tous les utilisateurs</div>
        <table class="utbl">
          <thead><tr><th>Utilisateur</th><th>Canal Twitch</th><th>Statut</th><th>Bot</th><th>Inscrit le</th><th></th></tr></thead>
          <tbody id="uTbody"><tr><td colspan="6" style="text-align:center;padding:1.5rem;color:var(--muted);font-family:var(--mono);font-size:.78rem">Chargement...</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- BOT CONTROL -->
    <div class="section" id="sec-bot">
      <div class="card">
        <div class="card-title">État du bot</div>
        <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
          <div class="bot-badge" id="botBadge2" style="font-size:.85rem;padding:.5rem 1.1rem"><div class="bdot" id="bd2"></div><span id="botTxt2">Hors ligne</span></div>
          <span id="connChannels" style="font-size:.78rem;color:var(--muted);font-family:var(--mono)">—</span>
        </div>
        <hr class="sep">
        <div class="ctrls">
          <button class="btn bgreen" id="btnSt" onclick="startBot()">▶ Démarrer le bot</button>
          <button class="btn bdanger" id="btnSp" onclick="stopBot()" disabled>⏹ Arrêter le bot</button>
        </div>
        <div class="alrt" id="alBot"></div>
      </div>
      <div class="card">
        <div class="card-title">Canaux surveillés</div>
        <div id="channelTags" style="display:flex;flex-wrap:wrap;gap:.5rem;min-height:30px">
          <span style="color:var(--muted);font-family:var(--mono);font-size:.78rem;font-style:italic">Aucun canal enregistré</span>
        </div>
      </div>
    </div>

    <!-- CONFIG -->
    <div class="section" id="sec-config">
      <div class="card">
        <div class="card-title">🔑 Token du bot Twitch</div>
        <div class="field">
          <label>Token OAuth</label>
          <input type="password" id="cfgTok" placeholder="oauth:xxxxxxxxxxxxxxxx">
          <p class="hint">Génère-le sur <a href="https://twitchtokengenerator.com" target="_blank">twitchtokengenerator.com</a> — scopes requis : <code style="background:var(--surf2);padding:1px 5px;border-radius:4px">chat:read</code> + <code style="background:var(--surf2);padding:1px 5px;border-radius:4px">chat:edit</code></p>
        </div>
        <button class="btn bprimary" onclick="saveTok()">💾 Sauvegarder le token</button>
        <div class="alrt" id="alTok"></div>
      </div>
      <div class="card">
        <div class="card-title">💬 Messages personnalisés</div>
        <div class="g2">
          <div class="field"><label>Message !lurk</label><textarea id="cfgLurk" rows="3"></textarea><p class="hint"><code style="background:var(--surf2);padding:1px 5px;border-radius:4px">{user}</code> = pseudo du viewer</p></div>
          <div class="field"><label>Message !unlurk</label><textarea id="cfgUnlurk" rows="3"></textarea></div>
        </div>
        <button class="btn bprimary" onclick="saveMsgs()">💾 Sauvegarder les messages</button>
        <div class="alrt" id="alMsg"></div>
      </div>
    </div>

    <!-- LOGS -->
    <div class="section" id="sec-logs">
      <div class="card">
        <div class="card-title">Journal complet</div>
        <div class="lhdr"><span class="lcnt" id="logCnt">0 entrée(s)</span><button class="bclr" onclick="clrLogs()">Effacer</button></div>
        <div class="lterm" id="logTerm"><div class="lempty">En attente d'activité...</div></div>
      </div>
    </div>

  </div>
</div>
</div>

<script>
let seenOv=0, seenLog=0;
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const titles={'overview':'Vue d\'ensemble','users':'Utilisateurs','bot':'Contrôle du bot','config':'Configuration','logs':'Journaux'};

function show(sec){
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.remove('active'));
  document.getElementById('sec-'+sec).classList.add('active');
  document.getElementById('nav-'+sec).classList.add('active');
  document.getElementById('pageTitle').textContent=titles[sec];
}

function alrt(id,msg,type){const e=document.getElementById(id);e.textContent=msg;e.className='alrt '+type+' show';setTimeout(()=>e.classList.remove('show'),5000);}

function renderLogs(logs,termId,cntId,seen){
  if(!logs||!logs.length)return seen;
  const t=document.getElementById(termId),atB=t.scrollHeight-t.scrollTop<=t.clientHeight+40;
  const empty=t.querySelector('.lempty');if(empty)empty.remove();
  logs.slice(seen).forEach(l=>{const d=document.createElement('div');d.className='ll '+(l.level||'info');d.innerHTML='<span class="lt">'+l.time+'</span><span class="lm">'+esc(l.msg)+'</span>';t.appendChild(d);});
  seen=logs.length;document.getElementById(cntId).textContent=seen+' entrée(s)';
  if(atB)t.scrollTop=t.scrollHeight;return seen;
}
function clrOv(){document.getElementById('ovTerm').innerHTML='<div class="lempty">Journal effacé.</div>';seenOv=0;document.getElementById('ovLCnt').textContent='0 entrée(s)';}
function clrLogs(){document.getElementById('logTerm').innerHTML='<div class="lempty">Journal effacé.</div>';seenLog=0;document.getElementById('logCnt').textContent='0 entrée(s)';}

function renderUsers(users,connected){
  const tb=document.getElementById('uTbody');tb.innerHTML='';
  users.forEach(u=>{
    const date=u.created_at?u.created_at.split('T')[0]:'—';
    const tr=document.createElement('tr');
    tr.innerHTML='<td style="font-weight:600;color:var(--text)">'+(u.admin?'👑 ':'')+esc(u.username)+'</td>'+
      '<td style="color:var(--purple);font-family:var(--mono)">'+(u.channel?'#'+esc(u.channel):'<span style="color:var(--muted)">—</span>')+'</td>'+
      '<td><span class="spill '+u.status+'">'+u.status+'</span></td>'+
      '<td><span class="dot '+(u.connected?'on':'off')+'"></span><span style="font-size:.78rem;color:var(--muted)">'+(u.connected?'Connecté':'Hors ligne')+'</span></td>'+
      '<td style="font-family:var(--mono);font-size:.72rem;color:var(--muted)">'+date+'</td>'+
      '<td>'+(u.admin?'':('<button class="btn bdanger btn-sm" onclick="rmUser(\''+u.username+'\')">Supprimer</button>'))+'</td>';
    tb.appendChild(tr);
  });
  // Channel tags
  const ct=document.getElementById('channelTags');ct.innerHTML='';
  const chs=users.filter(u=>u.channel);
  if(!chs.length){ct.innerHTML='<span style="color:var(--muted);font-family:var(--mono);font-size:.78rem;font-style:italic">Aucun canal enregistré</span>';return;}
  chs.forEach(u=>{
    const tag=document.createElement('span');
    tag.style.cssText='font-family:var(--mono);font-size:.78rem;padding:3px 11px;border-radius:999px;border:1px solid;'+(u.connected?'background:rgba(13,255,200,.08);border-color:rgba(13,255,200,.25);color:var(--green)':'background:var(--surf2);border-color:var(--border);color:var(--muted)');
    tag.innerHTML='<span class="dot '+(u.connected?'on':'off')+'"></span>#'+esc(u.channel);
    ct.appendChild(tag);
  });
}

async function rmUser(u){if(!confirm('Supprimer '+u+' ?'))return;const r=await fetch('/api/admin/user/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u})});if(!r.ok){const d=await r.json();alert(d.error);}else poll();}

async function startBot(){
  document.getElementById('btnSt').disabled=true;document.getElementById('btnSt').textContent='⏳...';
  const r=await fetch('/api/admin/bot/start',{method:'POST'});const d=await r.json();
  if(!r.ok){alrt('alBot','❌ '+(d.error||'Erreur'),'err');document.getElementById('btnSt').disabled=false;document.getElementById('btnSt').textContent='▶ Démarrer le bot';}
  else{alrt('alBot','✅ Démarrage en cours...','ok');setTimeout(poll,1500);}
}
async function stopBot(){document.getElementById('btnSp').disabled=true;await fetch('/api/admin/bot/stop',{method:'POST'});setTimeout(poll,1200);}

async function saveTok(){
  const tok=document.getElementById('cfgTok').value;
  if(!tok){alrt('alTok','Saisis le token OAuth','err');return;}
  const r=await fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bot_token:tok})});
  const d=await r.json();r.ok?alrt('alTok','✅ Token sauvegardé !','ok'):alrt('alTok','❌ '+d.error,'err');
}
async function saveMsgs(){
  const r=await fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lurk_message:document.getElementById('cfgLurk').value,unlurk_message:document.getElementById('cfgUnlurk').value})});
  const d=await r.json();r.ok?alrt('alMsg','✅ Messages sauvegardés !','ok'):alrt('alMsg','❌ '+d.error,'err');
}

async function loadConf(){
  try{const d=await fetch('/api/admin/config').then(r=>r.json());
    if(d.lurk_message)document.getElementById('cfgLurk').value=d.lurk_message;
    if(d.unlurk_message)document.getElementById('cfgUnlurk').value=d.unlurk_message;
  }catch(_){}
}

function setBotStatus(running,channels){
  const badge=document.getElementById('botBadge'),txt=document.getElementById('botBadgeTxt');
  const badge2=document.getElementById('botBadge2'),bd2=document.getElementById('bd2'),txt2=document.getElementById('botTxt2');
  [badge,badge2].forEach(b=>b.className='bot-badge'+(running?' on':''));
  txt.textContent=running?'Bot en ligne':'Bot hors ligne';
  txt2.textContent=running?'En ligne':'Hors ligne';
  document.getElementById('connChannels').textContent=running&&channels.length?channels.map(c=>'#'+c).join(', '):'Aucun canal connecté';
  document.getElementById('btnSt').disabled=running;document.getElementById('btnSp').disabled=!running;
}

async function poll(){
  try{
    const d=await fetch('/api/admin/users').then(r=>r.json());
    document.getElementById('sbUser').textContent=d.current_user||'Admin';
    document.getElementById('avatarLetter').textContent=(d.current_user||'A')[0].toUpperCase();
    document.getElementById('stTotal').textContent=d.users.length;
    document.getElementById('stActive').textContent=d.users.filter(u=>u.status==='active').length;
    document.getElementById('stPending').textContent=d.users.filter(u=>u.status==='pending').length;
    document.getElementById('stConn').textContent=d.users.filter(u=>u.connected).length;
    renderUsers(d.users,d.connected);
    setBotStatus(d.bot_running,d.connected);
    seenOv=renderLogs(d.logs,'ovTerm','ovLCnt',seenOv);
    seenLog=renderLogs(d.logs,'logTerm','logCnt',seenLog);
  }catch(_){}
}
poll();setInterval(poll,3000);setTimeout(loadConf,500);
</script></body></html>"""

# ═══════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════
@app.route('/')
def index():
    if 'username' not in session: return redirect(url_for('login_page'))
    users = load_users()
    if users.get(session['username'],{}).get('admin'): return redirect(url_for('admin_panel'))
    return redirect(url_for('dashboard'))

@app.route('/login')
def login_page():
    if 'username' in session: return redirect(url_for('index'))
    return render_template_string(AUTH_HTML, mode='login')

@app.route('/register')
def register_page():
    if 'username' in session: return redirect(url_for('index'))
    return render_template_string(AUTH_HTML, mode='register')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template_string(USER_HTML)

@app.route('/admin')
@admin_required
def admin_panel():
    return render_template_string(ADMIN_HTML)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login_page'))

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    users = load_users(); user = users.get(username)
    if user and check_password_hash(user['password'], data.get('password','')):
        session['username'] = username
        return jsonify({'status':'ok','admin':user.get('admin',False)})
    return jsonify({'error':'Identifiants incorrects'}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    password = data.get('password','')
    channel  = data.get('channel','').strip().lower().lstrip('#')
    if not all([username, password, channel]): return jsonify({'error':'Tous les champs sont requis'}), 400
    if len(username) < 3: return jsonify({'error':"Nom trop court (3 min)"}), 400
    if len(password) < 6: return jsonify({'error':'Mot de passe trop court (6 min)'}), 400
    users = load_users()
    if username in users: return jsonify({'error':"Nom d'utilisateur déjà pris"}), 400
    if any(d.get('channel','').lower()==channel for d in users.values()):
        return jsonify({'error':'Ce canal est déjà enregistré'}), 400
    users[username] = {'password':generate_password_hash(password),'channel':channel,'status':'pending','admin':False,'created_at':datetime.now().isoformat()}
    save_users(users); session['username'] = username
    if bot_running: join_live(channel)
    else: start_bot()
    add_log(f'Inscription : {username} → #{channel}', 'info', channel)
    return jsonify({'status':'ok'})

@app.route('/api/me')
@login_required
def api_me():
    users = load_users(); user = users.get(session['username'],{})
    ch = user.get('channel','')
    conn = [c.name.lower() for c in bot_instance.connected_channels] if bot_instance and bot_running else []
    ch_logs = [l for l in logs[-40:] if not l['channel'] or l['channel'].lower()==ch.lower()]
    return jsonify({'username':session['username'],'channel':ch,'status':user.get('status','pending'),'admin':user.get('admin',False),'connected':ch.lower() in conn,'logs':ch_logs})

@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    users = load_users()
    running = bot_running and bot_thread and bot_thread.is_alive()
    conn = [c.name.lower() for c in bot_instance.connected_channels] if bot_instance and running else []
    result = [{'username':u,'channel':d.get('channel',''),'status':d.get('status','pending'),'connected':d.get('channel','').lower() in conn,'admin':d.get('admin',False),'created_at':d.get('created_at','')} for u,d in users.items()]
    return jsonify({'users':result,'bot_running':running,'connected':conn,'logs':logs[-80:],'current_user':session.get('username','')})

@app.route('/api/admin/config', methods=['GET','POST'])
@admin_required
def api_admin_config():
    global config
    if request.method == 'POST':
        data = request.get_json() or {}
        if data.get('bot_token'): config['bot_token'] = data['bot_token']
        if data.get('lurk_message'): config['lurk_message'] = data['lurk_message']
        if data.get('unlurk_message'): config['unlurk_message'] = data['unlurk_message']
        save_config(config); return jsonify({'status':'saved'})
    return jsonify({**config,'bot_token':'●'*24 if config['bot_token'] else ''})

@app.route('/api/admin/bot/start', methods=['POST'])
@admin_required
def api_bot_start():
    if not config.get('bot_token'): return jsonify({'error':'Token bot manquant — configure-le dans Configuration'}), 400
    start_bot(); return jsonify({'status':'starting'})

@app.route('/api/admin/bot/stop', methods=['POST'])
@admin_required
def api_bot_stop():
    global bot_instance, bot_loop, bot_running
    if bot_instance and bot_loop and not bot_loop.is_closed():
        asyncio.run_coroutine_threadsafe(bot_instance.close(), bot_loop)
        add_log('Bot arrêté par admin', 'warning')
    else: bot_running = False
    return jsonify({'status':'stopping'})

@app.route('/api/admin/user/remove', methods=['POST'])
@admin_required
def api_remove_user():
    data = request.get_json() or {}
    target = data.get('username','').lower()
    users = load_users()
    if target not in users: return jsonify({'error':'Introuvable'}), 404
    if users[target].get('admin'): return jsonify({'error':'Impossible de supprimer un admin'}), 400
    ch = users[target].get('channel','')
    del users[target]; save_users(users)
    if bot_instance and bot_loop and bot_running and not bot_loop.is_closed() and ch:
        asyncio.run_coroutine_threadsafe(bot_instance.part_channels([ch]), bot_loop)
    add_log(f'Utilisateur supprimé : {target}', 'warning')
    return jsonify({'status':'removed'})

if __name__ == '__main__':
    if config.get('bot_token') and _get_channels():
        threading.Timer(2.0, start_bot).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
