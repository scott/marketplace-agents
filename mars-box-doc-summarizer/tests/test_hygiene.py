from box_doc_summarizer.hygiene import hygiene_text


def test_numeric_ranges_kept():
    assert hygiene_text("costs $60–$120 and 75–85°F") == "costs $60-$120 and 75-85°F"
    assert hygiene_text("75–85 degrees") == "75-85 degrees"


def test_prose_dash_replaced():
    assert hygiene_text("Maui — great") == "Maui, great"


def test_word_ranges_become_to():
    assert hygiene_text("June–November and April–early June") == "June to November and April to early June"


def test_unspaced_em_dash_is_a_comma_not_to():
    out = hygiene_text("must-book sights—like Haleakala—and beach stops")
    assert " to " not in out and "sights, like Haleakala, and" in out
