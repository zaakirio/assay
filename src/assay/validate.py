"""Business rules over a parsed Invoice. Each rule returns a human-readable
failure string; those strings double as the repair prompt fed back to the
model and as the reviewer-facing explanation in the queue."""

from .normalize import ISO_4217, money_equal, parse_date
from .schema import Invoice

MONEY_TOL = 0.02


def check_rules(inv: Invoice) -> list[str]:
    errors = []

    if not inv.vendor.strip():
        errors.append("vendor is empty")
    if not inv.invoice_number.strip():
        errors.append("invoice_number is empty")

    inv_date = parse_date(inv.invoice_date)
    due = parse_date(inv.due_date)
    if inv.invoice_date and inv_date is None:
        errors.append(f"invoice_date '{inv.invoice_date}' does not parse as a date")
    if inv.due_date and due is None:
        errors.append(f"due_date '{inv.due_date}' does not parse as a date")
    if inv_date and due and due < inv_date:
        errors.append(f"due_date {due} is before invoice_date {inv_date}")
    if inv_date and not (2000 <= inv_date.year <= 2035):
        errors.append(f"invoice_date year {inv_date.year} is implausible")

    if inv.currency is not None and inv.currency.upper() not in ISO_4217:
        errors.append(f"currency '{inv.currency}' is not an ISO 4217 code")

    if inv.total <= 0:
        errors.append(f"total {inv.total} is not positive")

    if inv.line_items:
        items_sum = round(sum(it.amount for it in inv.line_items), 2)
        base = inv.subtotal if inv.subtotal is not None else None
        if base is not None and not money_equal(items_sum, base, MONEY_TOL):
            errors.append(
                f"line item amounts sum to {items_sum} but subtotal is {base}"
            )
        expected_total = round((inv.subtotal if inv.subtotal is not None else items_sum)
                               + (inv.tax or 0.0), 2)
        if not money_equal(expected_total, inv.total, MONEY_TOL):
            errors.append(
                f"subtotal {inv.subtotal if inv.subtotal is not None else items_sum} "
                f"+ tax {inv.tax or 0} = {expected_total}, but total is {inv.total}"
            )
        for i, it in enumerate(inv.line_items):
            if it.quantity > 0 and it.unit_price > 0 and not money_equal(
                round(it.quantity * it.unit_price, 2), it.amount, MONEY_TOL
            ):
                errors.append(
                    f"line {i + 1} '{it.description[:30]}': "
                    f"{it.quantity:g} x {it.unit_price:g} != {it.amount:g}"
                )
    else:
        errors.append("no line items extracted")

    return errors
