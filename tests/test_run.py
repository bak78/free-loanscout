"""Scoring a business, and whole runs — with the SBA, email checks and
websites stubbed, so nothing touches the internet."""

import csv
import threading
from datetime import date

import pytest

from free_loanscout import cli, leads
from free_loanscout.crawl import SiteCrawl
from free_loanscout.export import COLUMNS, build_row
from free_loanscout.extract import build_page
from free_loanscout.sba import load_sba_rules, parse_business
from test_sba import FakeClient, rec

TODAY = date(2026, 10, 19)


@pytest.fixture(scope="module")
def srules():
    return load_sba_rules()


def business(srules, **overrides):
    b, why = parse_business(rec(**overrides), srules.field_named("Therapy (PT, OT, speech)"))
    assert b is not None, why
    return b


class StubFetcher:
    """Stands in for PoliteFetcher; the crawl itself is stubbed per test."""

    def stop(self):
        pass

    def close(self):
        pass


def loads(url, *args, **kwargs):
    crawl = SiteCrawl(domain="", start_url=url)
    crawl.pages = [build_page(url, "<p>Welcome to our practice.</p>")]
    return crawl


def wont_load(url, *args, **kwargs):
    return SiteCrawl(domain="", start_url=url)


class Sites:
    """crawl_site that loads only the listed domains, and remembers what it read."""

    def __init__(self, *live):
        self.live = live
        self.read = []

    def __call__(self, url, *args, **kwargs):
        self.read.append(url)
        return loads(url) if any(d in url for d in self.live) else wont_load(url)


class StubChecker:
    """No DNS: emails at these domains fail, all others pass."""
    bad = {"deadmail.com": "domain doesn't accept mail"}

    def needs_dns(self, email):
        return False

    def domain_problem(self, domain):
        return self.bad.get(domain, "")

    def problem(self, email):
        return self.bad.get(email.rpartition("@")[2], "")


# --- scoring ------------------------------------------------------------------------------------


def test_sba_facts_score_without_reading_anything(rules, srules):
    lead = leads.build_lead(business(srules), None, rules, srules, 8, TODAY)
    assert {"sba_registered", "established", "contacts_own_email", "company_domain", "sba_certified"} <= set(
        lead.score.signal_ids)
    assert lead.email_is_contacts_own and not lead.score.disqualified
    assert lead.website_check == leads.SITE_NOT_CHECKED


def test_its_own_website_loading_raises_the_weight(rules, srules, monkeypatch):
    monkeypatch.setattr(leads, "crawl_site", loads)
    alone = leads.build_lead(business(srules), None, rules, srules, 8, TODAY).score.total
    checked = leads.build_lead(business(srules), StubFetcher(), rules, srules, 8, TODAY)
    assert checked.website_check == leads.SITE_OWN and checked.confirmed_by_website
    assert checked.score.total > alone


@pytest.mark.parametrize("overrides, reason", [
    (dict(business_type_codes="A8"), "nonprofit"),
    (dict(email="director@county.gov"), "public_body"),
    (dict(email="store9@walgreens.com"), "national_chain"),
])
def test_never_leads(rules, srules, overrides, reason):
    lead = leads.build_lead(business(srules, **overrides), None, rules, srules, 8, TODAY)
    assert lead.score.disqualified and reason in lead.score.disqualify_reason


def test_an_org_email_alone_is_not_a_nonprofit(rules, srules):
    # Most .org addresses in the SBA list belong to for-profit companies.
    lead = leads.build_lead(business(srules, email="jane@carepartners.org"), None, rules, srules, 8, TODAY)
    assert not lead.score.disqualified


def test_the_row_has_every_column(rules, srules, monkeypatch):
    monkeypatch.setattr(leads, "crawl_site", loads)
    row = build_row(leads.build_lead(business(srules), StubFetcher(), rules, srules, 8, TODAY), rules)
    assert set(row) == set(COLUMNS)
    assert (row["first_name"], row["last_name"], row["email"]) == ("Shannon", "Murphy", "smurphy@bodysensept.com")
    assert (row["industry"], row["industry_group"]) == ("Therapy (PT, OT, speech)", "Healthcare")
    assert row["phone_source"] == "SBA" and row["email_is_contacts_own"] == "yes"
    assert row["website_check"] == leads.SITE_OWN


