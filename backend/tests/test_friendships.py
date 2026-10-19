import pytest
from conftest import ToolError, register_args

# Users whose inbox a test never inspects still need a webhook URL that is NOT the
# real api2.cursor.sh default, or deliver() would hit the network. Port 9 refuses fast.
DEAD_INBOX = "http://127.0.0.1:9/dead"


def test_search_matches_handle_or_name_case_insensitively_and_excludes_self(mcp) -> None:
    me = mcp.call("register", **register_args("searcher", webhook_url=DEAD_INBOX))["groknet_token"]
    mcp.call(
        "register",
        **register_args("alejandro", display_name="Jorge Alejandro Diez", webhook_url=DEAD_INBOX),
    )
    mcp.call("register", **register_args("juanb", display_name="Juan", webhook_url=DEAD_INBOX))

    hits = mcp.call("search_users", groknet_token=me, query="ALE")["users"]

    assert hits == [{"handle": "alejandro", "display_name": "Jorge Alejandro Diez", "profile": {}}]
    everyone = {u["handle"] for u in mcp.call("search_users", groknet_token=me, query="")["users"]}
    assert "searcher" not in everyone and {"alejandro", "juanb"} <= everyone


def test_friend_request_reaches_the_addressees_inbox_and_is_pending(
    mcp, client, make_inbox
) -> None:
    inbox = make_inbox()
    tomas = mcp.call("register", **register_args("tomas", webhook_url=DEAD_INBOX))["groknet_token"]
    mcp.call("register", **register_args("ale", webhook_url=inbox.url, webhook_key="crsr_ale"))

    result = mcp.call("send_friend_request", groknet_token=tomas, handle="ale")

    assert result["status"] == "pending"
    [event] = inbox.events
    assert event["type"] == "friend_request"
    assert event["from"] == {"handle": "tomas", "display_name": "Tomas"}
    assert "Tomas" in event["payload"]["message"]
    assert event["event_id"]
    assert inbox.keys == ["Bearer crsr_ale"]
    rows = [f for f in client.get("/api/friendships").json() if f["id"] == result["friendship_id"]]
    assert rows[0]["requester"] == "tomas" and rows[0]["addressee"] == "ale"
    assert rows[0]["status"] == "pending"


def test_resending_a_pending_request_is_a_no_op(mcp, make_inbox) -> None:
    inbox = make_inbox()
    a = mcp.call("register", **register_args("rep-a", webhook_url=DEAD_INBOX))["groknet_token"]
    mcp.call("register", **register_args("rep-b", webhook_url=inbox.url))

    first = mcp.call("send_friend_request", groknet_token=a, handle="rep-b")
    second = mcp.call("send_friend_request", groknet_token=a, handle="rep-b")

    assert second == first
    assert len(inbox.events) == 1


def test_requesting_someone_who_already_asked_you_accepts(mcp, make_inbox) -> None:
    inbox_a, inbox_b = make_inbox(), make_inbox()
    a = mcp.call("register", **register_args("cross-a", webhook_url=inbox_a.url))["groknet_token"]
    b = mcp.call("register", **register_args("cross-b", webhook_url=inbox_b.url))["groknet_token"]
    mcp.call("send_friend_request", groknet_token=a, handle="cross-b")

    result = mcp.call("send_friend_request", groknet_token=b, handle="cross-a")

    assert result["status"] == "accepted"
    assert [e["type"] for e in inbox_a.events] == ["friend_accepted"]
    assert [e["type"] for e in inbox_b.events] == ["friend_request"]


@pytest.mark.parametrize("handle", ["nobody-here", "self-req"])
def test_requests_to_unknown_handles_or_yourself_are_rejected(mcp, handle) -> None:
    me = mcp.call("register", **register_args("self-req", webhook_url=DEAD_INBOX))["groknet_token"]
    with pytest.raises(ToolError):
        mcp.call("send_friend_request", groknet_token=me, handle=handle)


def test_accepting_tells_the_requester_and_both_sides_see_accepted(mcp, client, make_inbox) -> None:
    inbox_req, inbox_addr = make_inbox(), make_inbox()
    req = mcp.call("register", **register_args("acc-req", webhook_url=inbox_req.url))[
        "groknet_token"
    ]
    addr = mcp.call("register", **register_args("acc-addr", webhook_url=inbox_addr.url))[
        "groknet_token"
    ]
    fid = mcp.call("send_friend_request", groknet_token=req, handle="acc-addr")["friendship_id"]

    result = mcp.call(
        "respond_to_friend_request", groknet_token=addr, handle="acc-req", accept=True
    )

    assert result == {"status": "accepted"}
    [event] = inbox_req.events
    assert event["type"] == "friend_accepted"
    assert event["from"]["handle"] == "acc-addr"
    row = next(f for f in client.get("/api/friendships").json() if f["id"] == fid)
    assert row["status"] == "accepted"


def test_declining_records_declined_and_sends_nothing(mcp, client, make_inbox) -> None:
    inbox_req = make_inbox()
    req = mcp.call("register", **register_args("dec-req", webhook_url=inbox_req.url))[
        "groknet_token"
    ]
    addr = mcp.call("register", **register_args("dec-addr", webhook_url=DEAD_INBOX))[
        "groknet_token"
    ]
    fid = mcp.call("send_friend_request", groknet_token=req, handle="dec-addr")["friendship_id"]

    result = mcp.call(
        "respond_to_friend_request", groknet_token=addr, handle="dec-req", accept=False
    )

    assert result == {"status": "declined"}
    assert inbox_req.events == []
    row = next(f for f in client.get("/api/friendships").json() if f["id"] == fid)
    assert row["status"] == "declined"


def test_only_the_addressee_can_respond(mcp) -> None:
    req = mcp.call("register", **register_args("only-req", webhook_url=DEAD_INBOX))["groknet_token"]
    mcp.call("register", **register_args("only-addr", webhook_url=DEAD_INBOX))
    bystander = mcp.call("register", **register_args("only-bystander", webhook_url=DEAD_INBOX))[
        "groknet_token"
    ]
    mcp.call("send_friend_request", groknet_token=req, handle="only-addr")

    with pytest.raises(ToolError, match="pending"):  # the requester cannot accept their own request
        mcp.call("respond_to_friend_request", groknet_token=req, handle="only-addr", accept=True)
    with pytest.raises(ToolError, match="pending"):  # nor can a third party
        mcp.call(
            "respond_to_friend_request", groknet_token=bystander, handle="only-req", accept=True
        )
