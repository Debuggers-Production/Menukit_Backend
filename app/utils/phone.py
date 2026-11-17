"""Phone normalization and formatting utilities."""

import re
from typing import Optional


def normalize_phone_with_country_code(phone: Optional[str], default_country_code: str = "+91") -> str:
    """
    Normalizes a mobile phone number to always include a country code.
    If 10 digits or country code is missing, prepends +91 (or default_country_code).

    Examples:
      '8756453849'     -> '+918756453849'
      '918756453849'   -> '+918756453849'
      '08756453849'    -> '+918756453849'
      '+918756453849'  -> '+918756453849'
      '+14155552671'   -> '+14155552671'
      '98765 43210'    -> '+919876543210'
    """
    if not phone:
        return ""

    trimmed = str(phone).strip()
    if not trimmed:
        return ""

    prefix = default_country_code if default_country_code.startswith("+") else f"+{default_country_code}"

    # If it already starts with '+', keep '+' and strip non-digit characters
    if trimmed.startswith("+"):
        digits = re.sub(r"\D", "", trimmed[1:])
        return f"+{digits}" if digits else trimmed

    digits = re.sub(r"\D", "", trimmed)
    if not digits:
        return trimmed

    # 10 digits -> standard Indian mobile, prepend +91
    if len(digits) == 10:
        return f"{prefix}{digits}"

    # 11 digits starting with 0 -> Indian mobile with trunk prefix 0
    if len(digits) == 11 and digits.startswith("0"):
        return f"{prefix}{digits[1:]}"

    # 12 digits starting with 91 -> Indian mobile with 91 prefix but missing '+'
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"

    # 11+ digits (e.g. international number entered without '+')
    if len(digits) > 10:
        return f"+{digits}"

    # Less than 10 digits (fallback)
    return f"{prefix}{digits}"
