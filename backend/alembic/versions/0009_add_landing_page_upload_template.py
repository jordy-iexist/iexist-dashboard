"""add landing page upload template

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE = (
    "Opdracht: Schrijf een informatieve SEO-geoptimaliseerde landingspagina van minimaal {lengte} woorden voor de website {website}.\n"
    "\n"
    "Het onderwerp van de landingspagina is: {onderwerp}.\n"
    "\n"
    "Doel van de landingspagina: bezoekers informeren en aanzetten tot het doen van een offerte aanvraag. Benoem duidelijk hoe {website} de bezoeker kan helpen.\n"
    "\n"
    "Stijl:\n"
    "\n"
    "Gebruik duidelijke, korte zinnen.\n"
    "\n"
    "Gebruik actieve taal (geen \"er wordt gekeken naar…\" maar \"de bank kijkt naar…\").\n"
    "\n"
    "Gebruik H2- en H3-tussenkoppen met zoekwoorden erin verwerkt. Verwerk de H2 en H3 tussenkoppen met opmaak, dus niet als H2: en H3:.\n"
    "\n"
    "Gebruik maximaal 1 opsomming in de pagina.\n"
    "\n"
    "Sluit af met een korte samenvatting en een call-to-action naar {website}.\n"
    "\n"
    "SEO-richtlijnen:\n"
    "\n"
    "Gebruik de primaire zoekwoorden elk minimaal 2–3 keer, verspreid over de tekst en in minstens één tussenkop:\n"
    "\n"
    "{primaire_zoekwoorden}\n"
    "\n"
    "Gebruik de secundaire zoekwoorden minimaal één keer, verspreid over de tekst:\n"
    "\n"
    "{secundaire_zoekwoorden}\n"
    "\n"
    "Structuur van de pagina:\n"
    "\n"
    "Titel met hoofdzoekwoord.\n"
    "\n"
    "Introductie: kort, pakkend, en met het hoofdzoekwoord in de eerste alinea.\n"
    "\n"
    "Informatieve hoofdsecties (H2's):\n"
    "\n"
    "Beantwoord de belangrijkste vragen van de doelgroep over het onderwerp.\n"
    "\n"
    "Conclusie + samenvatting + CTA: vat de kern samen en voeg een duidelijke oproep toe.\n"
    "\n"
    "FAQ-sectie:\n"
    "\n"
    "Voeg 6 relevante veelgestelde vragen en antwoorden toe.\n"
    "\n"
    "Antwoorden zijn kort (50–100 woorden) en informatief.\n"
    "\n"
    "FAQ's moeten aansluiten bij het onderwerp en long-tail zoektermen bevatten."
)


def upgrade() -> None:
    op.add_column(
        "landing_page_uploads",
        sa.Column("template", sa.Text(), nullable=True),
    )

    landing_page_uploads = sa.table(
        "landing_page_uploads",
        sa.column("template", sa.Text()),
    )
    op.execute(
        landing_page_uploads.update().values(
            template=DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE
        )
    )

    op.alter_column("landing_page_uploads", "template", nullable=False)


def downgrade() -> None:
    op.drop_column("landing_page_uploads", "template")
