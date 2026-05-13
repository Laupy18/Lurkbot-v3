"""
TwitchBot Panel v2 — Multi-utilisateurs avec authentification
Chaque VTuber crée un compte, entre son canal, et tape !addbot dans son chat pour activer.
"""

import threading, asyncio, json, os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import twitchio
from twitchio.ext import commands

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changez-moi-en-production-svp')

# ── Fichiers de données ──────────────────────────
USERS_FILE  = 'users.json'
CONFIG_FILE = 'config.json'

DEFAULT_CONFIG = {
    'bot_token':       os.environ.get('BOT_TOKEN', ''),
    'lurk_message':    '{user} part en mode lurk dans les buissons... 👀🌿',
    'unlurk_message':  '👋 {user} est de retour ! Bienvenue !'
}

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f: return json.load(f)
    return {}

def save_users(u):
    with open(USERS_FILE, 'w') as f: json.dump(u, f, indent=2, ensure_ascii=False)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f: return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()

def save_config(c):
    with open(CONFIG_FILE, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)

config = load_config()

# ── Auth decorators ──────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login_page'))
        users = load_users()
        if not users.get(session['username'], {}).get('admin', False):
            return jsonify({'error': 'Accès admin requis'}), 403
        return f(*args, **kwargs)
    return decorated

# ── Logs ─────────────────────────────────────────
logs = []

def add_log(msg, level='info', channel=None):
    entry = {
        'time':    datetime.now().strftime('%H:%M:%S'),
        'msg':     msg,
        'level':   level,
        'channel': channel or ''
    }
    logs.append(entry)
    if len(logs) > 500: logs.pop(0)
    print(f"[{entry['time']}] [{level.upper()}] {msg}")

# ── Bot Twitch ────────────────────────────────────
bot_instance = None
bot_thread   = None
bot_loop     = None
bot_running  = False

class TwitchBot(commands.Bot):

    def __init__(self, token, channels, lurk_msg, unlurk_msg):
        super().__init__(token=token, prefix='!', initial_channels=channels if channels else ['__placeholder__'])
        self.lurk_msg   = lurk_msg
        self.unlurk_msg = unlurk_msg

    async def event_ready(self):
        add_log(f'Bot connecté : {self.nick}', 'success')
        for ch in self.connected_channels:
            add_log(f'Canal rejoint : #{ch.name}', 'info', ch.name)

    async def event_message(self, message):
        if message.echo: return
        await self.handle_commands(message)

    @commands.command(name='addbot')
    async def addbot(self, ctx):
        """Active le bot sur ce canal si une inscription est en attente."""
        users   = load_users()
        channel = ctx.channel.name.lower()
        for username, data in users.items():
            if data.get('channel','').lower() == channel and data.get('status') == 'pending':
                users[username]['status'] = 'active'
                save_users(users)
                await ctx.send(f'✅ Bot activé sur #{channel} ! Bienvenue {ctx.author.name} 🎉 — Commandes : !lurk / !unlurk')
                add_log(f'#{channel} activé par {ctx.author.name}', 'success', channel)
                return
        # Déjà actif
        if any(d.get('channel','').lower() == channel and d.get('status') == 'active' for d in users.values()):
            await ctx.send('ℹ️ Le bot est déjà actif sur ce canal !')

    @commands.command(name='lurk')
    async def lurk(self, ctx):
        users   = load_users()
        channel = ctx.channel.name.lower()
        if not any(d.get('channel','').lower() == channel and d.get('status') == 'active' for d in users.values()):
            return
        await ctx.send(self.lurk_msg.format(user=ctx.author.name))
        add_log(f'{ctx.author.name} → !lurk', 'command', channel)

    @commands.command(name='unlurk')
    async def unlurk(self, ctx):
        users   = load_users()
        channel = ctx.channel.name.lower()
        if not any(d.get('channel','').lower() == channel and d.get('status') == 'active' for d in users.values()):
            return
        await ctx.send(self.unlurk_msg.format(user=ctx.author.name))
        add_log(f'{ctx.author.name} → !unlurk', 'command', channel)

    async def event_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound): return
        add_log(f'Erreur commande : {error}', 'error')


def _get_all_channels():
    users = load_users()
    return [d['channel'] for d in users.values() if d.get('channel') and d.get('status') in ('pending','active')]

def _run_bot(token, channels, lurk_msg, unlurk_msg):
    global bot_instance, bot_loop, bot_running
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot_instance = TwitchBot(token, channels, lurk_msg, unlurk_msg)
    try:
        bot_running = True
        bot_instance.run()
    except Exception as e:
        add_log(f'Erreur fatale : {e}', 'error')
    finally:
        bot_running = False
        add_log('Bot arrêté', 'warning')

def start_bot_if_needed():
    global bot_thread
    if bot_thread and bot_thread.is_alive(): return
    token = config.get('bot_token','')
    if not token: return
    channels = _get_all_channels()
    bot_thread = threading.Thread(
        target=_run_bot,
        args=(token, channels, config['lurk_message'], config['unlurk_message']),
        daemon=True
    )
    bot_thread.start()
    add_log('Bot démarré', 'info')

def join_live(channel):
    if bot_instance and bot_loop and bot_running and not bot_loop.is_closed():
        asyncio.run_coroutine_threadsafe(bot_instance.join_channels([channel]), bot_loop)
        add_log(f'Rejoint #{channel} en direct', 'success', channel)

# ── Routes pages ─────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'username' in session else url_for('login_page'))

@app.route('/login')
def login_page():
    if 'username' in session: return redirect(url_for('dashboard'))
    return render_template('auth.html', mode='login')

