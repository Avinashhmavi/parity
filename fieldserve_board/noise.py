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
    r"\bcongratulations\b|\bearn\s+\$|\bguaranteed\b|\bcheap\b|"
    r"\bpremium\s+listing\b|\boffer\s+inside\b|\bgrow\s+your\s+business\b|\bpotential\s+customers\b|\bearn\s+more\b|"
    r"\bsell\s+smart\b|\blease\s+opportunity\b|\bprime\s+commercial\b|\byour\s+listing\b)",
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


# Machine-generated alert templates carry a device / account / phone number:
# "DVR OFFLINE ALERT - DEVICE 48213", "MISSED CALL ALERT FROM 98xxxxxxxx",
# "MONTHLY USAGE QUOTA LIMIT EXCEEDED FOR ACCOUNT 12345". Alert vocabulary
# alone is not enough (a person can write "alarm alert at store"); the number is
# what marks a template. These senders often reuse a store mailbox, so this
# rule runs even when a store code is present.
_ALERT_VOCAB = re.compile(
    r"(\balert\b|\bquota\s+limit\s+exceeded\b|\busage\s+quota\b|\bthreshold\s+exceeded\b|\bmissed\s+call\b|\blow\s+battery\b)",
    re.IGNORECASE,
)
_MACHINE_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d{2,}\b|#\s*\d+")
# A bulk-mail sender is recognisable by its domain: promomail.*, newsletter.*, ...
_MARKETING_DOMAIN = re.compile(r"(promo|marketing|newsletter|bulk|deals|offers|campaign|advert)", re.IGNORECASE)


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
    subject = subject or ""
    email = (requester_email or "").strip().lower()
    local = email.split("@", 1)[0] if "@" in email else ""
    domain = email_domain(email)
    trusted = {d.strip().lower() for d in trusted_domains if d.strip()}
    from_trusted = bool(domain) and domain in trusted

    # These two are decided before the store-code shortcut: bulk mail never
    # becomes work, and alert templates are often sent from a store mailbox.
    if domain and not from_trusted and _MARKETING_DOMAIN.search(domain.split(".")[0]):
        return Verdict(True, f"bulk-mail sender domain '{domain}'")
    if _ALERT_VOCAB.search(subject) and _MACHINE_NUMBER.search(subject):
        return Verdict(True, "automated alert template (alert wording plus a device/account number)")

    if extracted.store_code:
        return Verdict(False)

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
