# CONTEXT

Glossary van het domein. Geen implementatiedetails.

## Klant

Een klant van het bureau, gerepresenteerd door zijn website (`CustomerWebsite` in code, "Klant" in de UI). Een klant heeft precies één website (naam + domein). Klanten zijn **team-globaal**: elke gebruiker ziet en gebruikt dezelfde klantenlijst. Een klant wordt gearchiveerd via deactiveren, niet verwijderd.

Zie [docs/adr/0001-klanten-team-globaal.md](docs/adr/0001-klanten-team-globaal.md).

## Gekoppelde content

Een blog of landingspagina hoort aan **maximaal één klant**, of is "zonder klant". De koppeling ontstaat op drie manieren:

1. **Bij CSV-upload** — automatisch gematcht: blogs op klantnaam (hoofdletterongevoelig, exact), landingspagina's op website-domein.
2. **Bij handmatige invoer** — expliciet gekozen per rij.
3. **Achteraf** — per blog/landingspagina aan te passen of te ontkoppelen.

Geen match betekent: wél genereren, niet koppelen. Klanten worden nooit automatisch aangemaakt vanuit een upload.

## Blogtitel

De blogtitel is de primaire H1-kop van de bloginhoud.

## Hero-afbeelding (uitgelichte afbeelding)

De primaire afbeelding van een blog, bedoeld om als hero/featured image te dienen. Wordt automatisch gegenereerd in **16:9** breedbeeld zodat hij bovenaan een artikel of als uitgelichte afbeelding past. Per blog is er hooguit één primaire afbeelding (`is_primary`); een handmatige upload heeft voorrang op de automatisch gegenereerde.

Zie [docs/adr/0002-hero-afbeelding-16-9.md](docs/adr/0002-hero-afbeelding-16-9.md).

## Stijl-instructie

De aanpasbare stijlzin die de gebruiker meegeeft aan de afbeeldingsgeneratie (bijv. "modern, editorial, clean, geen tekst of logo's"). Het systeem plakt hier automatisch de blogtitel en een samenvatting van de bloginhoud achter; samen vormen ze de prompt. Leeg = systeemstandaard. Staat los van de **Systemprompt**, die de tekstgeneratie van de blog stuurt.

## Share-link

De publieke leeslink van een blog of landingspagina. Werkt voor iedereen met de link. Dit is het artefact dat naar de linkbuilding-partij gaat: die plaatst de content op haar eigen websites, dus zij ontvangt share-links, geen gepubliceerde klant-URLs.

## Scope (mine / shared / all)

Bestaande zichtbaarheidsindeling van blogs en landingspagina's per gebruiker ("Van mij" / "Gedeeld met mij" / "Alle"). Staat los van de klant-koppeling: het klantfilter werkt binnen elke scope.
