"""Paging for the long lists: ?limit=&offset=, the total in the X-Total-Count header. Without `limit` a list is returned whole, as before."""
from typing import List, Optional

from fastapi import Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

MAX_PAGE = 500


def limit_q(limit: Optional[int] = Query(None, ge=0, le=MAX_PAGE)) -> Optional[int]:
    return limit


def offset_q(offset: int = Query(0, ge=0)) -> int:
    return offset


def like(text: str) -> str:
    """A search text for ilike(..., escape="\\"): % and _ typed by a person mean themselves."""
    return "%" + text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def total_header(response: Response, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)


def page_sql(db: Session, response: Response, stmt, limit: Optional[int], offset: int) -> List:
    """The rows of an ordered `select(Model)`: one page, and the number of rows in all."""
    total_header(response, db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return db.scalars(stmt).all()


def page_rows(rows: List[dict], q: Optional[str], limit: Optional[int], offset: int):
    """(one page, how many in all) of a table built in memory, optionally narrowed to the rows whose name, username or e-mail contains q."""
    if q and q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in f"{r['name'] or ''} {r['username'] or ''} {r['email'] or ''}".lower()]
    return (rows if limit is None else rows[offset:offset + limit]), len(rows)


def page_list(response: Response, items: List, limit: Optional[int], offset: int) -> List:
    """The same for a list that was filtered in Python."""
    total_header(response, len(items))
    return items if limit is None else items[offset:offset + limit]
