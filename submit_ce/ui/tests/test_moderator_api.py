"""SubmitApi.moderators_for_categories through the real legacy implementation.

The resolution logic itself is unit-tested in
submit_ce/implementations/tests/test_moderators.py; this exercises the API seam
and its session wiring against the app's database. The moderators it relies on
are seeded by submit_ce.make_test_db.MODERATORS during bootstrap.
"""

from flask import current_app


def test_moderators_for_categories_via_api(app, authorized_user):
    with app.app_context():
        mods = current_app.api.moderators_for_categories(["math.AG"])
        emails = sorted(m.email for m in mods)

        # math.AG category-level moderator + math archive-level moderator.
        assert "ag@example.org" in emails
        assert "matharch@example.org" in emails
        # opted out of web email -> excluded by default
        assert "noweb@example.org" not in emails
        # moderator of an unrelated category -> not included
        assert "cs@example.org" not in emails
