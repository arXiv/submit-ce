from submit_ce.domain.meta import Classification


def test_classification_displays_the_category_name():
    """As browse shows subjects, and as arxiv-base's abs macro asks for them."""
    assert Classification(category='astro-ph.GA').display() == \
        'Astrophysics of Galaxies (astro-ph.GA)'


def test_classification_displays_an_unknown_category_as_its_id():
    assert Classification(category='xx.YY').display() == 'xx.YY'
