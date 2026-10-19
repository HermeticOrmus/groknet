import httpx


def test_fake_inbox_records_events_and_scripts_failures(fake_inbox) -> None:
    fake_inbox.respond_with = [503]
    assert (
        httpx.post(fake_inbox.url, json={"n": 1}, headers={"Authorization": "Bearer k"}).status_code
        == 503
    )
    ok = httpx.post(fake_inbox.url, json={"n": 2}, headers={"Authorization": "Bearer k"})
    assert ok.status_code == 200 and ok.json()["success"] is True
    assert fake_inbox.events == [{"n": 2}]
    assert fake_inbox.keys == ["Bearer k", "Bearer k"]
