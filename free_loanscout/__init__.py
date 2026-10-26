"""Free LoanScout: small businesses from the SBA's Small Business Search, as loan leads, at no cost.

What it does: finds small businesses that chose to publish a contact person
and email in the SBA's public directory, checks that each email can take
mail, reads the business's own website for growth and warning signs, scores
it 0-100 with the evidence behind every point, and writes the leads to a CSV.
Nothing costs money: there are no paid lookups and no API keys.

How the modules fit together, in the order a run uses them:

    cli, gui    start a run, from the command line or a desktop window
    sba         ask the SBA search for businesses, by industry and area
    emailcheck  free checks that an email address can take mail
    churchlaw   churches and law firms, which are never leads
    leads       turn one business into a scored lead (SBA facts + website)
    crawl       read the handful of a site's pages most likely to tell
    fetch       the polite HTTP under the crawl (robots.txt, rate limits)
    extract     HTML to clean text, links and contacts
    contacts    the emails and phone numbers a site publishes
    signals     match the scoring rules in signals.yaml against page text
    score       combine the matches into a 0-100 score
    export      append rows to the results CSV; remember what's done
    cleanup     move rows that aren't leads (and chains) to a left-out file
    config      load .env and signals.yaml
"""

__version__ = "0.1.0"
