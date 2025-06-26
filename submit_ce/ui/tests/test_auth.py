def test_auth(authorized_client):
    resp = authorized_client.get("/")
    assert resp.status_code == 200
