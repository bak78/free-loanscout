# Free LoanScout

> **Branded edition.** Capital Sense Funding's colours and logo are in the window.

Finds **small businesses** — healthcare, construction and other fields — in
the SBA's Small Business Search, with the **contact person's first and last
name, email and phone**. It checks every email, reads each business's own
website to confirm it's real and for signs of growth, and writes a ranked CSV
of leads with the evidence behind every score.

**It costs nothing to run.** There are no paid lookups, no API keys and no
credits: the SBA list, the email check and the websites are all free.

```
SBA Small Business Search ──▶ email check, ──▶ its own website ──▶ free_leads.csv
(contact name, email,          free checks,     (real and running?
 phone; free)                  rank             growth signals; free)
```

Free LoanScout is SBA LoanScout without the Google lookup (Serper). Instead of
asking Google whether the business exists, it reads the business's own
website: the one on its SBA record, or else the website on its email's
domain (jane@acmehomecare.com → acmehomecare.com). A website that loads on the
same domain as the email is good proof the business is real and running.

What you give up compared with SBA LoanScout: **no Google ratings or review
counts** in the score, and a business that has closed but kept its website
can slip through.

## The easy way: the window

Double-click **`Free LoanScout GUI.bat`**. The first time, it sets itself up
(about a minute). Then:

1. **Where** — pick a state (or *All states*), and optionally the start of the
   ZIP codes (at least two digits; blank = the whole state).
2. **Industries** — tick what you want. Each heading (*Healthcare*,
   *Construction*, *Other fields*) ticks or clears its whole column.
3. **Preview** — asks the SBA and ranks every matching business from SBA
   facts alone, without reading any websites. Fast. Writes
   `out\free_leads_preview.csv`.
4. **Run** — reads the websites of the top businesses and writes
   `out\free_leads.csv`. Run again to continue down the list; businesses
   already done are skipped.
5. **Open results** opens the newest spreadsheet. **Stop** ends a run early;
   finished rows are kept.

## What's in the spreadsheet

| Column | Meaning |
|---|---|
| `first_name`, `last_name` | The contact person the business gave the SBA |
| `email` | The contact's email, as given to the SBA (checked: real shape, domain takes mail) |
| `phone` | The SBA phone, else one from its website |
| `company_name` | The name the public knows it by (its DBA when it has one) |
| `industry`, `industry_group` | e.g. *Home care* in *Healthcare* — the checkbox it came from |
| `score` | 0–100 weight; see below |
| `website_check` | What reading the website showed (below) |
| `email_is_contacts_own` | *yes* when the email carries the contact's name (jane.doe@…) |

`website_check` says one of:

- **loads; same domain as the email** — the strongest proof the business is real.
- **franchise brand page** — e.g. a Home Instead or FirstLight office page.
- **loads; different domain from the email** — a website loads, but on
  another domain than the email (often a rebrand; worth a glance).
- **didn't load** — the website is down or gone. Still listed, scored lower:
  the email's domain still takes mail, but the business may have closed.
- **no website** — none on the SBA record and a gmail-style email.

Then the website, legal name, address, year established, SBA certifications
(8(a), women-owned, HUBZone, veteran-owned), industry code, the top three
pieces of evidence, and notes.

## The score (weight)

Points come from evidence, and every point is traceable:

- **SBA facts:** years in business, the email being the contact's own, an
  email on the business's own domain, SBA certifications.
- **The website:** whether it's the business's own, hiring, expansion, new
  locations, signs of strain.

They're combined as **40% fit + 35% growth + 25% distress**, the same as the
other LoanScouts. The weights are in `config\sba.yaml` and `config\signals.yaml`.

## Who is left out, and why

Every business left out goes to **`out\free_leads_left_out.csv`** with the
reason in its first column, so nothing disappears silently.

Before any website is read:

- **Email fails the check** — badly shaped, a placeholder, a misspelled
  domain (gmial.com), a Gmail name too short to exist, or a domain that
  doesn't take mail.
