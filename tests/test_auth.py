import base64
import urllib.parse

import pytest

import app as app_module


class _Resp:
    def __init__(self, payload, ok=True, status=200):
        self._payload, self.ok, self.status_code, self.text = payload, ok, status, ""

    def json(self):
        return self._payload


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(app_module, "GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(app_module, "GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(app_module, "PUBLIC_URL", "https://seo.example")
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _start_sign_in(client, next_path="/"):
    r = client.get("/login?" + urllib.parse.urlencode({"next": next_path}))
    assert r.status_code == 302
    return urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["Location"]).query)


def _google_returns(monkeypatch, userinfo):
    monkeypatch.setattr(app_module.requests, "post", lambda *a, **k: _Resp({"access_token": "at"}))
    monkeypatch.setattr(app_module.requests, "get", lambda *a, **k: _Resp(userinfo))


def test_page_redirects_to_sign_in(google):
    r = google.get("/", headers={"Accept": "text/html"})
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")


def test_fetch_calls_get_401_not_a_redirect(google):
    r = google.get("/status", headers={"Accept": "application/json"})
    assert r.status_code == 401


def test_webhooks_and_health_stay_open(google):
    assert google.get("/health").status_code == 200
    # Reaches the signature check (401 for a bad signature), not the sign-in gate (302).
    r = google.post("/webhooks/products/create", data=b"{}", headers={"X-Shopify-Hmac-Sha256": "nope"})
    assert r.status_code == 401


def test_login_asks_google_for_the_aflalo_domain(google):
    q = _start_sign_in(google)
    assert q["hd"] == ["aflalonyc.com"]
    assert q["redirect_uri"] == ["https://seo.example/auth/callback"]
    assert q["client_id"] == ["cid.apps.googleusercontent.com"]


def test_aflalo_account_signs_in_and_returns_to_its_page(google, monkeypatch):
    q = _start_sign_in(google, "/?tab=photos")
    _google_returns(monkeypatch, {"email": "Lillian@aflalonyc.com", "email_verified": True, "hd": "aflalonyc.com"})
    r = google.get("/auth/callback?" + urllib.parse.urlencode({"state": q["state"][0], "code": "c"}))
    assert r.status_code == 302 and r.headers["Location"] == "/?tab=photos"
    with google.session_transaction() as s:
        assert s["user"] == "lillian@aflalonyc.com"


@pytest.mark.parametrize("userinfo", [
    {"email": "someone@gmail.com", "email_verified": True},
    {"email": "x@aflalonyc.com", "email_verified": False, "hd": "aflalonyc.com"},
    {"email": "x@aflalonyc.com", "email_verified": True},             # personal Google account, no Workspace hd
    {"email": "x@aflalonyc.com.evil.com", "email_verified": True, "hd": "aflalonyc.com.evil.com"},
])
def test_other_accounts_are_refused(google, monkeypatch, userinfo):
    q = _start_sign_in(google)
    _google_returns(monkeypatch, userinfo)
    r = google.get("/auth/callback?" + urllib.parse.urlencode({"state": q["state"][0], "code": "c"}))
    assert r.status_code == 403
    with google.session_transaction() as s:
        assert "user" not in s


def test_callback_without_matching_state_is_refused(google, monkeypatch):
    _start_sign_in(google)
    _google_returns(monkeypatch, {"email": "a@aflalonyc.com", "email_verified": True, "hd": "aflalonyc.com"})
    r = google.get("/auth/callback?state=forged&code=c")
    assert r.status_code == 400


def test_next_cannot_leave_the_site(google):
    _start_sign_in(google, "//evil.example/x")
    with google.session_transaction() as s:
        assert s["next"] == "/"


def test_sign_out_clears_the_session(google):
    with google.session_transaction() as s:
        s["user"] = "a@aflalonyc.com"
    assert google.get("/logout").status_code == 200
    with google.session_transaction() as s:
        assert "user" not in s


def test_password_still_works_without_google(monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "pw")
    client = app_module.app.test_client()
    assert client.get("/pending").status_code == 401
    ok = {"Authorization": "Basic " + base64.b64encode(b"anyone:pw").decode()}
    assert client.get("/pending", headers=ok).status_code == 200
