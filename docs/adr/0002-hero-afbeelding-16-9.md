# 0002 — Hero-afbeelding native 16:9 via gpt-image-2 op 2048×1152

Datum: 2026-06-17
Status: geaccepteerd

## Context

Per blog kan automatisch een afbeelding worden gegenereerd. Die moet bruikbaar zijn als hero-/uitgelichte afbeelding en dus **16:9** breedbeeld zijn. De oorspronkelijke implementatie genereerde vierkant (`1024×1024`) via één globale env-var.

De gewenste maat was `1920×1080`. OpenAI's `gpt-image-2` weigert die echter: custom maten moeten aan beide zijden een **veelvoud van 16** zijn, en `1080` is dat niet. Geldige nette 16:9-maten zijn `2048×1152` en `3840×2160` (4K).

## Besluit

- Hero-afbeeldingen worden **native in 16:9** gegenereerd; standaard `2048×1152`. Geen post-processing (croppen/resizen) — dus geen Pillow-dependency.
- De **Images-API met `gpt-image-2`** is de primaire generatieroute, zodat de per-gebruiker instelbare maat, model en kwaliteit daadwerkelijk worden toegepast. De oudere Responses-API blijft als fallback (alleen maat, geen custom model/kwaliteit).
- Afbeeldingsgeneratie-instellingen (stijl-instructie, maat, model, kwaliteit) staan per gebruiker als nullable overrides op `blog_generation_settings`, met fallback naar systeemstandaarden — hetzelfde patroon als de tekst-settings.

## Alternatieven

- **`1920×1080` afdwingen** — verworpen: ongeldig bij `gpt-image-2` (1080 ≠ veelvoud van 16).
- **3:2 (`1536×1024`) accepteren als "dichtbij genoeg"** — verworpen: geen echte 16:9, hero-crops zouden afwijken.
- **3:2 genereren en server-side croppen/resizen naar 16:9** — verworpen: onnodig nu het model native 16:9 levert; zou een image-library (Pillow) en een extra verwerkingsstap toevoegen.
- **Responses-API primair houden** — verworpen: kan geen custom image-model (`gpt-image-2`) of kwaliteit honoreren, waardoor de gebruikersinstellingen genegeerd zouden worden.

## Gevolgen

- De standaard-maat/-model wijzigen (`OPENAI_IMAGE_SIZE`, `OPENAI_IMAGE_MODEL`) is eenvoudig terug te draaien; de keuze voor native 16:9 boven croppen is dat ook zolang het model 16:9-maten blijft ondersteunen.
- `BlogImage.width`/`height` worden afgeleid uit de gevraagde maat. Bij de Responses-API-fallback zónder maat-parameter kunnen de werkelijke afmetingen afwijken van wat is opgeslagen.
- Toekomstige lezers: kies bij custom maten alleen veelvouden van 16, langste zijde ≤ 3840, ratio ≤ 3:1.
