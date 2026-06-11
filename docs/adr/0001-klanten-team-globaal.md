# 0001 — Klanten zijn team-globaal (single-tenant)

Datum: 2026-06-11
Status: geaccepteerd

## Context

Blogs en landingspagina's worden gekoppeld aan klanten (`customer_websites`). Vóór dit besluit was elke `CustomerWebsite` strikt gescoped op `created_by`: alleen de aanmaker zag en gebruikte hem (SEO-tracker, meta-optimizer). Blogs en landingspagina's kenden al een deel-mechanisme (`is_public`), waardoor content van collega's zichtbaar kan zijn — maar de klant van die content zou dan onzichtbaar of onfilterbaar zijn.

## Besluit

De app is een **interne tool voor één bureau**. Alle gebruikers zijn teamleden:

- De klantenlijst is globaal: iedere gebruiker leest, gebruikt, bewerkt en deactiveert alle klanten. `created_by` blijft bestaan als "aangemaakt door"-metadata, maar is geen queryfilter meer.
- Consequentie (bewust geaccepteerd): ook de SEO-tracker en meta-optimizer tonen alle websites, keywords, scans en runs aan alle gebruikers, en iedereen kan elkaars scans inzien en annuleren.

## Alternatieven

- **Per gebruiker laten** — verworpen: het klantfilter zou gedeelde content van collega's niet kunnen filteren, en elke klant zou per gebruiker opnieuw aangemaakt moeten worden.
- **Organisatie/team-model** — verworpen (voor nu): correcte oplossing als er ooit meerdere losse bureaus op de app moeten, maar fors werk (org-scoping door elke feature, migratie, auth). Pas nodig als multi-tenancy een echte eis wordt.

## Gevolgen

- Eén klant-begrip app-breed; nieuwe neutrale endpoints (`/api/customers`) naast de bestaande `/api/seo/websites`.
- Terugdraaien is lastig: zodra teamleden op elkaars klanten content en keywords bouwen, is er geen eenduidige eigenaar meer om naar terug te scopen.
- De duplicate-domein-check is globaal: twee gebruikers kunnen geen klant met hetzelfde domein aanmaken.
