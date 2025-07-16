def test_user_page(authorized_client, published_submission, sub_created, submitted_submission):
    """User page with published, submitted and unsubmitted."""
    resp = authorized_client.get("/")
    assert resp and resp.status_code == 200
    assert b"working" in resp.data and b"submitted" in resp.data
    #TODO assert for announced paper
