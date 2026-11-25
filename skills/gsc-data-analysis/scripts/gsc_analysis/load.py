"""Load Search Console data from the UI export (English or Spanish headers), the API, or an MCP tool result,
and normalize it to: date, query, page, country, device, clicks, impressions, ctr (0-1), position."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ALIASES = {
    "date": {"date", "dates", "fecha", "fechas", "day"},
    "query": {"query", "queries", "top queries", "consulta", "consultas", "consultas principales"},
    "page": {"page", "pages", "top pages", "url", "pagina", "página", "páginas", "paginas", "páginas principales", "paginas principales"},
    "country": {"country", "countries", "país", "pais", "paises", "países"},
    "device": {"device", "devices", "dispositivo", "dispositivos"},
    "clicks": {"clicks", "clics", "click"},
    "impressions": {"impressions", "impresiones"},
    "ctr": {"ctr"},
    "position": {"position", "posición", "posicion", "average position", "posición media", "posicion media"},
}
_LOOKUP = {alias: canon for canon, names in ALIASES.items() for alias in names}
NUMERIC = ["clicks", "impressions", "ctr", "position"]


def _to_number(s: pd.Series, percent: bool = False) -> pd.Series:
    """Parse numbers written as '1234', '12.5%', '12,5%' (Spanish decimal comma) or '1 234'."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    t = s.astype(str).str.strip().str.replace("%", "", regex=False).str.replace(" ", "", regex=False)
    t = t.str.replace(r"\s", "", regex=True)
    # '1.234,5' (thousands dot + decimal comma) -> '1234.5'; '12,5' -> '12.5'
    has_both = t.str.contains(r"\.") & t.str.contains(",")
    t = t.where(~has_both, t.str.replace(".", "", regex=False))
    t = t.str.replace(",", ".", regex=False)
    return pd.to_numeric(t, errors="coerce")


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to canonical names, parse numbers/dates, and make ctr a 0-1 fraction."""
    out = df.copy()
    renames = {}
    for c in out.columns:
        key = re.sub(r"\s+", " ", str(c).strip().lower())
        if key in _LOOKUP:
            renames[c] = _LOOKUP[key]
    out = out.rename(columns=renames)
    out = out.loc[:, ~out.columns.duplicated()]
    ctr_was_percent = False
    if "ctr" in out.columns and not pd.api.types.is_numeric_dtype(out["ctr"]):
        ctr_was_percent = out["ctr"].astype(str).str.contains("%").any()
    for c in NUMERIC:
        if c in out.columns:
            out[c] = _to_number(out[c])
    if "ctr" in out.columns and ctr_was_percent:
        out["ctr"] = out["ctr"] / 100.0
    elif "ctr" in out.columns and out["ctr"].max(skipna=True) > 1.0:
        out["ctr"] = out["ctr"] / 100.0  # numeric but expressed in percent
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for c in ("clicks", "impressions"):
        if c in out.columns:
            out[c] = out[c].fillna(0)
    return out


def load_csv(path: str | Path) -> pd.DataFrame:
    """Read a Search Console CSV (UI export or API dump). Tries UTF-8 (with BOM) then Latin-1."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return normalize(pd.read_csv(path, encoding=enc, sep=None, engine="python"))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path}")


def from_api_rows(rows: list[dict], dimensions: list[str]) -> pd.DataFrame:
    """Rows as returned by the Search Analytics API / gsc-mcp-server ({'keys': [...], 'clicks': ...})."""
    recs = []
    for r in rows:
        rec = dict(zip(dimensions, r.get("keys", [])))
        rec.update({k: r.get(k) for k in NUMERIC})
        recs.append(rec)
    return normalize(pd.DataFrame(recs))


def with_ctr(df: pd.DataFrame) -> pd.DataFrame:
    """Add `ctr_calc` = clicks / impressions (the reliable CTR; the exported one is rounded)."""
    out = df.copy()
    out["ctr_calc"] = (out["clicks"] / out["impressions"]).where(out["impressions"] > 0)
    return out
