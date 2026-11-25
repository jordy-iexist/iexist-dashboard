from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SignalKind = Literal["daling", "storing", "werk", "rapport"]
SignalSeverity = Literal["hoog", "middel", "laag"]
LinkType = Literal["customer_home", "monthly_report", "customer_profile", "seo_geo", "work_board", "none"]
RankState = Literal["ok", "not_configured", "not_tracked", "error", "missing"]


class SignalLink(BaseModel):
    # De frontend bouwt de route uit `type`, `customer_id` en (bij het maandrapport) `month`.
    type: LinkType
    customer_id: str | None = None
    month: str | None = None


class Signal(BaseModel):
    # Stabiel: "{kind}:{customer_id}", of "{kind}:bureau:{koppeling}" voor een bureaubreed signaal.
    id: str
    kind: SignalKind
    severity: SignalSeverity
    customer_id: str | None = None
    customer_name: str | None = None
    text: str
    link: SignalLink


class Kpis(BaseModel):
    customers: int
    customers_attention: int
    open_tasks: int
    open_tasks_high: int


class CustomerRow(BaseModel):
    id: str
    name: str
    # "missing" = er is nog geen momentopname.
    rank_state: RankState
    keywords: int | None = None
    top10: int | None = None
    top10_delta: int | None = None
    open_tasks: int
    signal_count: int


class OverviewResponse(BaseModel):
    generated_at: datetime
    # ISO-week in Europe/Amsterdam.
    week: int
    # Oudste `fetched_at` van de momentopnames met state ok; null als er geen is.
    rankings_fetched_at: datetime | None = None
    kpis: Kpis
    signals: list[Signal]
    customers: list[CustomerRow]
