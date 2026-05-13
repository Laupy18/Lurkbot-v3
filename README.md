[README.md](https://github.com/user-attachments/files/27695955/README.md)
# 🤖 Lurkbot Panel v3 — Multi-utilisateurs

## Fonctionnement
1. Les VTubers s'inscrivent sur le panel web
2. Le bot rejoint leur canal automatiquement
3. Ils tapent `!addbot` dans leur chat Twitch pour activer
4. Les commandes `!lurk` et `!unlurk` sont disponibles

## Variables d'environnement (Railway)
| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Token OAuth du bot Twitch (`oauth:xxx`) |
| `SECRET_KEY` | Clé secrète Flask (génère une chaîne aléatoire) |
| `PORT` | Port (géré automatiquement par Railway) |

## Déploiement Railway
1. Push le code sur GitHub
2. New Project → Deploy from GitHub
3. Settings → Variables → ajoute BOT_TOKEN et SECRET_KEY
4. Settings → Networking → Generate Domain
