"""Eenmalig: haal een refresh token op voor Google Search Console.

Gebruikt de OAuth desktop-client (GSC_CLIENT_ID en GSC_CLIENT_SECRET in backend/.env).
Log in met het Google-account dat alle klanten als property heeft.

    docker compose run --rm api python scripts/gsc_authorize.py

Het script print een link. Open die in de browser en geef toestemming. De browser
stuurt daarna door naar http://127.0.0.1:8765/?code=... en toont een foutpagina
("kan geen verbinding maken"): dat klopt. Kopieer de volledige URL uit de adresbalk
en plak die hier. Zet daarna de geprinte regel GSC_REFRESH_TOKEN=... in backend/.env
en herstart api en worker.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Google geeft soms extra of anders geordende scopes terug; dat is geen fout.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import google_auth_httplib2  # noqa: E402
import httplib2  # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.search_console import client as gsc  # noqa: E402

REDIRECT_URI = "http://127.0.0.1:8765"


def main() -> int:
    client_id = settings.gsc_client_id.strip()
    client_secret = settings.gsc_client_secret.strip()
    if not client_id or not client_secret:
        print("Zet eerst GSC_CLIENT_ID en GSC_CLIENT_SECRET (van de OAuth desktop-client) in backend/.env.")
        return 1

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": gsc.TOKEN_URI,
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=gsc.SCOPES,
    )
    flow.redirect_uri = REDIRECT_URI
    # prompt=consent: Google geeft alleen dan opnieuw een refresh token af.
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")

    print("\n1. Open deze link en log in met het Google-account met alle klant-properties:\n")
    print(auth_url)
    print(f"\n2. Na toestemming stuurt de browser door naar {REDIRECT_URI}/?... (foutpagina is normaal).")
    pasted = input("3. Plak hier de volledige URL uit de adresbalk: ").strip()

    query = parse_qs(urlparse(pasted).query)
    if query.get("error"):
        print(f"Google gaf een fout terug: {query['error'][0]}")
        return 1
    code = (query.get("code") or [""])[0] or (pasted if "://" not in pasted else "")
    if not code:
        print("Geen code gevonden in de geplakte URL.")
        return 1
    if query.get("state") and query["state"][0] != state:
        print("De geplakte URL hoort niet bij deze sessie (state komt niet overeen). Start opnieuw.")
        return 1

    flow.fetch_token(code=code)
    credentials = flow.credentials
    if not credentials.refresh_token:
        print("Google gaf geen refresh token terug. Trek de toegang van de app in via "
              "https://myaccount.google.com/permissions en probeer het opnieuw.")
        return 1

    print("\nZet deze regel in backend/.env en herstart api en worker:\n")
    print(f"GSC_REFRESH_TOKEN={credentials.refresh_token}\n")

    try:
        service = gsc.get_service(
            google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=30))
        )
        sites = gsc.list_sites(service=service)
    except gsc.SearchConsoleServiceError as exc:
        print(f"Let op: de properties konden niet worden opgehaald: {exc}")
        return 0
    print(f"Controle: dit account heeft toegang tot {len(sites)} properties.")
    for site in sites[:10]:
        print(f"  {site['site_url']} ({site['permission']})")
    if len(sites) > 10:
        print(f"  ... en {len(sites) - 10} meer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
