"""Dashboard login (issue #12): a 6-digit code delivered through the bot's own inbox."""

import re
from datetime import timedelta

import pytest
from conftest import register_args
from sqlmodel import Session, delete, select

from app import config
from app.db import engine
from app.events import bus
from app.models import LoginCode, User, now


@pytest.fixture(autouse=True)
def _clean_tables_after_each_test(client, monkeypatch):
    # The TestClient talks plain http://testserver, which would drop a Secure cookie.
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://testserver")
    client.cookies.clear()
    yield
    client.cookies.clear()
    with Session(engine) as session:
        session.exec(delete(LoginCode))
        session.exec(delete(User).where(User.handle.startswith("auth_")))
        session.commit()


def register(client, handle: str, **overrides) -> None:
    resp = client.post("/api/register", json=register_args(handle, **overrides))
    assert resp.status_code == 201, resp.text


def start(client, email: str):
    return client.post("/api/auth/start", json={"email": email})


def verify(client, email: str, code: str):
    return client.post("/api/auth/verify", json={"email": email, "code": code})


def last_code(inbox) -> str:
    return inbox.events[-1]["payload"]["code"]


def test_start_delivers_login_code_to_own_inbox(client, fake_inbox) -> None:
    register(client, "auth_a", webhook_url=fake_inbox.url)
    resp = start(client, "  AUTH_A@mail.grokbot.com ")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sent": True}

    assert len(fake_inbox.events) == 1
    event = fake_inbox.events[0]
    assert event["type"] == "login_code"
    assert event["from"]["handle"] == "auth_a"
    code = event["payload"]["code"]
    assert re.fullmatch(r"\d{6}", code)
    assert event["payload"]["expires_in_minutes"] == 10
    assert code in event["payload"]["message"]
    assert fake_inbox.keys[0] == "Bearer crsr_auth_a_secret"


def test_verify_sets_cookie_and_me_works(client, fake_inbox) -> None:
    register(client, "auth_b", display_name="Bea", webhook_url=fake_inbox.url)
    q = bus.subscribe()
    try:
        start(client, "auth_b@mail.grokbot.com")
        code = last_code(fake_inbox)
        resp = verify(client, "auth_b@mail.grokbot.com", code)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
    finally:
        bus.unsubscribe(q)
    assert resp.status_code == 200, resp.text
    expected = {"handle": "auth_b", "display_name": "Bea", "email": "auth_b@mail.grokbot.com"}
    assert resp.json() == expected
    set_cookie = resp.headers["set-cookie"]
    assert "groknet_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "Max-Age=604800" in set_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == expected

    joined = "\n".join(events)
    assert '"login_requested"' in joined and '"login_succeeded"' in joined
    assert code not in joined


def test_cookie_is_secure_behind_https(client, fake_inbox, monkeypatch) -> None:
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://groknet.eastwood.ai")
    register(client, "auth_s", webhook_url=fake_inbox.url)
    start(client, "auth_s@mail.grokbot.com")
    resp = verify(client, "auth_s@mail.grokbot.com", last_code(fake_inbox))
    assert resp.status_code == 200
    assert "Secure" in resp.headers["set-cookie"]


def test_code_is_single_use(client, fake_inbox) -> None:
    register(client, "auth_c", webhook_url=fake_inbox.url)
    start(client, "auth_c@mail.grokbot.com")
    code = last_code(fake_inbox)
    assert verify(client, "auth_c@mail.grokbot.com", code).status_code == 200
    client.cookies.clear()
    assert verify(client, "auth_c@mail.grokbot.com", code).status_code == 401


def test_wrong_code_is_401(client, fake_inbox) -> None:
    register(client, "auth_d", webhook_url=fake_inbox.url)
    start(client, "auth_d@mail.grokbot.com")
    wrong = "000000" if last_code(fake_inbox) != "000000" else "111111"
    resp = verify(client, "auth_d@mail.grokbot.com", wrong)
    assert resp.status_code == 401
    assert "groknet_session" not in resp.headers.get("set-cookie", "")


def test_expired_code_is_401(client, fake_inbox) -> None:
    register(client, "auth_e", webhook_url=fake_inbox.url)
    start(client, "auth_e@mail.grokbot.com")
    with Session(engine) as session:
        row = session.exec(
            select(LoginCode).where(LoginCode.email == "auth_e@mail.grokbot.com")
        ).one()
        row.expires_at = now() - timedelta(seconds=1)
        session.add(row)
        session.commit()
    assert verify(client, "auth_e@mail.grokbot.com", last_code(fake_inbox)).status_code == 401


def test_non_grokbot_email_is_400(client) -> None:
    resp = start(client, "someone@gmail.com")
    assert resp.status_code == 400
    assert resp.json()["sent"] is False
    assert "@mail.grokbot.com" in resp.json()["detail"]


def test_unknown_email_is_400(client) -> None:
    resp = start(client, "auth_nobody@mail.grokbot.com")
    assert resp.status_code == 400
    assert resp.json()["sent"] is False
    assert "register" in resp.json()["detail"].lower()


def test_second_start_invalidates_first_code(client, fake_inbox) -> None:
    register(client, "auth_f", webhook_url=fake_inbox.url)
    start(client, "auth_f@mail.grokbot.com")
    first = last_code(fake_inbox)
    start(client, "auth_f@mail.grokbot.com")
    second = last_code(fake_inbox)
    if first != second:
        assert verify(client, "auth_f@mail.grokbot.com", first).status_code == 401
    assert verify(client, "auth_f@mail.grokbot.com", second).status_code == 200


def test_sixth_start_in_window_is_429(client, fake_inbox) -> None:
    register(client, "auth_g", webhook_url=fake_inbox.url)
    for _ in range(5):
        assert start(client, "auth_g@mail.grokbot.com").status_code == 200
    resp = start(client, "auth_g@mail.grokbot.com")
    assert resp.status_code == 429
    assert resp.json()["sent"] is False
    assert len(fake_inbox.events) == 5


def test_unreachable_inbox_is_502(client) -> None:
    register(client, "auth_h")  # closed port, delivery fails
    resp = start(client, "auth_h@mail.grokbot.com")
    assert resp.status_code == 502
    assert resp.json()["sent"] is False


def test_me_without_valid_cookie_is_401(client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set("groknet_session", "auth_forged.not-signed")
    assert client.get("/api/auth/me").status_code == 401


def test_logout_clears_cookie(client, fake_inbox) -> None:
    register(client, "auth_i", webhook_url=fake_inbox.url)
    start(client, "auth_i@mail.grokbot.com")
    verify(client, "auth_i@mail.grokbot.com", last_code(fake_inbox))
    assert client.get("/api/auth/me").status_code == 200
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert "Max-Age=0" in resp.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401
