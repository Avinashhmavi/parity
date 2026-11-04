"""Pull store code, store name and job type out of messy ticket text.

The store and job type are not fields; they live in conventions:

* subjects like ``PM AT OMNIMART TARVENO (K7Q2XR)`` or
  ``INSTALLATION AT OMNIMART VESHOLM``
* requester emails like ``store.k7q2xr@omnimart.example``

These are heuristics. Each rule is listed here so nothing is unstated magic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

MAINTENANCE = "Maintenance"
INSTALLATION = "Installation"
SERVICE_CALL = "Service Call"
OTHER = "Other"

_CODE = r"[A-Za-z0-9]{6}"
# 1. A 6-char token in parentheses at the end of the subject: "(K7Q2XR)".
_PAREN_CODE = re.compile(rf"\(\s*({_CODE})\s*\)")
# 2. The requester email: store.k7q2xr@ / store-k7q2xr@ / store_k7q2xr@.
_EMAIL_CODE = re.compile(rf"^store[._\-]({_CODE})@", re.IGNORECASE)
# 3. A bare token in the subject that mixes letters and digits (K7Q2XR). A
#    plain 6-letter word such as CAMERA must never match, hence the lookaheads.
_BARE_CODE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])([A-Z0-9]{6})\b")

# Subjects use hyphen, en dash (\u2013) and em dash (\u2014) as separators.
_STORE_NAME = re.compile(
    r"\bOMNIMART\s+(?P<name>[A-Z][A-Z0-9 .'&\-]*?)\s*(?:\(|[-\u2013\u2014:|,]|$)",
    re.IGNORECASE,
)

# Order matters: the first group that matches wins, mirroring the brief
# (PM/AMC are maintenance even when the subject also mentions a fault).
_JOB_RULES = (
    (MAINTENANCE, re.compile(r"\b(PM|AMC|PREVENTIVE|MAINTENANCE|MAINTAINANCE)\b", re.I)),
    (INSTALLATION, re.compile(r"\b(INSTALL\w*|COMMISSION\w*|SET[\s\-]?UP|NEW\s+(?:CAMERA|CCTV|ALARM|SYSTEM))\b", re.I)),
    (
        SERVICE_CALL,
        re.compile(
            r"(NOT\s+(?:WORKING|RECORDING|FUNCTIONING|POWERING|DISPLAYING)|\b(?:FAULT\w*|COMPLAINT\w*|BROKEN|OFFLINE|DOWN|"
            r"REPAIR\w*|DEFECT\w*|MALFUNCTION\w*|FAIL\w*|ISSUE\w*|NO\s+(?:SIGNAL|VIDEO|DISPLAY|POWER)|DAMAGE\w*)\b)",
            re.I,
        ),
    ),
)


@dataclass(frozen=True)
class Extracted:
    store_code: str
    store_name: str
    job_type: str
    store_code_source: str  # "subject" | "email" | "subject-bare" | ""


def store_code(subject: str, requester_email: str = "") -> tuple[str, str]:
    """Return ``(code, source)``; code is upper-case or empty."""
    subject = subject or ""
    email_code = ""
    match = _EMAIL_CODE.match((requester_email or "").strip())
    if match:
        email_code = match.group(1).upper()

    for m in _PAREN_CODE.finditer(subject):
        code = m.group(1).upper()
        # "(ALARMS)" is a word, not a store. All-letter codes are only
        # believed when the requester email agrees.
        if any(c.isdigit() for c in code) or code == email_code:
            return code, "subject"

    if email_code:
        return email_code, "email"

    bare = _BARE_CODE.search((subject or "").upper())
    if bare:
        return bare.group(1), "subject-bare"
    return "", ""


def store_name(subject: str) -> str:
    match = _STORE_NAME.search(subject or "")
    if not match:
        return ""
    name = " ".join(match.group("name").split())
    return name.title()


def job_type(subject: str) -> str:
    text = subject or ""
    for label, pattern in _JOB_RULES:
        if pattern.search(text):
            return label
    return OTHER


def extract(subject: str, requester_email: str = "") -> Extracted:
    code, source = store_code(subject, requester_email)
    return Extracted(code, store_name(subject), job_type(subject), source)


def email_domain(email: Optional[str]) -> str:
    email = (email or "").strip().lower()
    return email.rsplit("@", 1)[1] if "@" in email else ""
