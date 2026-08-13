import re
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.dependencies import require_user_id, utc_now_iso
from app.db.models import (
    Blog,
    CsvRow,
    CustomerSheetCell,
    CustomerSheetColumn,
    CustomerWebsite,
    Job,
)
from app.db.session import get_db
from app.features.customers.schemas import (
    CustomerSheetCellItem,
    CustomerSheetCellUpsertRequest,
    CustomerSheetColumnCreateRequest,
    CustomerSheetColumnItem,
    CustomerSheetColumnUpdateRequest,
    CustomerSheetResponse,
    CustomerSheetRowItem,
)

router = APIRouter(tags=["customer-sheet"])

_TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _extract_markdown_title(content: str, row_data: dict[str, Any]) -> str:
    match = _TITLE_PATTERN.search(content or "")
    if match and match.group(1).strip():
        return match.group(1).strip()
    klant = str(row_data.get("klant", "") or "").strip()
    if klant:
        return klant
    return "Titel ontbreekt"


def _blog_row_data_map(db: Session, blogs: list[Blog]) -> dict[str, dict[str, Any]]:
    """Batch-fetch CsvRow.data for a list of blogs via their generation job.

    Mirrors what `_extract_blog_context` in blogs/router.py does per-blog, but
    in two IN-queries instead of an N+1 loop — a customer sheet can list every
    blog for that customer at once.
    """
    job_ids = [blog.job_id for blog in blogs if blog.job_id]
    if not job_ids:
        return {}
    jobs = db.query(Job.id, Job.row_id).filter(Job.id.in_(job_ids)).all()
    job_row_map = {str(job_id): row_id for job_id, row_id in jobs}

    row_ids = [row_id for row_id in job_row_map.values() if row_id]
    row_data_map: dict[str, Any] = {}
    if row_ids:
        rows = db.query(CsvRow.id, CsvRow.data).filter(CsvRow.id.in_(row_ids)).all()
        row_data_map = {str(row_id): data for row_id, data in rows}

    result: dict[str, dict[str, Any]] = {}
    for blog in blogs:
        row_id = job_row_map.get(str(blog.job_id)) if blog.job_id else None
        data = row_data_map.get(str(row_id)) if row_id else None
        result[str(blog.id)] = data if isinstance(data, dict) else {}
    return result


def _require_customer(db: Session, customer_id: str) -> CustomerWebsite:
    website = (
        db.query(CustomerWebsite).filter(CustomerWebsite.id == customer_id).first()
    )
    if not website:
        raise HTTPException(status_code=404, detail="Klant niet gevonden.")
    return website


def _require_column(
    db: Session, customer_id: str, column_id: str
) -> CustomerSheetColumn:
    column = (
        db.query(CustomerSheetColumn)
        .filter(
            CustomerSheetColumn.id == column_id,
            CustomerSheetColumn.customer_website_id == customer_id,
        )
        .first()
    )
    if not column:
        raise HTTPException(status_code=404, detail="Kolom niet gevonden.")
    return column


