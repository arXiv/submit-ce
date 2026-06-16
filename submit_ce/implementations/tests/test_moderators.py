import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from submit_ce.implementations.legacy_implementation.models import (
    Base, User, Moderator,
)
from submit_ce.implementations.legacy_implementation.moderators import (
    split_category,
    moderators_for_categories,
    moderator_emails,
)


@pytest.fixture
def db_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _user(session, user_id, email, first="Mod", last="Erator"):
    session.add(User(user_id=user_id, email=email,
                     first_name=first, last_name=last))


def _seed(session):
    # math.AG category-level moderator
    _user(session, 1, "ag@example.org", "Alice", "Gauss")
    session.add(Moderator(user_id=1, archive="math", subject_class="AG"))
    # math archive-level moderator (covers all of math)
    _user(session, 2, "matharch@example.org", "Marc", "Archive")
    session.add(Moderator(user_id=2, archive="math", subject_class=""))
    # unrelated cs.AI moderator
    _user(session, 3, "cs@example.org", "Carol", "Sharp")
    session.add(Moderator(user_id=3, archive="cs", subject_class="AI"))
    # math.AG moderator who opted out of web email
    _user(session, 4, "noweb@example.org", "Nora", "Webless")
    session.add(Moderator(user_id=4, archive="math", subject_class="AG",
                          no_web_email=1))
    session.commit()


def test_split_category():
    assert split_category("math.AG") == ("math", "AG")
    assert split_category("hep-th") == ("hep-th", "")
    assert split_category("astro-ph.GA") == ("astro-ph", "GA")


def test_resolves_category_and_archive_level(db_session):
    _seed(db_session)
    mods = moderators_for_categories(db_session, ["math.AG"])
    emails = [m.email for m in mods]
    # category-level AG mod + archive-level math mod; excludes cs.AI and no_web.
    assert emails == ["ag@example.org", "matharch@example.org"]
    assert sorted(emails) == emails  # sorted by email


def test_excludes_no_web_email_by_default(db_session):
    _seed(db_session)
    emails = moderator_emails(db_session, ["math.AG"])
    assert "noweb@example.org" not in emails


def test_include_no_web_email_when_not_excluded(db_session):
    _seed(db_session)
    emails = moderator_emails(db_session, ["math.AG"],
                              exclude_no_web_email=False)
    assert "noweb@example.org" in emails


def test_dedupes_across_categories(db_session):
    # An archive-level math moderator is reached by both math.AG and math.CO.
    _seed(db_session)
    mods = moderators_for_categories(db_session, ["math.AG", "math.CO"])
    emails = [m.email for m in mods]
    assert emails.count("matharch@example.org") == 1


def test_unknown_category_returns_no_moderators(db_session):
    _seed(db_session)
    assert moderators_for_categories(db_session, ["q-bio.NC"]) == []


def test_archive_level_flag_and_category(db_session):
    _seed(db_session)
    mods = {m.email: m for m in
            moderators_for_categories(db_session, ["math.AG"])}
    assert mods["matharch@example.org"].is_archive_level
    assert mods["matharch@example.org"].category == "math"
    assert not mods["ag@example.org"].is_archive_level
    assert mods["ag@example.org"].category == "math.AG"
