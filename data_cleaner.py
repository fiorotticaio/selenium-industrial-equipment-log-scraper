"""
data_cleaner.py
----------------
Takes the raw, messy records produced by scraper.py and turns them into a
clean, analysis-ready pandas DataFrame.

Cleaning steps, in order:
    1. Load raw records into a DataFrame.
    2. Normalize `status` into a fixed vocabulary (operational /
       under_maintenance / offline / decommissioned / unknown).
    3. Parse `last_maintenance_raw` / `next_due_raw`, which arrive in at
       least three different date formats, into real datetimes.
    4. Parse the semicolon-delimited `specs_raw` string into separate
       typed columns (power_kw, voltage_v, equipment_type).
    5. Deduplicate on equipment_id, keeping the most recently-seen /
       most-complete record when the same equipment appears on multiple
       pages (a common artifact of paginated legacy systems).
    6. Flag rows with missing critical fields for manual review instead
       of silently dropping them -- curation should be auditable.
"""

from __future__ import annotations

import re
import logging

import pandas as pd

logger = logging.getLogger("tractian_scraper")

STATUS_MAP = {
    "operational": "operational",
    "under_maintenance": "under_maintenance",
    "under maintenance": "under_maintenance",
    "offline": "offline",
    "decommissioned": "decommissioned",
}

POWER_PATTERN = re.compile(r"Power:\s*([\d.]+)\s*kW", re.IGNORECASE)
VOLTAGE_PATTERN = re.compile(r"Voltage:\s*([\d.]+)\s*V", re.IGNORECASE)
TYPE_PATTERN = re.compile(r"Type:\s*([A-Za-z ]+)", re.IGNORECASE)


def load_raw_records(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    logger.info("Loaded %d raw records into DataFrame", len(df))
    return df


def normalize_status(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    normalized = (
        df["status"]
        .fillna("")
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )
    df["status_clean"] = normalized.map(STATUS_MAP).fillna("unknown")
    return df


def _parse_flexible_date(value: str | None) -> pd.Timestamp | None:
    """Parse a date that may be in any of: YYYY-MM-DD, DD/MM/YYYY, or
    'Month D, YYYY'. Returns pd.NaT if it's empty, 'N/A', or unparseable.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT

    value = str(value).strip()
    if not value or value.upper() in {"N/A", "NA", ""}:
        return pd.NaT

    # Try each known legacy format explicitly rather than relying purely
    # on pandas' generic inference, since DD/MM/YYYY vs MM/DD/YYYY is
    # ambiguous without knowing the source format per-column.
    candidate_formats = ["%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y"]
    for fmt in candidate_formats:
        try:
            return pd.to_datetime(value, format=fmt)
        except (ValueError, TypeError):
            continue

    # Last resort: let pandas guess, but flag it in the logs since a
    # silently-wrong guess on ambiguous dates is worse than a null.
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        logger.warning("Could not parse date value: %r", value)
    else:
        logger.warning("Fell back to inferred parsing for date value: %r -> %s", value, parsed)
    return parsed


def normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["last_maintenance_date"] = df["last_maintenance_raw"].apply(_parse_flexible_date)
    df["next_due_date"] = df["next_due_raw"].apply(_parse_flexible_date)
    return df


def parse_specs(df: pd.DataFrame) -> pd.DataFrame:
    """Specs arrive as a free-form 'Power: 50kW; Voltage: 480V; Type: X'
    string with fields sometimes missing entirely, so each field is
    extracted independently rather than with one combined pattern --
    a combined regex would fail the whole match whenever a single field
    (e.g. voltage) is absent.
    """
    df = df.copy()
    specs = df["specs_raw"].fillna("")
    df["power_kw"] = pd.to_numeric(
        specs.str.extract(POWER_PATTERN, expand=False), errors="coerce"
    )
    df["voltage_v"] = pd.to_numeric(
        specs.str.extract(VOLTAGE_PATTERN, expand=False), errors="coerce"
    )
    df["equipment_type"] = specs.str.extract(TYPE_PATTERN, expand=False).str.strip()
    return df


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per equipment_id.

    When the same equipment_id was scraped on more than one page (which
    happens on real portals when records get re-sorted between page
    loads), keep the record with the most non-null fields, and break ties
    by preferring the most recent last_maintenance_date.
    """
    df = df.copy()
    df["_completeness"] = df.notna().sum(axis=1)
    df = df.sort_values(
        by=["_completeness", "last_maintenance_date"], ascending=[False, False]
    )
    before = len(df)
    df = df.drop_duplicates(subset="equipment_id", keep="first")
    df = df.drop(columns="_completeness")
    logger.info("Deduplicated %d raw rows down to %d unique equipment records", before, len(df))
    return df


def flag_incomplete(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    critical_fields = ["equipment_id", "status_clean", "last_maintenance_date"]
    df["needs_review"] = df[critical_fields].isna().any(axis=1)
    flagged = int(df["needs_review"].sum())
    if flagged:
        logger.warning("%d record(s) flagged for manual review (missing critical fields)", flagged)
    return df


def clean_pipeline(raw_records: list[dict]) -> pd.DataFrame:
    """Run the full cleaning pipeline and return the final DataFrame."""
    df = load_raw_records(raw_records)
    if df.empty:
        logger.warning("No records to clean.")
        return df

    df = normalize_status(df)
    df = normalize_dates(df)
    df = parse_specs(df)
    df = deduplicate(df)
    df = flag_incomplete(df)

    final_columns = [
        "equipment_id",
        "status_clean",
        "last_maintenance_date",
        "next_due_date",
        "equipment_type",
        "power_kw",
        "voltage_v",
        "location",
        "needs_review",
        "source_page",
    ]
    df = df[final_columns].rename(columns={"status_clean": "status"})
    df = df.sort_values(by="equipment_id").reset_index(drop=True)
    return df
