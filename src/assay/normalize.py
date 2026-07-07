"""Shared normalizers used by both validation and the eval metrics, so the
pipeline and the scorer cannot disagree about what 'the same date' means."""

import re
from datetime import date, datetime

ISO_4217 = {
    "AED", "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP",
    "HKD", "HUF", "IDR", "ILS", "INR", "JPY", "KRW", "MXN", "MYR", "NOK",
    "NZD", "PHP", "PLN", "RON", "SAR", "SEK", "SGD", "THB", "TRY", "TWD",
    "USD", "ZAR",
}

_DATE_PATTERNS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d",
    "%d %b, %Y", "%m-%d-%Y",
    # Month-name variants seen in SROIE receipt ground truth ("22 MAR 18",
    # "27/MAR/2018", "28-FEB-2018").
    "%d %b %y", "%d/%b/%Y", "%d/%b/%y", "%d-%b-%Y", "%d-%b-%y",
]


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    v = value.strip()
    for pat in _DATE_PATTERNS:
        try:
            return datetime.strptime(v, pat).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2})$", v)
    if m:
        d, mth, yr = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        try:
            return date(yr, mth, d)
        except ValueError:
            return None
    return None


def norm_text(value: str | None) -> str:
    if value is None:
        return ""
    v = re.sub(r"\s+", " ", value).strip().casefold()
    return re.sub(r"[.,]+$", "", v)


def norm_invoice_number(value: str | None) -> str:
    if value is None:
        return ""
    # Separator characters vary between print layouts and model output
    # ("INV-00123" vs "INV 00123"); only the alphanumerics identify the invoice.
    return re.sub(r"[\W_]+", "", value).casefold()


def money_equal(a: float | None, b: float | None, tol: float = 0.01) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol
