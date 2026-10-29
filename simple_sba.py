"""
Simple SBA LoanScout — find small businesses in the SBA's public directory
and save them to a spreadsheet. One file, no setup beyond `requests`.

WHAT IT DOES
    1. Asks the SBA's Small Business Search for every business in one industry.
    2. Keeps the ones in the state you picked that show a contact name and email.
    3. Saves them to a CSV file you can open in Excel.

HOW TO RUN IT
    Change the settings below, then in the VS Code terminal type:
        python simple_sba.py

WHERE THE DATA COMES FROM
    The website https://search.certifications.sba.gov lists businesses that
    registered to sell to the U.S. government. When you search on that page,
    your browser quietly sends a request to the SBA's data feed and gets the
    results back as data (JSON). This program sends that same request itself,
    so it never has to read the web page. Each business chose to make its
    contact person, email and phone public.

This is the simple version of free_loanscout/sba.py. The full program also
checks the emails, reads each business's website, and scores the leads.
"""

import csv
import time

import requests

# ---------------------------------------------------------------------------
# SETTINGS — change these
# ---------------------------------------------------------------------------

# The state to keep, written out in full the way the SBA writes it.
STATE = "Maryland"

# The industry, as the start of a NAICS code (the government's industry codes).
# The longer the code, the smaller and faster the search; a very short one
# like "62" (all of healthcare) is many searches and takes a long time.
# "6216" = home health care. Some others to try:
#   "6212"  dentists           "238220" plumbing, heating and air conditioning
#   "6213"  therapists         "7225"   restaurants
INDUSTRY_CODE = "6216"

# The spreadsheet to write.
OUTPUT_FILE = "simple_leads.csv"

# ---------------------------------------------------------------------------
# The SBA's addresses
# ---------------------------------------------------------------------------

# The list of every industry code the SBA knows.
NAICS_LIST_URL = "https://search.certifications.sba.gov/naicsJson.json"
# The search feed: the same address the search page sends its searches to.
SEARCH_URL = "https://search.certifications.sba.gov/_api/v2/search"

# Tell the SBA who is asking. Being honest about it is polite.
HEADERS = {"User-Agent": "SimpleLoanScout/1.0", "Content-Type": "application/json"}


def get_full_codes(code_start):
    """Turn a short code like "6216" into every full 6-digit code starting
    with it ("621610", ...). The SBA search only understands full codes."""
    print("Getting the SBA's list of industry codes...")
    response = requests.get(NAICS_LIST_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()  # stop with an error if the SBA said no

    codes = []
    for industry in response.json():
        code = str(industry.get("naics_code"))
        if len(code) == 6 and code.startswith(code_start):
            codes.append(code)
    return codes


def search_sba(codes):
    """Ask the SBA for every business registered under these industry codes.
    The answer covers the whole country, because the feed can't filter by state.

    If the SBA is too slow it answers "504 Gateway Timeout" (or 500, 502, 503).
    That means "busy, try again", so we wait and try again, up to 3 times."""

    # This is a copy of what the search page sends. Everything is left empty
    # ("search for anything") except the industry codes.
    request_body = {
        "searchProfiles": {"searchTerm": ""},
        "location": {"states": [], "zipCodes": [], "counties": [], "districts": [], "msas": []},
        "sbaCertifications": {"activeCerts": [], "isPreviousCert": False, "operatorType": "Or"},
        "naics": {"codes": [{"value": c, "label": c} for c in codes],
                  "isPrimary": False, "operatorType": "Or"},
        "selfCertifications": {"certifications": [], "operatorType": "Or"},
        "keywords": {"list": [], "operatorType": "Or"},
        "lastUpdated": {"date": {"label": "Anytime", "value": "anytime"}},
        "samStatus": {"isActiveSAM": False},
        "qualityAssuranceStandards": {"qas": []},
        "bondingLevels": {"constructionIndividual": "", "constructionAggregate": "",
                          "serviceIndividual": "", "serviceAggregate": ""},
        "businessSize": {"relationOperator": "at-least", "numberOfEmployees": ""},
        "annualRevenue": {"relationOperator": "at-least", "annualGrossRevenue": ""},
        "entityDetailId": "",
    }

    for attempt in range(1, 4):
        try:
            response = requests.post(SEARCH_URL, json=request_body, headers=HEADERS, timeout=300)
            # 500, 502, 503 and 504 all mean the SBA's server is busy or slow.
            if response.status_code not in (500, 502, 503, 504):
                response.raise_for_status()  # any other error: stop and show it
                return response.json().get("results", [])
            problem = f"the SBA answered {response.status_code} (busy)"
        except requests.exceptions.Timeout:
            problem = "the SBA took too long to answer"

        if attempt < 3:
            wait = 30 * attempt  # 30 seconds, then 60
            print(f"    {problem}; waiting {wait} seconds and trying again...")
            time.sleep(wait)

    print(f"    {problem} 3 times; skipping this code. Try again later.")
    return []


def to_lead(business):
    """Pick out the parts of one SBA record we want, or return None if the
    business didn't make a contact name and email public."""
    email = (business.get("email") or "").strip().lower()
    contact = (business.get("contact_person") or "").strip()

    # display_email is the business saying "yes, show my email in public".
    if not business.get("display_email") or "@" not in email:
        return None
    if " " not in contact:  # we want a first AND last name
        return None

    first_name = contact.split()[0].title()
    last_name = contact.split()[-1].title()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": business.get("phone") if business.get("display_phone") else "",
        # A "doing business as" name is what the public knows, so prefer it.
        "company_name": business.get("dba_name") or business.get("legal_business_name"),
        "website": business.get("website") or "",
        "city": business.get("city") or "",
        "state": business.get("state") or "",
        "zip": str(business.get("zipcode") or "")[:5],
        "year_established": business.get("year_established") or "",
    }


def main():
    # Step 1: which full industry codes to ask about.
    codes = get_full_codes(INDUSTRY_CODE)
    if not codes:
        print(f"No industry codes start with {INDUSTRY_CODE!r}. Check the setting.")
        return
    # Step 2: ask the SBA, one code at a time. Small questions get answered;
    # asking for many codes at once is what makes the SBA time out (504).
    businesses = []
    for number, code in enumerate(codes, start=1):
        time.sleep(2)  # a short pause between requests, to be polite to the SBA
        print(f"Searching the SBA for code {code} ({number} of {len(codes)})...")
        businesses += search_sba([code])
    print(f"The SBA returned {len(businesses)} businesses nationwide.")

    # Step 3: keep the ones in our state with a public contact.
    leads = []
    seen_emails = set()
    for business in businesses:
        if business.get("state") != STATE:
            continue
        lead = to_lead(business)
        if lead is None:
            continue
        if lead["email"] in seen_emails:  # skip the same email twice
            continue
        seen_emails.add(lead["email"])
        leads.append(lead)

    print(f"{len(leads)} are in {STATE} with a contact name and email.")
    if not leads:
        return

    # Step 4: save them to a spreadsheet.
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(leads[0].keys()))
        writer.writeheader()
        writer.writerows(leads)
    print(f"Saved to {OUTPUT_FILE}")


# This line means: run main() when this file is started directly.
if __name__ == "__main__":
    main()