@app.route('/register')
def register_page():
    if 'username' in session: return redirect(url_for('dashboard'))
    return render_template('auth.html', mode='register')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# ── API Auth ──────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    password = data.get('password','')
    users = load_users()
    user  = users.get(username)
    if user and check_password_hash(user['password'], password):
        session['username'] = username
        return jsonify({'status': 'ok', 'admin': user.get('admin', False)})
    return jsonify({'error': 'Identifiants incorrects'}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    data     = request.get_json() or {}
    username = data.get('username','').strip().lower()
    password = data.get('password','')
    channel  = data.get('channel','').strip().lower().lstrip('#')

    if not all([username, password, channel]):
        return jsonify({'error': 'Tous les champs sont requis'}), 400
    if len(username) < 3:
        return jsonify({'error': "Nom d'utilisateur trop court (3 min)"}), 400
    if len(password) < 6:
        return jsonify({'error': 'Mot de passe trop court (6 min)'}), 400

    users = load_users()
    if username in users:
        return jsonify({'error': "Ce nom d'utilisateur existe déjà"}), 400
    if any(d.get('channel','').lower() == channel for d in users.values()):
        return jsonify({'error': 'Ce canal Twitch est déjà enregistré'}), 400

    is_admin = len(users) == 0   # Premier compte = admin
    users[username] = {
        'password':   generate_password_hash(password),
        'channel':    channel,
        'status':     'pending',
        'admin':      is_admin,
        'created_at': datetime.now().isoformat()
    }
    save_users(users)
    session['username'] = username

    # Rejoindre le canal ou démarrer le bot
    if bot_running:
        join_live(channel)
    else:
        start_bot_if_needed()

    add_log(f'Inscription : {username} → #{channel}', 'info', channel)
    return jsonify({'status': 'ok', 'admin': is_admin, 'pending': True})

# ── API Utilisateur ───────────────────────────────

@app.route('/api/me')
@login_required
def api_me():
    users = load_users()
    user  = users.get(session['username'], {})
    ch    = user.get('channel','')
    connected_channels = []
    if bot_instance and bot_running:
        connected_channels = [c.name.lower() for c in bot_instance.connected_channels]
    return jsonify({
        'username':  session['username'],
        'channel':   ch,
        'status':    user.get('status','pending'),
        'admin':     user.get('admin', False),
        'connected': ch.lower() in connected_channels,
        'bot_running': bot_running and bot_thread and bot_thread.is_alive(),
        'logs': [l for l in logs[-40:] if not l['channel'] or l['channel'].lower() == ch.lower() or user.get('admin')]
    })

# ── API Admin ─────────────────────────────────────

@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    users = load_users()
    running = bot_running and bot_thread and bot_thread.is_alive()
    connected_channels = []
    if bot_instance and running:
        connected_channels = [c.name.lower() for c in bot_instance.connected_channels]
    result = []
    for uname, data in users.items():
        ch = data.get('channel','')
        result.append({
            'username':  uname,
            'channel':   ch,
            'status':    data.get('status','pending'),
            'connected': ch.lower() in connected_channels,
            'admin':     data.get('admin', False),
            'created_at': data.get('created_at','')
        })
    return jsonify({'users': result, 'bot_running': running, 'logs': logs[-60:]})

@app.route('/api/admin/config', methods=['GET', 'POST'])
@admin_required
def api_admin_config():
    global config
    if request.method == 'POST':
        data = request.get_json() or {}
        if data.get('bot_token'):    config['bot_token']      = data['bot_token']
        if data.get('lurk_message'): config['lurk_message']   = data['lurk_message']
        if data.get('unlurk_message'): config['unlurk_message'] = data['unlurk_message']
        save_config(config)
        return jsonify({'status': 'saved'})
    safe = {**config, 'bot_token': '●' * 24 if config['bot_token'] else ''}
    return jsonify(safe)

@app.route('/api/admin/bot/start', methods=['POST'])
@admin_required
def api_bot_start():
    if not config.get('bot_token'):
        return jsonify({'error': 'Token bot manquant — configure-le d\'abord'}), 400
    start_bot_if_needed()
    return jsonify({'status': 'starting'})

@app.route('/api/admin/bot/stop', methods=['POST'])
@admin_required
def api_bot_stop():
    global bot_instance, bot_loop, bot_running
    if bot_instance and bot_loop and not bot_loop.is_closed():
        asyncio.run_coroutine_threadsafe(bot_instance.close(), bot_loop)
        add_log('Bot arrêté par admin', 'warning')
    else:
        bot_running = False
    return jsonify({'status': 'stopping'})

@app.route('/api/admin/user/remove', methods=['POST'])
@admin_required
def api_remove_user():
    data = request.get_json() or {}
    target = data.get('username','').lower()
    users  = load_users()
    if target not in users:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if users[target].get('admin'):
        return jsonify({'error': 'Impossible de supprimer un admin'}), 400
    ch = users[target].get('channel','')
    del users[target]
    save_users(users)
    # Quitter le canal si bot actif
    if bot_instance and bot_loop and bot_running and not bot_loop.is_closed() and ch:
        asyncio.run_coroutine_threadsafe(bot_instance.part_channels([ch]), bot_loop)
    add_log(f'Utilisateur supprimé : {target}', 'warning')
    return jsonify({'status': 'removed'})

# ── Lancement ─────────────────────────────────────
if __name__ == '__main__':
    if config.get('bot_token') and _get_all_channels():
        threading.Timer(2.0, start_bot_if_needed).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