# --- which website is read -------------------------------------------------------------------


@pytest.mark.parametrize("email, website, live, check", [
    ("arielle@mindsetqualityllc.com", "https://mindsetqualityllc.com", ["mindsetqualityllc"], leads.SITE_OWN),
    ("tyler@thomaspointcap.com", "https://www.homeinstead.com/131", [], leads.SITE_FRANCHISE),
    ("jane@gmail.com", "https://janesclinic.com", ["janesclinic"], leads.SITE_OTHER),
    ("jane@gmail.com", "https://janesclinic.com", [], leads.SITE_DEAD),
    ("jane@gmail.com", "", [], leads.SITE_NONE),
    # No website on the SBA record: the email's own domain is tried instead.
    ("jane@janesclinic.com", "", ["janesclinic"], leads.SITE_OWN),
    # The SBA website is dead, but the email's domain loads.
    ("jane@janesclinic.com", "https://oldsite.com", ["janesclinic"], leads.SITE_OWN),
])
def test_what_the_website_check_finds(rules, srules, monkeypatch, email, website, live, check):
    monkeypatch.setattr(leads, "crawl_site", Sites(*live))
    lead = leads.build_lead(business(srules, email=email, website=website), StubFetcher(), rules, srules, 8, TODAY)
    assert lead.website_check == check


def test_a_dead_website_is_still_shown_in_the_row(rules, srules, monkeypatch):
    monkeypatch.setattr(leads, "crawl_site", Sites())
    b = business(srules, email="jane@janesclinic.com", website="https://oldsite.com")
    lead = leads.build_lead(b, StubFetcher(), rules, srules, 8, TODAY)
    assert lead.website_check == leads.SITE_DEAD and "oldsite.com" in lead.website


# --- whole runs ---------------------------------------------------------------------------------


@pytest.fixture
def sites(monkeypatch):
    found = Sites("practice", "bodysensept")
    monkeypatch.setattr(leads, "crawl_site", found)
    return found


@pytest.fixture
def workdir(tmp_path, monkeypatch, sites):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "EmailChecker", StubChecker)
    return tmp_path


def _rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _records(n):
    return [rec(uei=f"U{i}", email=f"owner{i}@gmail.com", contact_person=f"PAT SMITH{chr(65 + i)}",
                website=f"www.practice{i}.com")
            for i in range(n)]


OPTIONS = dict(state="MD", zip_prefixes=(), fields=("Therapy (PT, OT, speech)",), out="out/leads.csv", workers=1)


def run(records, stop=None, **overrides):
    return cli.run_leads(cli.RunOptions(**(OPTIONS | overrides)), stop, sba_client=FakeClient(records),
                         fetcher=StubFetcher())


def test_preview_reads_no_websites_and_writes_every_business(workdir, sites):
    assert run(_records(4), dry_run=True) == cli.EXIT_OK
    assert sites.read == []
    assert len(_rows(workdir / "out/leads_preview.csv")) == 4


def test_run_checks_the_limit_and_resumes_where_it_stopped(workdir, sites):
    assert run(_records(3), limit=2) == cli.EXIT_OK
    assert len(sites.read) == 2
    assert run(_records(3), limit=2) == cli.EXIT_OK
    assert len(sites.read) == 3, "the second run only checked the one left"
    assert len(_rows(workdir / "out/leads.csv")) == 3
    assert run(_records(3), limit=2) == cli.EXIT_DEPLETED


def test_a_business_whose_website_wont_load_is_kept_and_says_so(workdir):
    assert run([rec(uei="D1", email="pat@gmail.com", website="www.gone.com")]) == cli.EXIT_OK
    [row] = _rows(workdir / "out/leads.csv")
    assert row["website_check"] == leads.SITE_DEAD