- **Department inbox** — hr@, careers@, billing@, credentialing@… won't reach the owner.
- **Chain or group** — one email domain used by 3 or more businesses: one
  company's many nursing homes or branches. Email providers and franchise
  brands never count.
- **Email already used** — listed in an earlier batch (see *Memory* below).
- **Same email or same contact twice** — one owner's several companies; the
  best-ranked one is kept.
- **Nonprofit** — the SBA record says so (a `.org` email alone doesn't: most
  `.org` addresses in the list belong to for-profit companies).
- **Government or school email** (.gov, .edu, .mil), and **national chains**
  (the `national_chains` list in `sba.yaml`).
- **Churches and law firms** — never leads. Caught by name (Grace Baptist
  Church, Church of God, New Hope Ministries, Law Offices of…, Attorneys at
  Law, Esq.) or by an email or website domain like `smithlaw.com`. A business
  merely named after a church (Church Organs Inc, Cathedral Art Metal) stays.

After the website is read:

- **Closed** — its website says it has closed or is closing for good
  ("permanently closed", "we have closed our doors", "last day of business").
  Hospice wording ("final days") and privacy policies don't count.
- **A church or law firm by its website** — "join us for worship", "our
  pastor", "attorneys at law", "our law firm". A care home offering residents
  Sunday service, or a site saying "consult your attorney", doesn't count.
- **Disqualified by its website** — a nonprofit (only when the site says the
  business itself is one; an owner's bio mentioning a nonprofit doesn't count,
  and an LLC's website wording never does), a lender, a public company.
- **Chains and groups** — a website domain shared by 3 or more businesses
  in the results (franchises, listed in `franchise_domains`, stay).

## Memory

Three files in `out\` remember what's done, so no one is emailed twice:

- `free_leads.seen.txt` — every business already checked (or left out).
- `free_leads.emails.txt` — every email ever written to the results.
- `free_leads.csv` — the current batch.

To start a fresh batch for your boss, **delete only `free_leads.csv`**. Keep
the two `.txt` files.

`free_leads.emails.txt` can also be seeded with emails sent from the other
LoanScouts (one email per line), so they're never listed again.

## Industries

The checkboxes come from `config\sba.yaml`. Each line names industry codes
(NAICS), or the start of them: `"6211"` means every code starting 6211. A
business counts only in the industry of its **main** code, so consultants and
suppliers that merely list a healthcare or construction code are left out.
Add, rename or move industries there — no code change needed.

## Setup

No keys are needed. Optionally copy `.env.example` to `.env` and put in a
contact address, which the program shows to websites it reads:

```
CRAWLER_CONTACT_EMAIL=you@yourcompany.com
```

## Command line

```
.venv\Scripts\python -m free_loanscout run --state MD --group Healthcare --dry-run
.venv\Scripts\python -m free_loanscout run --state MD --industry "Home care" --limit 100
.venv\Scripts\python -m free_loanscout run --state ALL --group Construction --limit 500
```

## Good to know

- **The SBA search has no official download.** The program asks the same data
  feed the search page uses, one industry at a time, with a pause between.
  If the SBA redesigns its site, the program may need updating.
- The SBA feed can't filter by state, so each industry comes back for the
  whole country and the state is picked out here. Each day's answers are
  saved in `data\sba\`, so a second run the same day doesn't ask again.
- Websites are read politely: a pause between pages on one site, and
  `robots.txt` is respected.

## The code

Each file in `free_loanscout\` starts with a note on what it does and how it
works. `free_loanscout\__init__.py` lists every file and the order a run uses
them in — the place to start reading.

`simple_sba.py` is a one-file version of the SBA search, for learning how it
works: it asks the SBA for one industry in one state and saves the businesses
with a public contact to `simple_leads.csv`. It skips the email check, the
website reading and the score. Run it with `.venv\Scripts\python simple_sba.py`.

## Tests

```
.venv\Scripts\python -m pytest
```
