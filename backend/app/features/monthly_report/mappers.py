"""Rijen van `monthly_reports` omzetten naar het antwoord van `/api/monthly-reports`.

Pure functies. Verdraagzaam voor lege of ongeldige JSON-kolommen: die worden `None`, zodat
elk endpoint in elke fase van een run een geldig antwoord geeft. De aanvragen (`Leads`) worden
bij elk lezen opnieuw berekend uit `manual` van deze rij en van het rapport van de vorige maand.
"""
from __future__ import annotations

from typing import Any

from app.db.models import MonthlyReport as MonthlyReportRow
from app.features.competitor_analysis.mappers import _choice, _model
from app.features.competitor_analysis.schemas import AiUsage
from app.features.monthly_report.schemas import (
    Leads,
    Manual,
    MonthlyReport,
    ReportData,
    ReportStatus,
    ReportText,
)


def manual_of(row: MonthlyReportRow | None) -> Manual | None:
    return _model(Manual, row.manual) if row is not None else None


def leads_from(manual: Manual | None, previous_manual: Manual | None) -> Leads:
    """`previous` uit `manual.leads_previous`; anders `leads` van het rapport van de vorige maand."""
    value = manual.leads if manual is not None else None
    previous, source = None, None
    if manual is not None and manual.leads_previous is not None:
        previous, source = manual.leads_previous, "manual"
    elif previous_manual is not None and previous_manual.leads is not None:
        previous, source = previous_manual.leads, "previous_report"
    return Leads(
        value=value,
        previous=previous,
        previous_source=source,
        updated_at=manual.updated_at if manual is not None else None,
    )


def effective_leads(row: MonthlyReportRow | None, previous_row: MonthlyReportRow | None) -> Leads:
    return leads_from(manual_of(row), manual_of(previous_row))


def text_outdated(row: MonthlyReportRow | None, leads: Leads) -> bool:
    """True als er tekst is en de aanvragen afwijken van wat de agent bij het schrijven kreeg."""
    if row is None or _model(ReportText, row.report) is None:
        return False
    data = _model(ReportData, row.data)
    written: tuple[Any, Any] = (None, None)
    if data is not None:
        written = (data.metrics.leads.value, data.metrics.leads.previous)
    return (leads.value, leads.previous) != written


def to_monthly_report(
    row: MonthlyReportRow | None,
    *,
    customer_id: str,
    month: str,
    previous_row: MonthlyReportRow | None,
) -> MonthlyReport:
    """Het antwoord voor één klant en maand; zonder rij een leeg `draft`-antwoord."""
    leads = effective_leads(row, previous_row)
    if row is None:
        return MonthlyReport(customer_website_id=customer_id, month=month, leads=leads)
    return MonthlyReport(
        id=row.id,
        customer_website_id=row.customer_website_id,
        month=row.month,
        status=_choice(row.status, ReportStatus) or "failed",
        error_message=row.error_message,
        model=row.model,
        ai_usage=_model(AiUsage, row.ai_usage) or AiUsage(),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        leads=leads,
        text_outdated=text_outdated(row, leads),
        data=_model(ReportData, row.data),
        report=_model(ReportText, row.report),
    )
