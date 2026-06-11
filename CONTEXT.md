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

## Share-link

De publieke leeslink van een blog of landingspagina. Werkt voor iedereen met de link. Dit is het artefact dat naar de linkbuilding-partij gaat: die plaatst de content op haar eigen websites, dus zij ontvangt share-links, geen gepubliceerde klant-URLs.

## Scope (mine / shared / all)

Bestaande zichtbaarheidsindeling van blogs en landingspagina's per gebruiker ("Van mij" / "Gedeeld met mij" / "Alle"). Staat los van de klant-koppeling: het klantfilter werkt binnen elke scope.
