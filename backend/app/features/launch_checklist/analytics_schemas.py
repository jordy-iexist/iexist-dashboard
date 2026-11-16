"""Responses van de Analytics-endpoints (livegang). Procenten 0-100; None = niet gemeten."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Number = int | float
SourceState = Literal["ok", "reused", "not_measured", "not_connected", "error"]
MetricUnit = Literal["count", "percent", "score", "ms", "position"]


class MetricDef(BaseModel):
    key: str
    label: str
    group: str
    group_label: str
    unit: MetricUnit
    higher_is_better: bool | None
    phases: list[int]


class CustomerRef(BaseModel):
    id: str
    name: str
    domain: str


class ScanRef(BaseModel):
    scan_id: str
    phase: int
    period: str
    label: str
    date: str


class PointSources(BaseModel):
    ahrefs: SourceState
    search_console: SourceState
    bing: SourceState
    proranktracker: SourceState
    cwv: SourceState


class TrendPoint(ScanRef):
    ruleset: int
    is_primary: bool
    sources: PointSources
    values: dict[str, Number | None]


class RulesetBreak(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    after_scan_id: str
    from_: int = Field(alias="from")
    to: int


class TrendResponse(BaseModel):
    customer: CustomerRef
    metrics: list[MetricDef]
    points: list[TrendPoint]
    breaks: list[RulesetBreak]


class MetricComparison(BaseModel):
    key: str
    label: str
    group: str
    group_label: str
    unit: MetricUnit
    higher_is_better: bool | None
    before: Number | None
    after: Number | None
    delta: Number | None
    pct: float | None


class CompareResponse(BaseModel):
    a: ScanRef
    b: ScanRef
    metrics: list[MetricComparison]
    # Zelfde vorm als de delen van checklist["comparison"] van een fase 4-scan.
    ai: dict[str, Any] | None
    issues: dict[str, Any] | None
    pages: dict[str, Any] | None
    ahrefs: dict[str, Any] | None
    rankings: dict[str, Any] | None
    notes: list[str]


class BenchmarkRow(BaseModel):
    customer: CustomerRef
    scan: ScanRef | None
    values: dict[str, Number | None]


class MetricSummary(BaseModel):
    median: Number | None
    p25: Number | None
    p75: Number | None
    min: Number | None
    max: Number | None
    n: int


class BenchmarkResponse(BaseModel):
    metrics: list[MetricDef]
    rows: list[BenchmarkRow]
    summary: dict[str, MetricSummary]
