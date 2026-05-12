"""Parse the BNI Malaysia member list PDF and load into the prospects table."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pdfplumber

from outreach.db.connection import get_connection

# Columns expected in the BNI PDF, in order. Used to map extracted rows.
_COLUMNS: tuple[str, ...] = (
    "name",
    "company",
    "profession",
    "area",
    "city",
    "bni_chapter",
    "phone",
    "category",
)


def parse_bni_pdf(pdf_path: Path) -> list[dict]:
    """Parse the BNI member PDF into a list of prospect dicts.

    Each dict has keys matching the prospects schema columns:
    name, company, profession, area, city, bni_chapter, phone, category.

    Header rows, empty rows, and rows missing name or company are dropped.
    Duplicates by (name, company) are deduplicated, keeping the first.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"BNI PDF not found: {pdf_path}")

    rows: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for raw in table:
                    cells = [(c or "").strip() for c in raw]
                    if not cells or all(not c for c in cells):
                        continue
                    # Skip the header row that repeats across pages.
                    if cells[0].lower() == "name":
                        continue
                    # Pad/truncate to the expected column count.
                    cells = (cells + [""] * len(_COLUMNS))[: len(_COLUMNS)]
                    row = dict(zip(_COLUMNS, cells))
                    if not row["name"] or not row["company"]:
                        continue
                    rows.append(row)
    return _deduplicate(rows)


def _deduplicate(rows: list[dict]) -> list[dict]:
    """Drop duplicate (name, company) pairs, keeping the first occurrence."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for r in rows:
        key = (r["name"].lower(), r["company"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def load_into_db(
    prospects: list[dict],
    conn: sqlite3.Connection | None = None,
) -> tuple[int, int]:
    """Insert prospects into the database.

    Returns ``(attempted, inserted)``. Skipped rows = attempted - inserted
    (caused by the UNIQUE(source, source_id) constraint when re-running).
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    assert conn is not None  # for type checkers
    try:
        inserted = 0
        for index, p in enumerate(prospects):
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO prospects (
                    source, source_id, name, company, profession,
                    area, city, bni_chapter, phone, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bni",
                    f"bni:{index}:{p['name'].lower()}",
                    p["name"],
                    p["company"],
                    p["profession"],
                    p["area"],
                    p["city"],
                    p["bni_chapter"],
                    p["phone"],
                    p["category"],
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
        if own_conn:
            conn.commit()
        return len(prospects), inserted
    finally:
        if own_conn:
            conn.close()


def parse_and_load(pdf_path: Path) -> None:
    """Parse the PDF and load into the DB. Print a one-screen summary."""
    print(f"📄 Parsing {pdf_path}...")
    prospects = parse_bni_pdf(pdf_path)
    print(f"   Parsed {len(prospects)} unique prospects")
    if not prospects:
        print(
            "⚠️  No prospects extracted. The PDF may use a different layout"
            " than expected. Save it as a copy from the original Excel"
            " export and try again."
        )
        return
    print("💾 Loading into database...")
    attempted, inserted = load_into_db(prospects)
    skipped = attempted - inserted
    print(f"✅ Inserted {inserted} new prospects ({skipped} already in DB)")
