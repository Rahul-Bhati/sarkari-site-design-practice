"""Facts we are willing to show, and the WhatsApp forward.

A number or a sentence is kept only when it already appears in the notice
text. The model does not get to invent a vacancy count or a fee.
"""

from __future__ import annotations

_STRING_FIELDS = (
    "post",
    "pay",
    "age",
    "qualification",
    "how_to_apply",
    "benefit",
    "application_link",
    "helpline",
)


def whatsapp_text(
    title: str,
    deadline: str | None,
    vacancies: int | None,
    url: str,
) -> str:
    """The forward a family group already expects. Omit posts when we have no count."""
    lines = [title.strip(), f"Last date: {deadline or 'not listed'}"]
    if vacancies is not None:
        lines.append(f"Posts: {vacancies}")
    lines.append(url)
    return "\n".join(lines)


def number_in_text(number: int, text: str) -> bool:
    forms = {str(number), f"{number:,}", _indian_group(number)}
    return any(form in text for form in forms)


def keep_supported_facts(details: dict, text: str) -> dict:
    """Return only the detail fields the notice text actually contains."""
    source = text or ""
    folded = source.casefold()
    kept: dict = {}

    for key in _STRING_FIELDS:
        value = details.get(key)
        if isinstance(value, str) and value.strip() and value.strip().casefold() in folded:
            kept[key] = value.strip()

    fee = details.get("fee")
    if isinstance(fee, str) and fee.strip() and _fee_supported(fee.strip(), source):
        kept["fee"] = fee.strip()

    dates = details.get("important_dates")
    if isinstance(dates, str) and dates.strip() and dates.strip().casefold() in folded:
        kept["important_dates"] = dates.strip()

    for key in ("vacancies", "emd_amount"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and number_in_text(value, source):
            kept[key] = value

    return kept


def quote_in_text(value: str | None, text: str) -> bool:
    if not value or not value.strip():
        return False
    return value.strip().casefold() in (text or "").casefold()


def _fee_supported(fee: str, text: str) -> bool:
    if fee.casefold() in text.casefold():
        return True
    digits = "".join(ch for ch in fee if ch.isdigit())
    if not digits:
        return False
    return number_in_text(int(digits), text)


def _indian_group(number: int) -> str:
    raw = str(number)
    if len(raw) <= 3:
        return raw
    head, tail = raw[:-3], raw[-3:]
    parts = [tail]
    while head:
        parts.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(parts))
