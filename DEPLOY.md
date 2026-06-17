# Deployment op Hetzner Cloud VPS (Docker + Caddy)

De volledige stack draait op één VPS via `docker-compose.prod.yml`:

```
                ┌─────────────────────── VPS ────────────────────────┐
Internet ──────▶│ Caddy (80/443, automatische HTTPS)                 │
                │   app.iexist.nl ──▶ frontend (Next.js, :3000)       │
                │   api.iexist.nl ──▶ api (FastAPI, :8000)            │
                │                      │                             │
                │   worker (Celery) ◀─┤── redis ── db (Postgres 16)  │
                └─────────────────────────────────────────────────────┘
```

De browser praat alleen met de frontend (`app.iexist.nl`), behalve voor
blog-afbeeldingen: die worden via signed URLs direct van `api.iexist.nl` geladen.

## 1. VPS aanmaken

- **Type:** Hetzner CPX31 (4 vCPU / 8 GB) aanbevolen. De Celery-worker draait
  Playwright Chromium voor crawls — dat is geheugenintensief. CPX21 (4 GB) is
  het absolute minimum.
- **Image:** Ubuntu 24.04.
- SSH-key toevoegen bij het aanmaken.

## 2. DNS

Maak **vóór de eerste start** twee A-records aan die naar het server-IP wijzen
(anders kan Caddy geen Let's Encrypt-certificaat ophalen):

```
app.iexist.nl  A  <server-ip>
api.iexist.nl  A  <server-ip>
```

## 3. Server voorbereiden

```bash
# Docker Engine + compose-plugin (officiële Docker repo)
curl -fsSL https://get.docker.com | sh

# Firewall
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

## 4. Project en configuratie

```bash
git clone <repo-url> iexist-dashboard
cd iexist-dashboard
```

**Root `.env`** (compose-variabelen):

```bash
cp .env.production.example .env
# Vul in: DOMAIN, POSTGRES_PASSWORD (openssl rand -hex 24), Supabase keys, ALLOWED_IPS
```

**`ALLOWED_IPS`** beperkt de toegang tot `app.iexist.nl` (het dashboard) tot je
eigen IP('s). Caddy geeft al het overige verkeer een `403 Forbidden`. `api.iexist.nl`
blijft publiek — dat is nodig voor blog-afbeeldingen die via signed URLs door
bezoekers/WordPress geladen worden. Achterhaal je publieke IP met `curl ifconfig.me`.
Meerdere IP's/ranges **spatiegescheiden** (geen komma's), bv. `"91.215.151.210 84.22.33.44"`
— bij meerdere zijn de quotes verplicht.

IP's later wijzigen kan zonder rebuild — alleen Caddy herladen:

```bash
# pas ALLOWED_IPS aan in .env, daarna:
docker compose -f docker-compose.prod.yml up -d caddy
```

**`backend/.env`** (backend-secrets):

```bash
cp backend/.env.example backend/.env
```

Pas daarin minimaal aan:

| Variabele | Waarde |
|---|---|
| `JWT_SECRET_KEY` | `openssl rand -hex 32` — verplicht, app start niet met placeholder |
| `STORAGE_SIGNING_SECRET` | `openssl rand -hex 32` — verplicht |
| `WORDPRESS_CREDENTIALS_KEY` | Fernet-key: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `CELERY_QUEUES` | `default,blog_generation,image_generation,audit` — **let op:** het voorbeeld mist `audit`; zonder die queue draaien website-audits nooit |
| `SERPAPI_API_KEY` | optioneel (SEO-tracker) |

`DATABASE_URL`, `REDIS_URL`, `MEDIA_BASE_URL` en `CORS_ALLOWED_ORIGINS` worden
door `docker-compose.prod.yml` overschreven — wat er in `backend/.env` staat
maakt daarvoor niet uit.

## 5. Starten

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

- Alembic-migrations draaien automatisch bij het starten van de API-container
  (`backend/scripts/start-api.sh`).
- Caddy haalt bij de eerste request certificaten op voor beide subdomeinen.

Controleren:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api worker caddy
```

## 6. Updaten (nieuwe release)

```bash
cd iexist-dashboard
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker image prune -f   # oude image-lagen opruimen
```

## 7. Backups (aanbevolen)

Dagelijkse database-dump via cron (`crontab -e`):

```cron
0 3 * * * cd /root/iexist-dashboard && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U csv_blog_generator csv_blog_generator | gzip > /root/backups/db-$(date +\%F).sql.gz
```

Neem ook de media-volume mee (geüploade/gegenereerde blog-afbeeldingen):

```bash
docker run --rm -v iexist-dashboard_backend_media:/media -v /root/backups:/backup \
  alpine tar czf /backup/media-$(date +%F).tar.gz -C /media .
```

Bewaar backups bij voorkeur ook buiten de server (bv. Hetzner Storage Box).

## Troubleshooting

- **Geen certificaat / "connection refused":** klopt de DNS? `dig app.iexist.nl`
  moet het server-IP geven. Check `docker compose ... logs caddy`.
- **API weigert te starten:** vrijwel altijd een placeholder-secret;
  `validate_required_secrets` blokkeert lege of `change-me`-waarden.
- **Afbeeldingen laden niet:** `MEDIA_BASE_URL` moet `https://api.iexist.nl`
  zijn (zet compose automatisch) en `api.iexist.nl` moet publiek bereikbaar zijn.
- **Jobs blijven op `pending`:** draait de worker? Staat de juiste queue in
  `CELERY_QUEUES`? Check `docker compose ... logs worker`.
