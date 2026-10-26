"""Incremental CSV output.

Rows are appended and flushed as each business finishes, so a run killed
halfway still leaves a usable file. A sibling seen.txt of SBA business IDs
(UEI) lets a re-run skip businesses already done — which is what lets each
run continue down the ranked list instead of reading the same websites
twice.

How it works:

- COLUMNS is the CSV's layout; build_row() fills it from a Lead — the
  contact, the scores, the SBA facts, the top three pieces of evidence and
  any crawl errors. The phone the business gave the SBA comes first; its
  website's is used only when it gave none.
- CsvWriter appends rows under a lock, so worker threads can share it. With
  each row it also appends the business's ID to <results>.seen.txt and its
  email to <results>.emails.txt. Both files only ever grow (unless a run
  starts over), so deleting the results to start a fresh batch never makes
  a later batch repeat a business or an inbox. mark_done() records a
  business as finished without writing a row (one that was left out).
- Opening an existing CSV from an older version rewrites it with the current
  columns first, so new rows don't land under the wrong headings.
- sort_csv_by_score() rewrites the finished CSV highest score first.
"""

from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import Rules
from .leads import Lead

COLUMNS = [
    # Who to email, and the business.
    "first_name",
    "last_name",
    "email",
    "phone",
    "company_name",
    "industry",
    "industry_group",
    # The weight: 0-100, from SBA facts and the website.
    "score",
    "growth_score",
    "distress_score",
    "fit_score",
    "website_check",
    # More about the contact and the business.
    "email_is_contacts_own",
    "contact_full_name",
    "phone_source",
    "website",
    "legal_name",
    "address",
    "city",
    "state",
    "zip",
    "county",
    "year_established",
    "years_in_business",
    "sba_certifications",
    "naics",
    "uei",
    # Evidence and diagnostics.
    "disqualified",
    "disqualify_reason",
    "top_signals",
    "evidence_1",
    "evidence_2",
    "evidence_3",
    "other_phones",
    "pages_crawled",
    "notes",
    "processed_at",
    "key",
]


def build_row(lead: Lead, rules: Rules) -> dict:
    b, crawl, score = lead.business, lead.crawl, lead.score
    contacts = crawl.contacts if crawl is not None else None

    # The number the business gave the SBA comes first; its website's when it gave none.
    if b.phone:
        phone, phone_source = b.phone, "SBA"
    elif contacts is not None and contacts.phone:
        phone, phone_source = contacts.phone, "website"
    else:
        phone, phone_source = "", ""

    evidence = [h.describe() for h in score.top_hits(3)]
    evidence += [""] * (3 - len(evidence))

    notes = []
    if crawl is not None:
        notes += crawl.errors[:2]

    return {
        "first_name": b.contact_first,
        "last_name": b.contact_last,
        "email": b.email,
        "phone": phone,
        "company_name": b.company_name,
        "industry": b.field,
        "industry_group": b.group,
        "score": score.total,
        "growth_score": score.categories.get("growth", 0.0),
        "distress_score": score.categories.get("distress", 0.0),
        "fit_score": score.categories.get("fit", 0.0),
        "website_check": lead.website_check,
        "email_is_contacts_own": "yes" if lead.email_is_contacts_own else "no (company inbox)",
        "contact_full_name": b.contact_full,
        "phone_source": phone_source,
        "website": lead.website,
        "legal_name": b.legal_name,
        "address": b.address,
        "city": b.city,
        "state": b.state,
        "zip": b.zip,
        "county": b.county,
        "year_established": b.year_established,
        "years_in_business": b.years_in_business() or "",
        "sba_certifications": ", ".join(b.certifications),
        "naics": b.naics,
        "uei": b.key,
        "disqualified": "yes" if score.disqualified else "no",
        "disqualify_reason": score.disqualify_reason,
        "top_signals": " | ".join(score.signal_ids),
        "evidence_1": evidence[0],
        "evidence_2": evidence[1],
        "evidence_3": evidence[2],
        "other_phones": " | ".join(contacts.other_phones) if contacts else "",
        "pages_crawled": crawl.pages_crawled if crawl is not None else 0,
        "notes": " | ".join(notes),
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "key": b.key,
    }


class CsvWriter:
    """Thread-safe append-as-you-go writer with a resumable seen-list."""

    def __init__(self, path: Path | str, resume: bool = True, track_seen: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.path.with_name(f"{self.path.stem}.seen.txt")
        self.emails_path = emails_path(self.path)
        self.track_seen = track_seen

        self._lock = threading.Lock()
        self.seen: set[str] = set()

        if resume and track_seen and self.seen_path.exists():
            self.seen = {
                line.strip()
                for line in self.seen_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }

        if resume and self.path.exists():
            _upgrade_columns(self.path)

        write_header = not self.path.exists() or not resume
        mode = "w" if write_header else "a"

        self._file = self.path.open(mode, newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=COLUMNS)
        if write_header:
            self._writer.writeheader()
            self._file.flush()

        # The seen-list is only ever added to, unless the run starts over
        # (no_resume). It must not follow the results file: a new results
        # file (the old one deleted to start a fresh batch) would wipe the
        # memory of every company already done, and later runs would repeat them.
        self._seen_file = (
            self.seen_path.open("a" if resume else "w", encoding="utf-8") if track_seen else None
        )
        # The same for every email written, so a later batch never lists an
        # inbox an earlier one did, after that batch's results file is gone.
        self._emails_file = (
            self.emails_path.open("a" if resume else "w", encoding="utf-8") if track_seen else None
        )

    def write(self, row: dict) -> None:
        with self._lock:
            self._writer.writerow(row)
            self._file.flush()
            if self._seen_file is not None:
                self._seen_file.write(f"{row['key']}\n")
                self._seen_file.flush()
            if self._emails_file is not None and row.get("email"):
                self._emails_file.write(f"{row['email'].strip().lower()}\t{row['key']}\n")
                self._emails_file.flush()
            self.seen.add(row["key"])

    def mark_done(self, key: str) -> None:
        """Record a lead as finished without writing a row — one left out for
        having no working email — so later runs don't check it again."""
        with self._lock:
            if self._seen_file is not None:
                self._seen_file.write(f"{key}\n")
                self._seen_file.flush()
            self.seen.add(key)

    def already_done(self, key: str) -> bool:
        return key in self.seen

    def close(self) -> None:
        self._file.close()
        if self._seen_file is not None:
            self._seen_file.close()
        if self._emails_file is not None:
            self._emails_file.close()

    def __enter__(self) -> "CsvWriter":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def emails_path(results: Path | str) -> Path:
    """<results>.emails.txt: every email ever written, one per line, with its key."""
    results = Path(results)
    return results.with_name(f"{results.stem}.emails.txt")


def remembered_emails(results: Path | str) -> dict[str, str]:
    """{email: key} from the email memory; empty when there is none yet."""
    try:
        lines = emails_path(results).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    found: dict[str, str] = {}
    for line in lines:
        email, _, key = line.strip().partition("\t")
        if email:
            found.setdefault(email.lower(), key)
    return found


def _upgrade_columns(path: Path) -> None:
    """Rewrite a CSV from an older version with the current columns, so
    appended rows don't land under the wrong headings."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or reader.fieldnames == COLUMNS:
            return
        rows = list(reader)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sort_csv_by_score(path: Path | str) -> None:
    """Rewrite the finished CSV highest-score-first, for review."""
    path = Path(path)
    if not path.exists():
        return

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    rows.sort(key=lambda r: float(r.get("score") or 0), reverse=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
