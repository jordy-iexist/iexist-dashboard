"""Celery-taak: het maandrapport van één klant voor één maand.

Statussen op `monthly_reports`: pending → collecting → writing → completed, of failed met een
melding. Bij een fout blijven `data` en `report` van de vorige geslaagde run staan: ze worden
pas samen weggeschreven als de nieuwe run slaagt.

1. Atomair claimen: alleen een rij op `pending` wordt opgepakt (de taak kan na een
   worker-herstart opnieuw worden afgeleverd; dan niets doen).
2. Cijfers en werk verzamelen (`services/collect.py`). `manual` wordt bij de start gelezen en
   nooit door de taak geschreven; de router kan hem tijdens de run bijwerken.
3. Eén aanroep van de agent (`services/report_agent.write_report`). Het verbruik telt op in
   `ai_usage` (`add_usage` met het model dat werkelijk antwoordde).

Geen sleutels, prompts of klantgegevens in logregels en foutmeldingen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from app.db.models import CustomerWebsite, MonthlyReport as MonthlyReportRow
from app.db.session import SessionLocal
from app.features.competitor_analysis.mappers import _model
from app.features.competitor_analysis.schemas import AiUsage
from app.features.competitor_analysis.services.insights import NOT_CONFIGURED_MESSAGE, add_usage
from app.features.customers.profile import parse_profile
from app.features.customers.rankings import host_of
from app.features.monthly_report.mappers import manual_of
from app.features.monthly_report.schemas import ACTIVE_REPORT_STATUSES, ReportData, ReportText
from app.features.monthly_report.services import report_agent as agent
from app.features.monthly_report.services.collect import collect
from app.features.monthly_report.services.periods import previous_month
from app.services.anthropic.client import AnthropicServiceError
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

TIMEOUT_MESSAGE = "Het maken van het rapport duurde te lang en is afgebroken. Probeer het opnieuw."
GONE_MESSAGE = "De klant of het rapport bestaat niet meer."


class _Failed(Exception):
    """De run kan niet verder; de tekst is de melding voor de gebruiker."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- database ------------------------------------------------------------------------------


def _claim(report_id: str) -> bool:
    """`pending` → `collecting` in één update; False als de rij niet (meer) op `pending` staat."""
    with SessionLocal() as db:
        count = db.query(MonthlyReportRow).filter(
            MonthlyReportRow.id == report_id, MonthlyReportRow.status == "pending",
        ).update({"status": "collecting", "updated_at": _now()}, synchronize_session=False)
        db.commit()
        return count == 1


def _update(report_id: str, **fields: Any) -> None:
    """Werk het rapport bij (altijd `updated_at`), maar alleen zolang het actief is."""
    fields["updated_at"] = _now()
    with SessionLocal() as db:
        db.query(MonthlyReportRow).filter(
            MonthlyReportRow.id == report_id, MonthlyReportRow.status.in_(ACTIVE_REPORT_STATUSES),
        ).update(fields, synchronize_session=False)
        db.commit()


def _fail(report_id: str, message: str) -> None:
    try:
        _update(report_id, status="failed", error_message=message[:1000])
    except Exception:  # noqa: BLE001 - laatste poging; niets meer aan te doen
        logger.exception("Maandrapport %s: status 'failed' niet opgeslagen", report_id)


def _customer(customer: CustomerWebsite) -> Any:
    base_url = str(customer.base_url or "")
    return agent.ReportCustomer(
        name=customer.name or "",
        domain=host_of(base_url) or customer.domain or "",
        seo_goals=customer.seo_goals,
        tone_of_voice=customer.tone_of_voice,
        form_of_address=customer.form_of_address,
        profile=parse_profile(customer.profile),
    )


def _collect(report_id: str) -> tuple[ReportData, Any, int, AiUsage]:
    """Cijfers en werk, de klant voor de agent, de volgende tekstversie en het verbruik tot nu toe."""
    with SessionLocal() as db:
        row = db.get(MonthlyReportRow, report_id)
        customer = db.get(CustomerWebsite, row.customer_website_id) if row is not None else None
        if row is None or customer is None:
            raise _Failed(GONE_MESSAGE)
        previous_row = (
            db.query(MonthlyReportRow)
            .filter(MonthlyReportRow.customer_website_id == row.customer_website_id,
                    MonthlyReportRow.month == previous_month(row.month))
            .first()
        )
        data = collect(db, customer, row.month, previous_data=row.data, previous_month_row=previous_row,
                       manual=manual_of(row))
        previous = _model(ReportText, row.report)
        version = previous.version + 1 if previous is not None else 1
        return data, _customer(customer), version, _model(AiUsage, row.ai_usage) or AiUsage()


# --- de taak -------------------------------------------------------------------------------


def _run(report_id: str) -> None:
    data, customer, version, usage = _collect(report_id)
    _update(report_id, status="writing")
    result = agent.write_report(data, customer, version=version)
    if result.state != "ok" or result.report is None:
        raise _Failed(result.message or NOT_CONFIGURED_MESSAGE)
    usage = add_usage(usage, result.usage, result.model)
    _update(report_id, status="completed", data=data.model_dump(mode="json"),
            report=result.report.model_dump(mode="json"), model=result.model or None,
            ai_usage=usage.model_dump(mode="json"), error_message=None, completed_at=_now())


@celery_app.task(
    bind=True,
    name="app.worker.tasks.run_monthly_report_task",
    soft_time_limit=540,
    time_limit=600,
)
def run_monthly_report_task(self, report_id: str) -> str:
    """Verzamelt de cijfers en laat de tekst schrijven (zie de module-docstring)."""
    if not _claim(report_id):
        logger.info("Maandrapport %s niet gestart: niet gevonden of niet meer 'pending'.", report_id)
        return report_id
    try:
        _run(report_id)
    except SoftTimeLimitExceeded:
        logger.warning("Maandrapport %s: tijdslimiet bereikt.", report_id)
        _fail(report_id, TIMEOUT_MESSAGE)
    except AnthropicServiceError as exc:
        logger.warning("Maandrapport %s: Claude-fout (%s)", report_id, exc.code)
        _fail(report_id, f"Claude gaf een fout: {exc.message}")
    except _Failed as exc:
        logger.warning("Maandrapport %s mislukt: %s", report_id, exc)
        _fail(report_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Maandrapport %s onverwacht mislukt", report_id)
        _fail(report_id, f"Het maken van het rapport is gestopt door een interne fout ({type(exc).__name__}).")
    return report_id
