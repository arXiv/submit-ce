"""``routes_to_general_category`` matches ``GENPH`` patterns as legacy Perl does.

The patterns are made up, in the shapes the real table uses: full addresses
with ``\\@``, escaped and bare dots, ``.*``, groups, alternation, one domain.
Names are fictional animals, never real people.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from submit_ce.implementations.legacy_implementation import models
from submit_ce.implementations.legacy_implementation.suspect import \
    routes_to_general_category

PATTERNS = [
    ("GENPH", r"baloo\@example\.org"),
    ("GENPH", r"bagheera\@mail.example"),
    ("GENPH", r"\@hundred-acre\.example"),
    ("GENPH", r"(piglet|eeyore)\@wood\.example"),
    ("GENPH", r"kaa.*\@jungle\.example"),
    ("GENPH", r"tigger\@bounce\.example)|(roo\@pouch\.example"),  # needs Perl's (...) wrap
    ("GENPH", r"heffalump\@(dream"),  # invalid as a regex; skipped
    ("SUSPECT", r"shere-khan\@example\.org"),
]


@pytest.fixture
def session():
    """An in-memory database holding just the tables the lookup reads."""
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(models.SuspectEmail(type=type_, pattern=pattern)
                        for type_, pattern in PATTERNS)
        session.commit()
        yield session


@pytest.mark.parametrize("email, routed", [
    ("baloo@example.org", True),
    ("Baloo@Example.ORG", True),        # case-insensitive
    ("xbaloo@example.org.uk", True),    # not anchored
    ("bagheera@mailXexample", True),    # a bare dot matches any character
    ("pooh@hundred-acre.example", True),
    ("eeyore@wood.example", True),
    ("kaa.python@jungle.example", True),
    ("roo@pouch.example", True),
    ("baloo@example.com", False),
    ("shere-khan@example.org", False),  # SUSPECT patterns flag authors instead
    ("hathi@physics.example", False),
])
def test_genph_patterns(session, email, routed):
    assert routes_to_general_category(session, "1", email) is routed


def test_invalid_pattern_is_logged_by_id(session, caplog):
    """A pattern is a flagged person's address; the log names only its row."""
    routes_to_general_category(session, "1", "hathi@physics.example")
    row_id = session.scalar(select(models.SuspectEmail.id)
                            .where(models.SuspectEmail.pattern.startswith("heffalump")))
    assert "heffalump" not in caplog.text
    assert f"arXiv_suspect_emails id {row_id}" in caplog.text
