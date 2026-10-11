"""Field helpers for the Nautobot hardware seed job."""
from __future__ import annotations

import re

# Matches a month-year cell ("Oct 2026") or an exact ISO date ("2026-10-04").
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_YEAR_RE = re.compile(r"^([A-Za-z]{3,})\s+(\d{4})$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The first dollar amount in a free-text Price cell ("$45 ea" -> "45"); any
# trailing qualifier ("ea", "lot", ...) describes the unit, not the amount.
_PRICE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{1,2})?)")


def _purchase_date(raw: str) -> str | None:
    """Parse the ledger's free-text Purchased cell into an ISO date string.

    Accepts a month-year ("Oct 2026", resolved to the 1st) or an exact
    "2026-10-04". Anything else (blank, "—", unrecognised) returns ``None`` so
    the caller omits the field rather than writing a wrong date.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if _ISO_DATE_RE.match(text):
        return text
    match = _MONTH_YEAR_RE.match(text)
    if not match:
        return None
    month = _MONTH_ABBR.get(match.group(1)[:3].lower())
    if not month:
        return None
    return f"{match.group(2)}-{month:02d}-01"


def _purchase_price_cents(raw: str) -> int | None:
    """Parse a free-text Price cell ("$15,899.99", "$45 ea") into integer cents.

    Returns ``None`` for blank/placeholder text so the caller omits rather
    than records a $0.00 purchase.
    """
    text = (raw or "").strip()
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", "")) * 100)
    except ValueError:
        return None


def _is_drive(row) -> bool:
    """Whether the component category is managed by the live drive gatherer."""
    return str(row.get("category") or "").strip().lower().startswith(("ssd", "hdd", "nvme"))


def _module_asset_tags(hw_id: str, quantity) -> list[str]:
    """Return the row's stable Module asset tags for its unit quantity."""
    try:
        count = int(quantity or 1)
    except (TypeError, ValueError):
        count = 1
    if count > 1:
        return [f"{hw_id}#{index}" for index in range(1, count + 1)]
    return [hw_id]


def _row_modules(Module, hw_id: str) -> dict[str, object]:
    """Find only Modules owned by this row, including its numeric unit tags."""
    owned = re.compile(rf"{re.escape(hw_id)}(#\d+)?")
    return {
        str(module.asset_tag): module
        for module in Module.objects.filter(asset_tag__startswith=hw_id)
        if owned.fullmatch(str(module.asset_tag))
    }


def _procurement_data(row) -> dict:
    """The row's non-empty procurement CustomField values, keyed as they are stored.

    Omits a key entirely when the source has nothing for it — exactly like
    ``_serial`` below: a blank seed field must never erase a value already
    recorded in Nautobot (e.g. one entered after a physical audit found the
    real purchase date).
    """
    data = {}
    purchase_date = _purchase_date(row.get("purchased", ""))
    if purchase_date:
        data["purchase_date"] = purchase_date
    price_cents = _purchase_price_cents(row.get("price", ""))
    if price_cents is not None:
        data["purchase_price_cents"] = price_cents
    vendor = str(row.get("vendor") or "").strip()
    if vendor:
        data["vendor"] = vendor
    receipt_ref = str(row.get("receipt_ref") or "").strip()
    if receipt_ref:
        data["receipt_ref"] = receipt_ref
    return data


def _apply_procurement_data(obj, row) -> None:
    """Merge this row's procurement values into ``obj.custom_field_data``.

    A merge, never a replace: only the keys present in ``data`` are touched,
    so a CustomField this job does not own is left alone, and saves only
    happen when something actually changed.
    """
    data = _procurement_data(row)
    if not data:
        return
    changed = False
    for key, value in data.items():
        if obj.custom_field_data.get(key) != value:
            obj.custom_field_data[key] = value
            changed = True
    if changed:
        obj.validated_save()

# Nautobot's `serial` is a plain CharField, so any of None, "", "  " and the
# placeholder dashes people type into markdown tables all have to collapse to
# "no serial known" — otherwise a literal "—" becomes a device's identity and
# looks exactly like a real one forever after.
_SERIAL_PLACEHOLDERS = {
    "",
    "-",
    "--",
    "—",
    "n/a",
    "na",
    "none",
    "unknown",
    "tbd",
    "?",
    # DMI defaults from boards whose serial was never programmed. These are the
    # dangerous ones: unlike "n/a" they LOOK like data, they are identical
    # across every board of that make, and dmidecode returns them confidently.
    # Verified live on this estate's two workstation-class nodes, which report
    # exactly these while the rack servers return real service tags.
    "system serial number",
    "default string",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "not specified",
    "not applicable",
    "0123456789",
    "00000000",
}


def _serial(row) -> str:
    """The row's serial, or "" when it carries nothing usable."""
    value = str(row.get("serial") or "").strip()
    return "" if value.lower() in _SERIAL_PLACEHOLDERS else value
