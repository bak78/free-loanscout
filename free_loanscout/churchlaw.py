"""Churches and law firms are never leads (the boss's rule, October 2026).

What it does: church_or_law() looks at a business's names (legal name and
"doing business as" name) and its email and website domains, and says whether
it is a church or a law firm, with the words that gave it away. leads.py
turns a yes into a disqualifying hit, so the business goes to the left-out
file before any website is read. The website wording ("join us for worship",
"attorneys at law") is caught separately, by the church and law_firm signals
in signals.yaml.

How it works: three regular expressions.

- CHURCH_NAME matches church, parish, synagogue, mosque, diocese, ministry
  and the like — but "church" and its kin count only when they name the
  organization: at the end of the name (allowing a trailing Inc or LLC), or
  before "of" (Grace Baptist Church Inc, Church of God). A business named
  after one passes (Church Organs Inc, Cathedral Art Metal Co, or a
  contractor whose owner is called Church).
- LAW_NAME matches "law firm", "law offices", attorney, lawyer, Esq, "Law
  LLC" and a name ending in "Law" (Smith Law).
- LAW_DOMAIN matches domains ending in law, lawfirm, attorneys and so on
  (smithlaw.com, jonesattorneys.com).

Names are checked before domains. Whole words only, so "Temple Grading",
"LaChapelle" and "delaware.com" pass.
"""

from __future__ import annotations

import re

CHURCH_NAME = re.compile(
    r"\bministr(?:y|ies)\b|\b(?:arch)?diocese\b|"
    r"\b(?:church(?:es)?|parish|synagogue|mosque|masjid|cathedral|tabernacle|congregation)\b"
    r"(?=\s+of\b|[\s,.]*(?:(?:inc|incorporated|corp|corporation|llc)\b\.?)?[\s,.]*$)", re.I)
LAW_NAME = re.compile(
    r"\blaw (?:firm|offices?|group|center|partners)\b|\b(?:attorneys?|lawyers?)\b|\besq\b\.?|"
    r"\blaw(?:,)? (?:llc|pllc|llp|pc|p\.c\.|pa|p\.a\.)\b|\b\w+ law\s*$", re.I)
# smithlaw.com, smithlawfirm.com, jonesattorneys.com — but not delaware.com.
LAW_DOMAIN = re.compile(r"(?:law|lawfirm|lawoffices?|lawgroup|lawyers?|attorneys?|esq)\.[a-z]+$", re.I)


def church_or_law(names=(), domains=()) -> tuple[str, str]:
    """('church' or 'law_firm', the evidence), or ('', '') for anyone else."""
    names = [n.strip() for n in names if n and n.strip()]
    for signal_id, by_name in (("church", CHURCH_NAME), ("law_firm", LAW_NAME)):
        for name in names:
            found = by_name.search(name)
            if found:
                return signal_id, f"name: {name} ({found.group(0).strip()})"
    for domain in sorted(d for d in domains if d):
        if LAW_DOMAIN.search(domain):
            return "law_firm", f"domain: {domain}"
    return "", ""