def test_free_checks_leave_businesses_out_before_any_website_is_read_with_reasons(workdir, sites):
    records = [
        rec(uei="GOOD", email="owner@gmail.com", contact_person="ANA LOPEZ"),
        rec(uei="DEPT", email="hr@bodysensept.com", contact_person="BEN KIM"),
        rec(uei="DEAD", email="x@deadmail.com", contact_person="CY DOE"),
        rec(uei="NPO", email="npo@gmail.com", contact_person="DEE FOX", business_type_codes="A8"),
        rec(uei="TWIN", email="owner@gmail.com", contact_person="EVE RAY"),
        rec(uei="SAME", email="other@gmail.com", contact_person="ANA LOPEZ"),
    ]
    assert run(records) == cli.EXIT_OK
    assert len(sites.read) == 1
    assert [r["key"] for r in _rows(workdir / "out/leads.csv")] == ["GOOD"]
    reasons = {r["key"]: r["left_out_reason"] for r in _rows(workdir / "out/leads_left_out.csv")}
    assert reasons["DEPT"].startswith("department inbox")
    assert reasons["DEAD"].startswith("email fails the check")
    assert reasons["NPO"].startswith("disqualified: nonprofit")
    assert reasons["TWIN"].startswith("same email as")
    assert reasons["SAME"].startswith("same contact as")
    # Recorded once: a second run neither reads them nor writes them again.
    run(records)
    assert len(_rows(workdir / "out/leads_left_out.csv")) == 5


def test_an_email_from_an_earlier_batch_is_not_listed_again(workdir, sites):
    run([rec(uei="A", email="pat@gmail.com")])
    (workdir / "out/leads.csv").unlink()  # sent to the boss; a fresh batch starts
    run([rec(uei="B", email="pat@gmail.com")])
    assert len(sites.read) == 1
    reasons = [r["left_out_reason"] for r in _rows(workdir / "out/leads_left_out.csv")]
    assert reasons == ["pat@gmail.com already used for another lead"]


def test_stop_before_reading_writes_nothing(workdir):
    stop = threading.Event()
    stop.set()
    assert run(_records(2), stop) == cli.EXIT_INTERRUPTED


def test_zip_codes_need_a_state(workdir):
    assert run([], state="ALL", zip_prefixes=("212",)) == cli.EXIT_CONFIG_ERROR


def test_groups_on_the_command_line_mean_all_their_industries():
    names = cli.fields_from(None, ["construction"])
    assert "Roofing" in names and len(names) == 8


# --- chains and credentialing inboxes --------------------------------------------------------


def test_one_companys_many_businesses_are_a_chain_before_any_website_is_read(workdir, sites):
    homes = [rec(uei=f"N{i}", email=f"admin{i}@chs-corp.com", contact_person=f"PAT LEE{chr(65 + i)}",
                 website=f"www.home{i}.com") for i in range(3)]
    run(homes + _records(1))
    assert len(sites.read) == 1, "no time spent on the chain"
    reasons = [r["left_out_reason"] for r in _rows(workdir / "out/leads_left_out.csv")]
    assert reasons == ["chain or group: chs-corp.com is shared by 3 businesses"] * 3


def test_a_credentialing_inbox_is_a_department_inbox():
    from free_loanscout.contacts import is_wrong_department

    assert is_wrong_department("credentialing@chs-corp.com")


def test_an_llcs_website_alone_cant_make_it_a_nonprofit(rules, srules, monkeypatch):
    def nonprofit_site(url, *args, **kwargs):
        crawl = SiteCrawl(domain="", start_url=url)
        crawl.pages = [build_page(url, "<p>We are a nonprofit serving seniors.</p>")]
        return crawl

    monkeypatch.setattr(leads, "crawl_site", nonprofit_site)
    llc = leads.build_lead(business(srules, legal_business_name="BUNNY'S HOME CARE, LLC"), StubFetcher(),
                           rules, srules, 8, TODAY)
    assert not llc.score.disqualified
    inc = leads.build_lead(business(srules, legal_business_name="HOPE HOUSE INC"), StubFetcher(),
                           rules, srules, 8, TODAY)
    assert inc.score.disqualified and "nonprofit" in inc.score.disqualify_reason
    # The SBA's own nonprofit code still counts for an LLC.
    coded = leads.build_lead(business(srules, legal_business_name="X LLC", business_type_codes="A8"),
                             None, rules, srules, 8, TODAY)
    assert coded.score.disqualified


def test_professional_services_is_no_longer_an_industry(srules):
    assert "Professional services" not in [f.name for _, fields in srules.groups for f in fields]
