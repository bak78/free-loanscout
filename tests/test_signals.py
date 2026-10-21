from free_loanscout.signals import match_page, match_site


def ids(hits):
    return {h.signal_id for h in hits}


def test_growth_signals_fire_on_expanding_business(page_factory, rules):
    hits = match_page(page_factory("growing_hvac.html"), rules)
    found = ids(hits)
    assert "new_location" in found
    assert "expansion_language" in found
    assert "hiring_active" in found
    assert "capacity_strain" in found
    assert "new_equipment" in found


def test_fit_signals_fire_on_established_local_business(page_factory, rules):
    hits = match_page(page_factory("growing_hvac.html"), rules)
    found = ids(hits)
    assert "established_business" in found
    assert "has_staff" in found


def test_repeated_phrase_counts_once(page_factory, rules):
    """Invariant 1: distinct signal ids, not occurrences."""
    hits = match_page(page_factory("repetitive_hiring.html"), rules)
    hiring = [h for h in hits if h.signal_id == "hiring_active"]
    assert len(hiring) == 1


def test_negation_suppresses_distress_signals(page_factory, rules):
    """Invariant 2: 'we are NOT going out of business' is not distress."""
    hits = match_page(page_factory("negated_closing.html"), rules)
    found = ids(hits)
    assert "closed_or_closing" not in found
    assert "liquidation" not in found
    # the non-negated fit signal still lands
    assert "established_business" in found


def test_evidence_snippet_contains_the_matched_phrase(page_factory, rules):
    hits = match_page(page_factory("growing_hvac.html"), rules)
    hit = next(h for h in hits if h.signal_id == "new_location")
    assert "second location" in hit.snippet.lower()
    assert hit.source_url == "https://example.com/"


def test_page_bonus_applies_on_matching_page_type(page_factory, rules):
    home = page_factory("repetitive_hiring.html", "https://example.com/")
    careers = page_factory("repetitive_hiring.html", "https://example.com/careers")

    assert careers.page_type == "careers"

    home_hit = next(h for h in match_page(home, rules) if h.signal_id == "hiring_active")
    careers_hit = next(
        h for h in match_page(careers, rules) if h.signal_id == "hiring_active"
    )
    assert careers_hit.weight > home_hit.weight


def test_match_site_keeps_highest_weight_hit_per_signal(page_factory, rules):
    home = page_factory("repetitive_hiring.html", "https://example.com/")
    careers = page_factory("repetitive_hiring.html", "https://example.com/careers")

    hits = match_site([home, careers], rules)
    hiring = [h for h in hits if h.signal_id == "hiring_active"]

    assert len(hiring) == 1
    # the careers-page hit won, because the page bonus made it heavier
    assert hiring[0].source_url.endswith("/careers")


def test_site_hits_are_sorted_by_weight_descending(page_factory, rules):
    hits = match_site([page_factory("growing_hvac.html")], rules)
    weights = [h.weight for h in hits]
    assert weights == sorted(weights, reverse=True)


def test_disqualifier_fires_on_lender(page_factory, rules):
    hits = match_page(page_factory("bank_disqualify.html"), rules)
    assert "is_lender" in ids(hits)


def test_everyday_banking_words_are_not_a_lender(rules):
    """Each of these disqualified a real lead in October 2026."""
    from free_loanscout.extract import build_page
    texts = [
        "Benefits: Medical, Dental, Vision, 401K, HSA (Health Savings Account), Paid Holidays",
        "Board of Directors: Fred Reinhardt, Greenwood Credit Union; Carolyn Souza, Looking Upwards",
        "1. Open an Account or Pay Cash. Submit a credit account application",
        "Keith worked as Senior Vice President and Business Banking Team Leader of Berkshire Bank",
        "Revenues are in the $20 million range and still growing. The SBA loan was soon repaid.",
        "We lend a helping hand to families in need.",
    ]
    for text in texts:
        page = build_page("https://example.com/about", f"<html><body><p>{text}</p></body></html>")
        hit_ids = {h.signal_id for h in match_site([page], rules)}
        assert "is_lender" not in hit_ids, text


def test_a_lenders_own_notices_still_disqualify(rules):
    from free_loanscout.extract import build_page
    for text in ["Member FDIC. Equal Housing Lender.", "Federally insured by NCUA", "NMLS ID: 401234",
                 "We are a direct lender serving small businesses", "We offer small business loans"]:
        page = build_page("https://bank.example/", f"<html><body><p>{text}</p></body></html>")
        assert "is_lender" in {h.signal_id for h in match_site([page], rules)}, text


def _site_ids(text, rules, url="https://example.com/about"):
    from free_loanscout.extract import build_page
    page = build_page(url, f"<html><body><p>{text}</p></body></html>")
    return {h.signal_id for h in match_site([page], rules)}


def test_a_closed_business_is_left_out_not_ranked_up(rules):
    for text in ["We are permanently closed. Thank you for 12 years!",
                 "After 20 years we have closed our doors.",
                 "Our last day of business is November 1.",
                 "The agency has ceased operations.",
                 "Everything must go: we're going out of business"]:
        assert "closed_or_closing" in _site_ids(text, rules), text
    from free_loanscout.extract import build_page
    page = build_page("https://example.com/", "<p>We are permanently closed.</p>")
    hit = next(h for h in match_site([page], rules) if h.signal_id == "closed_or_closing")
    assert hit.category == "disqualify"


def test_hospice_privacy_and_holiday_wording_is_not_closing(rules):
    """Each of these is from a real, open business's website."""
    for text in ["Hospice care gives comfort and dignity in a loved one's final days.",
                 "If we cease operations or are acquired, your data may be transferred.",
                 "We are closing our doors early on Christmas Eve.",
                 "We are not permanently closed — just moving down the street!"]:
        assert "closed_or_closing" not in _site_ids(text, rules), text


def test_a_bio_or_mission_statement_is_not_a_nonprofit(rules):
    """Each of these disqualified a real for-profit lead in October 2026."""
    for text in ["As my career traversed a busy family medicine practice and a large nonprofit "
                 "organization, I spent countless hours with seniors.",
                 "Our mission is to serve families across Maryland with compassionate home care.",
                 "Jane volunteers with the Red Cross, a charitable organization."]:
        assert "nonprofit" not in _site_ids(text, rules), text


def test_a_business_that_says_it_is_a_nonprofit_still_is(rules):
    for text in ["We are a nonprofit serving Baltimore since 1990.",
                 "Hope House is a 501(c)(3) organization.",
                 "Hope House is a community-based nonprofit.",
                 "Your gift is a tax-deductible donation."]:
        assert "nonprofit" in _site_ids(text, rules), text


def test_a_churchs_or_law_firms_website_disqualifies(rules):
    for text, signal in [("Join us for worship every Sunday at 10am.", "church"),
                         ("Welcome to our church family!", "church"),
                         ("Meet our senior pastor, Rev. Dan Lee.", "church"),
                         ("Watch past sermons online.", "church"),
                         ("Smith & Jones, attorneys at law.", "law_firm"),
                         ("Our law firm has served Baltimore for 30 years.", "law_firm"),
                         ("Talk to our personal injury lawyers today.", "law_firm")]:
        assert signal in _site_ids(text, rules), text


def test_care_homes_that_mention_church_or_lawyers_are_kept(rules):
    for text in ["Residents enjoy weekly worship services and Sunday service in our chapel.",
                 "We drive clients to church, the pharmacy and appointments.",
                 "Please consult your attorney about long-term care planning.",
                 "Lawn care and snow removal for commercial properties."]:
        found = _site_ids(text, rules)
        assert not found & {"church", "law_firm"}, text
