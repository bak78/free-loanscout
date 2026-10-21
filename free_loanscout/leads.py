"""Turn one SBA business into a scored lead, for free.

SBA facts (how long it's been in business, whether the email is the contact's
own, certifications) become signal hits of their own, scored by the same
engine as website text. Every point of a score is traceable to evidence: a
row can say "fit 48 — its website acmehomecare.com is its own".

The SBA already gives the contact's name and email, so no email finder is
needed. Instead of a paid Google lookup, the business's own website is read:
the one on its SBA record, or else the site on its email's domain. A website
that loads on the email's domain shows the business is real and running, and
its pages carry the growth and warning signs (hiring, a nonprofit or lender
notice...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .config import Rules
from .contacts import is_role_address
from .crawl import SiteCrawl, crawl_site, is_crawlable, registered_domain
from .emailcheck import FREE_MAIL, domain_of
from .fetch import PoliteFetcher
from .sba import Business, SbaRules
from .score import Score, score_site
from .signals import SignalHit, match_site

SBA_SOURCE = "SBA Small Business Search"
PUBLIC_TLDS = ("gov", "edu", "mil")

# What the website check found, as the website_check column says it.
SITE_OWN = "loads; same domain as the email"
SITE_FRANCHISE = "franchise brand page"
SITE_OTHER = "loads; different domain from the email"
SITE_DEAD = "didn't load"
SITE_NONE = "no website"
SITE_NOT_CHECKED = "not checked (preview)"


@dataclass(frozen=True)
class Lead:
    business: Business
    website: str
    crawl: SiteCrawl | None
    score: Score
    email_is_contacts_own: bool = False
    website_check: str = SITE_NOT_CHECKED

    @property
    def confirmed_by_website(self) -> bool:
        """Its own website loads (or is a franchise brand's page for it)."""
        return self.website_check in (SITE_OWN, SITE_FRANCHISE)


def _hit(signal_id: str, weight: float, snippet: str, source: str, category: str = "fit") -> SignalHit:
    return SignalHit(signal_id=signal_id, category=category, weight=float(weight),
                     snippet=snippet, source_url=source, page_type="registry")


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def email_belongs_to(email: str, first: str, last: str) -> bool:
    """True when the address's mailbox carries the contact's name:
    jane.doe@, jdoe@, doej@, jane@ — but never info@ or office@."""
    if not email or is_role_address(email):
        return False
    local = _letters(email.partition("@")[0])
    first, last = _letters(first), _letters(last)
    # A short surname must sit at an end, or "Lee" would match fleet@.
    if len(last) >= 4 and last in local:
        return True
    if len(last) == 3 and (local.startswith(last) or local.endswith(last)):
        return True
    return len(first) >= 3 and (local.startswith(first) or (len(local) >= 3 and first.startswith(local)))


def own_domain(b: Business) -> str:
    """The business's own email domain, or '' for a gmail-style address."""
    domain = domain_of(b.email)
    return "" if domain in FREE_MAIL else domain


def websites_to_try(b: Business) -> list[str]:
    """The SBA record's website, then the email's own domain when that's
    different — a business with jane@acmehomecare.com usually has
    acmehomecare.com, even when it left the website box blank."""
    sites = [b.website] if b.website else []
    own = own_domain(b)
    if own and own not in {registered_domain(s) for s in sites}:
        sites.append(f"https://{own}")
    return sites


def sba_hits(b: Business, rules: SbaRules, today: date | None = None) -> list[SignalHit]:
    """What the SBA record says about this business."""
    w = rules.weights
    hits = [_hit("sba_registered", w.get("sba_registered", 8),
                 f"{b.field} (NAICS {b.naics}); contact {b.contact_full}", SBA_SOURCE)]
    years = b.years_in_business(today)
    if years >= int(w.get("established_years", 3)):
        hits.append(_hit("established", w.get("established", 10),
                         f"In business since {b.year_established} ({years} years)", SBA_SOURCE))
    if email_belongs_to(b.email, b.contact_first, b.contact_last):
        hits.append(_hit("contacts_own_email", w.get("contacts_own_email", 8),
                         f"{b.email} is {b.contact_first} {b.contact_last}'s own", SBA_SOURCE))
    if own_domain(b):
        hits.append(_hit("company_domain", w.get("company_domain", 4),
                         f"Email on the business's own domain ({own_domain(b)})", SBA_SOURCE))
    if b.certifications:
        hits.append(_hit("sba_certified", w.get("sba_certified", 6),
                         f"SBA certified: {', '.join(b.certifications)}", SBA_SOURCE))
    return hits


def disqualify_hits(b: Business, website: str, rules: SbaRules) -> list[SignalHit]:
    """Reasons this isn't a small-business borrower, known from the SBA
    record, the email, or the website."""
    hits = []
    if b.nonprofit:
        hits.append(_hit("nonprofit", 0, "Registered with the SBA as a nonprofit organization",
                         SBA_SOURCE, "disqualify"))
    if domain_of(b.email).rpartition(".")[2] in PUBLIC_TLDS:
        hits.append(_hit("public_body", 0, f"{b.email} is a government or school address",
                         SBA_SOURCE, "disqualify"))
    domains = {domain_of(b.email), registered_domain(b.website) if b.website else "",
               registered_domain(website) if website else ""}
    chain = sorted(d for d in domains if d and d in rules.national_chains)
    if chain:
        hits.append(_hit("national_chain", 0, f"{chain[0]} is a national chain (national_chains in sba.yaml)",
                         website or SBA_SOURCE, "disqualify"))
    return hits


def is_llc(b: Business) -> bool:
    """An LLC is almost never a nonprofit, so its website's wording alone
    (an owner's bio: "worked at a large nonprofit") can't make it one."""
    return re.search(r"\bl\.?\s?l\.?\s?c\b", f"{b.legal_name} {b.dba}".lower()) is not None


def website_check(b: Business, website: str, crawl: SiteCrawl | None, rules: SbaRules) -> str:
    """What reading the website showed. A franchise brand's page (a Home
    Instead office) counts as the owner's own even when it doesn't load:
    brand sites often turn programs away."""
    domain = registered_domain(website) if website else ""
    if not domain:
        return SITE_NONE
    if domain in rules.franchise_domains:
        return SITE_FRANCHISE
    if crawl is None or not crawl.pages:
        return SITE_DEAD
    return SITE_OWN if domain == own_domain(b) else SITE_OTHER


def build_lead(
    b: Business,
    fetcher: PoliteFetcher | None,
    rules: Rules,
    sba_rules: SbaRules,
    max_pages: int,
    today: date | None = None,
) -> Lead:
    """Read the business's website and score it. Everything here is free.

    Pass fetcher=None for a quick preview: SBA facts only, no website read.
    """
    website, crawl, check = b.website, None, SITE_NOT_CHECKED
    if fetcher is not None:
        candidates = [s for s in websites_to_try(b) if is_crawlable(s, rules)]
        website, check = (candidates[0] if candidates else b.website), SITE_NONE
        for site in candidates:
            attempt = crawl_site(site, fetcher, rules, max_pages)
            found = website_check(b, site, attempt, sba_rules)
            # The first site is kept unless a later one loads.
            if found != SITE_DEAD or crawl is None:
                website, crawl, check = site, attempt, found
            if found != SITE_DEAD:
                break

    site_hits = match_site(crawl.pages, rules) if crawl is not None and crawl.pages else []
    if is_llc(b):
        site_hits = [h for h in site_hits if h.signal_id != "nonprofit"]
    hits = sba_hits(b, sba_rules, today) + disqualify_hits(b, website, sba_rules) + site_hits
    w = sba_rules.weights
    if check in (SITE_OWN, SITE_FRANCHISE):
        hits.append(_hit("own_website", w.get("own_website", 10),
                         f"Its website {registered_domain(website)} is its own ({check})", website))
    elif check == SITE_OTHER:
        hits.append(_hit("website_loads", w.get("website_loads", 4),
                         f"Its website {registered_domain(website)} loads", website))
    return Lead(b, website, crawl, score_site(hits, rules),
                email_is_contacts_own=email_belongs_to(b.email, b.contact_first, b.contact_last),
                website_check=check)
