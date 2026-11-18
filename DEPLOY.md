# Deployment op Hetzner Cloud VPS (Docker + Caddy)

De volledige stack draait op één VPS via `docker-compose.prod.yml`:

```
                ┌─────────────────────── VPS ────────────────────────┐
Internet ──────▶│ Caddy (80/443, automatische HTTPS)                 │
                │   app.iexist.nl ──▶ frontend (Next.js, :3000)       │
                │   api.iexist.nl ──▶ api (FastAPI, :8000)            │
                │                      │                             │
                │   worker (Celery) ◀─┤── redis ── db (Postgres 16)  │
                │   beat (Celery, planning) ──▶ redis                │
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
| `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` | optioneel (Search Console in livegang fase 4). Neem de drie waarden over uit de lokale `backend/.env`; het refresh token is niet aan een machine gebonden. Een nieuw token maak je met `docker compose -f docker-compose.prod.yml run --rm api python scripts/gsc_authorize.py` |
| `BING_CLIENT_ID`, `BING_CLIENT_SECRET`, `BING_WEBMASTER_REDIRECT_URI` | optioneel (Bing Webmaster in livegang fase 4). Client-ID en -secret van de OAuth-client bij Bing Webmaster → Settings → API Access. De redirect-URI is `https://app.iexist.nl/api/bing-webmaster/callback` en moet exact gelijk zijn aan die bij Bing. Daarna koppel je één keer met de knop **Koppel Bing Webmaster** bij fase 4 van een klant; het token staat versleuteld in de database (`oauth_connections`), dus elke omgeving koppelt zelf. Zet `BING_WEBMASTER_API_KEY` **niet** in productie: die is voor lokaal testen en heeft schrijfrechten |

Bing accepteert geen `localhost` als redirect-URI. Lokaal test je Bing daarom met
`BING_WEBMASTER_API_KEY` (zelfde data, geen OAuth). Wil je de OAuth-flow toch lokaal
doorlopen: klik lokaal op **Koppel Bing Webmaster**, geef toestemming, en vervang in de
adresbalk van de pagina waar je uitkomt `https://app.iexist.nl` door
`http://localhost:3000` (binnen 5 minuten, zolang is de code geldig).

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
docker compose -f docker-compose.prod.yml logs -f api worker beat caddy
```

### Geplande taken (Celery beat)

De service `beat` plant periodieke taken in; het werk zelf doet `worker` (queue
`audit`). Draai er **precies één** van, anders gaat elke taak dubbel. Redis bewaart
niets, dus het schedule-bestand staat in de container (`/tmp/celerybeat-schedule`).

- **Dagelijkse sitemap-monitor** (livegang): elke dag om `SITEMAP_MONITOR_HOUR`
  (standaard 5, Europe/Amsterdam, na de back-up van 03:00) krijgt elke klant met de
  schakelaar aan en een voltooide nulmeting een korte run die alleen nieuwe en
  gewijzigde pagina's uit de sitemap scant. De eerste run legt alleen de
  uitgangssituatie vast. Instellingen in `backend/.env`: `SITEMAP_MONITOR_ENABLED`
  (`false` = noodrem voor de dagelijkse run; "Nu controleren" blijft werken),
  `SITEMAP_MONITOR_MAX_URLS`, `SITEMAP_MONITOR_MAX_PAGES_PER_RUN`.
- Handmatig één keer starten (alle klanten):
  `docker compose -f docker-compose.prod.yml exec worker celery -A app.worker.celery_app call app.worker.tasks.run_sitemap_monitor_dispatch_task`

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
- **Sitemap-monitor draait niet:** toont `docker compose ... logs beat` het schema
  (`sitemap-monitor-dagelijks`)? Staat `SITEMAP_MONITOR_ENABLED` niet op `false`, en
  heeft de worker de queue `audit`?
