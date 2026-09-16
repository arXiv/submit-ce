"""Classic<->domain status mapping for admin remove (SUBMISSION-257)."""
from submit_ce.implementations.legacy_implementation import models


def test_removed_constant_is_9():
    assert models.Submission.REMOVED == 9


def test_removed_maps_to_domain_removed():
    row = models.Submission(status=models.Submission.REMOVED)
    assert row.status_from_classic() == 'removed'