@router.get(
    "/api/customers/{customer_id}/sheet", response_model=CustomerSheetResponse
)
async def get_customer_sheet(
    customer_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _require_customer(db, customer_id)

    columns = (
        db.query(CustomerSheetColumn)
        .filter(CustomerSheetColumn.customer_website_id == customer_id)
        .order_by(CustomerSheetColumn.position.asc())
        .all()
    )

    blogs: list[Blog] = (
        db.query(Blog)
        .filter(
            Blog.customer_website_id == customer_id,
            or_(Blog.created_by == user_id, Blog.is_public.is_(True)),
        )
        .order_by(Blog.created_at.desc())
        .all()  # type: ignore[assignment]
    )
    blog_ids = [str(blog.id) for blog in blogs]
    row_data_map = _blog_row_data_map(db, blogs)

    cells_by_blog: dict[str, dict[str, str | None]] = defaultdict(dict)
    if blog_ids:
        cell_rows = (
            db.query(CustomerSheetCell)
            .join(
                CustomerSheetColumn,
                CustomerSheetCell.column_id == CustomerSheetColumn.id,
            )
            .filter(
                CustomerSheetColumn.customer_website_id == customer_id,
                CustomerSheetCell.blog_id.in_(blog_ids),
            )
            .all()
        )
        for cell in cell_rows:
            cells_by_blog[str(cell.blog_id)][str(cell.column_id)] = cell.value

    rows = []
    for blog in blogs:
        row_data = row_data_map.get(str(blog.id), {})
        rows.append(
            CustomerSheetRowItem(
                id=str(blog.id),
                title=_extract_markdown_title(blog.content, row_data),
                created_at=blog.created_at,
                published_at=blog.published_at,
                is_owner=blog.created_by == user_id,
                words=str(row_data.get("woorden") or "").strip() or None,
                anchor_1=str(row_data.get("anker_1") or "").strip() or None,
                anchor_1_url=str(row_data.get("anker_1_url") or "").strip() or None,
                anchor_2=str(row_data.get("anker_2") or "").strip() or None,
                anchor_2_url=str(row_data.get("anker_2_url") or "").strip() or None,
                placement_url=blog.placement_url,
                cells=cells_by_blog.get(str(blog.id), {}),
            )
        )

    return CustomerSheetResponse(
        columns=[
            CustomerSheetColumnItem(id=str(c.id), label=c.label, position=c.position)
            for c in columns
        ],
        rows=rows,
    )


@router.post(
    "/api/customers/{customer_id}/sheet/columns",
    response_model=CustomerSheetColumnItem,
)
async def create_sheet_column(
    customer_id: str,
    payload: CustomerSheetColumnCreateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _require_customer(db, customer_id)

    label = str(payload.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Kolomnaam is verplicht.")

    max_position = (
        db.query(func.max(CustomerSheetColumn.position))
        .filter(CustomerSheetColumn.customer_website_id == customer_id)
        .scalar()
    )
    next_position = (max_position or 0) + 1

    now = utc_now_iso()
    column = CustomerSheetColumn(
        id=str(uuid.uuid4()),
        customer_website_id=customer_id,
        label=label,
        position=next_position,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(column)
    db.commit()
    db.refresh(column)
    return CustomerSheetColumnItem(
        id=str(column.id), label=column.label, position=column.position
    )


@router.patch(
    "/api/customers/{customer_id}/sheet/columns/{column_id}",
    response_model=CustomerSheetColumnItem,
)
async def update_sheet_column(
    customer_id: str,
    column_id: str,
    payload: CustomerSheetColumnUpdateRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _require_customer(db, customer_id)
    _require_column(db, customer_id, column_id)

    updates: dict[str, Any] = {"updated_at": utc_now_iso()}
    if payload.label is not None:
        label = payload.label.strip()
        if not label:
            raise HTTPException(
                status_code=400, detail="Kolomnaam mag niet leeg zijn."
            )
        updates["label"] = label
    if payload.position is not None:
        updates["position"] = payload.position

    if len(updates) == 1:
        raise HTTPException(status_code=400, detail="Geen wijzigingen ontvangen.")

    db.query(CustomerSheetColumn).filter(CustomerSheetColumn.id == column_id).update(
        updates
    )
    db.commit()

    updated = _require_column(db, customer_id, column_id)
    return CustomerSheetColumnItem(
        id=str(updated.id), label=updated.label, position=updated.position
    )


@router.delete("/api/customers/{customer_id}/sheet/columns/{column_id}")
async def delete_sheet_column(
    customer_id: str,
    column_id: str,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _require_customer(db, customer_id)
    _require_column(db, customer_id, column_id)

    db.query(CustomerSheetCell).filter(
        CustomerSheetCell.column_id == column_id
    ).delete()
    db.query(CustomerSheetColumn).filter(
        CustomerSheetColumn.id == column_id
    ).delete()
    db.commit()
    return {"success": True}


@router.put(
    "/api/customers/{customer_id}/sheet/cells", response_model=CustomerSheetCellItem
)
async def upsert_sheet_cell(
    customer_id: str,
    payload: CustomerSheetCellUpsertRequest,
    user_id: str = Depends(require_user_id),
    db: Session = Depends(get_db),
):
    _require_customer(db, customer_id)
    _require_column(db, customer_id, payload.column_id)

    blog = (
        db.query(Blog)
        .filter(
            Blog.id == payload.blog_id,
            Blog.customer_website_id == customer_id,
            or_(Blog.created_by == user_id, Blog.is_public.is_(True)),
        )
        .first()
    )
    if not blog:
        raise HTTPException(status_code=400, detail="Blog niet gevonden.")

    value = payload.value.strip() if isinstance(payload.value, str) else None
    value = value or None

    existing_cell = (
        db.query(CustomerSheetCell)
        .filter(
            CustomerSheetCell.column_id == payload.column_id,
            CustomerSheetCell.blog_id == payload.blog_id,
        )
        .first()
    )
    if existing_cell:
        db.query(CustomerSheetCell).filter(
            CustomerSheetCell.id == existing_cell.id
        ).update({"value": value, "updated_at": utc_now_iso()})
    else:
        now = utc_now_iso()
        db.add(
            CustomerSheetCell(
                id=str(uuid.uuid4()),
                column_id=payload.column_id,
                blog_id=payload.blog_id,
                value=value,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()

    return CustomerSheetCellItem(
        column_id=payload.column_id, blog_id=payload.blog_id, value=value
    )
