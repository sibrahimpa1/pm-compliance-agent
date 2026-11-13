from pmcompliance.names import match, normalize


def test_normalize_drops_legal_forms_and_punctuation():
    assert normalize("Northgate H.V.A.C. Services, Inc.") == "northgate hvac services"
    assert normalize("Copperleaf Plumbing Company") == normalize("Copperleaf Plumbing Co.")


def test_match_levels():
    assert match("Copperleaf Plumbing Company", "Copperleaf Plumbing Co.") == "match"
    assert match("Sparkle & Shine Cleaning, LLC", "Sparkle and Shine Cleaning LLC") == "match"
    assert match("Brightline Electrical LLC", "Brightline Electric LLC") in ("match", "review")
    assert match("Sparkle Shine Janitorial Services Inc.", "Sparkle & Shine Cleaning LLC") \
        == "mismatch"
    assert match("Zenith Roofing", "Brightline Electric LLC") == "mismatch"
