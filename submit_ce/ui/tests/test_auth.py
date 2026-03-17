from submit_ce.ui.auth import _modern_auth, _ng_dict_jwt_auth
from jwt import encode


def test_modern_auth(app, authorized_user_session, jwt_secret):
    session, jwt = authorized_user_session
    with app.test_request_context("/"):
        db_session, _ = _modern_auth([jwt])
        assert db_session and db_session.session_id == session.session_id

def test_modern_auth_via_http(authorized_client):
    resp = authorized_client.get("/")
    assert resp.status_code == 200

def test_ng_auth(app, authorized_user_session, jwt_secret):
    session, _ = authorized_user_session
    with app.test_request_context("/"):
        old_style_jwt = encode({
            'user_id': session.user.user_id,
            'session_id': session.session_id,
            'nonce': 'notused',
            'expires': session.end_time.isoformat(),
        }, jwt_secret)
        db_session, _ = _ng_dict_jwt_auth([old_style_jwt])
        assert db_session and db_session.session_id == session.session_id
