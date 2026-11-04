"""Decide which tickets belong on the operational sheet.

The sheet is for work somebody must act on. Automated alerts and marketing
spam are not work, so they are kept off the Tickets sheet and listed on a
separate ``Noise`` sheet with the reason, so a wrong call is visible and
reversible rather than silent.

Principles:

* **Conservative.** A real ticket on the Noise sheet is worse than a spam
  ticket on the board. Only strong evidence moves a ticket to noise.
* **A store code is proof of work.** If a store can be identified the ticket
  is operational, whatever else the text says.
* Every verdict carries a reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .extract import OTHER, Extracted, email_domain

_SPAM_SUBJECT = re.compile(
    r"(\bunsubscribe\b|\bnewsletter\b|\bwebinar\b|\bfree\s+trial\b|\blimited[\s-]time\b|\bact\s+now\b|"
    r"\bclick\s+here\b|\bbuy\s+now\b|\bspecial\s+offer\b|\bexclusive\s+(?:offer|deal)\b|\bdiscount\b|"
    r"\d+\s?%\s*off\b|\bwinner\b|\blottery\b|\bcrypto\b|\bbitcoin\b|\bseo\b|\bviagra\b|\bpromo(?:tion\w*)?\b|"
    r"\bcongratulations\b|\bearn\s+\$|\bguaranteed\b|\bcheap\b)",
    re.IGNORECASE,
)
# Wording only machines write. With no store code this is noise even if a
# job-type keyword happens to appear ("Delivery Status Notification (Failure)").
_AUTOMATED_STRONG = re.compile(
    r"(\bdo\s+not\s+reply\b|\bdelivery\s+status\s+notification\b|\bout\s+of\s+office\b|\bautomatic\s+reply\b|"
    r"\bauto[\s-]?reply\b|\bundeliverable\b|\bmailer-daemon\b|\bmail\s+delivery\s+(?:failed|subsystem)\b)",
    re.IGNORECASE,
)
# Alert-style wording a human could also write; only believed when nothing else
# says "work" (no store, no job type).
_AUTOMATED_WEAK = re.compile(
    r"(^\s*\[?\s*(?:auto(?:mated)?|automatic|system|monitoring|alert|notification|noreply|no-reply)\b|"
    r"\bheartbeat\b|\bscheduled\s+report\b|\bthreshold\s+(?:exceeded|breach\w*)\b|\bdisk\s+space\b|"
    r"\bcpu\s+usage\b|\buptime\s+report\b)",
    re.IGNORECASE,
)
_AUTOMATED_SENDER = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster|notifications?|alerts?|alarms?[-_.]?bot|"
    r"monitor(?:ing)?|nagios|zabbix|system|automated?|bounce\w*|newsletter|marketing|promo(?:tions?)?|offers?|deals?|"
    r"sales|noc|sensor\w*)([-_.+@].*)?$",
    re.IGNORECASE,
)


def from_trusted_human(local_part: str, from_trusted: bool) -> bool:
    """A trusted-domain sender that is not itself an automated mailbox."""
    return from_trusted and not _AUTOMATED_SENDER.match(local_part)


@dataclass(frozen=True)
class Verdict:
    is_noise: bool
    reason: str = ""


def classify(
    subject: str,
    requester_email: str,
    extracted: Extracted,
    trusted_domains: Iterable[str] = (),
) -> Verdict:
    """Return whether a ticket is noise, and why."""
    if extracted.store_code:
        return Verdict(False)

    subject = subject or ""
    email = (requester_email or "").strip().lower()
    local = email.split("@", 1)[0] if "@" in email else ""
    domain = email_domain(email)
    trusted = {d.strip().lower() for d in trusted_domains if d.strip()}
    from_trusted = bool(domain) and domain in trusted

    if _SPAM_SUBJECT.search(subject) and not from_trusted:
        return Verdict(True, "marketing/spam wording, no store, sender not a trusted domain")
    if _AUTOMATED_SENDER.match(local) and not from_trusted:
        return Verdict(True, f"automated sender '{local}', no store")
    if _AUTOMATED_STRONG.search(subject) and not from_trusted_human(local, from_trusted):
        return Verdict(True, "automated-message wording, no store")
    if _AUTOMATED_WEAK.search(subject) and extracted.job_type == OTHER:
        return Verdict(True, "automated alert wording, no store, no job type")
    if _SPAM_SUBJECT.search(subject) and extracted.job_type == OTHER:
        return Verdict(True, "marketing/spam wording, no store, no job type")
    return Verdict(False)
