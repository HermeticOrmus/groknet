import pytest
from conftest import ToolError, register_args


def test_list_groknet_tools_names_every_tool_with_its_schema(mcp) -> None:
    result = mcp.call("list_groknet_tools")

    names = {t["name"] for t in result["tools"]}
    assert {"register", "whoami", "send_message", "call_groknet_tool"} <= names
    register = next(t for t in result["tools"] if t["name"] == "register")
    assert "handle" in register["input_schema"]["properties"]
    assert register["description"].startswith("Join Groknet")


def test_call_groknet_tool_runs_a_named_tool_with_arguments(mcp) -> None:
    assert mcp.call("call_groknet_tool", name="ping", arguments={}) == {
        "tool": "ping",
        "result": {"status": "ok", "service": "groknet"},
    }
    registered = mcp.call(
        "call_groknet_tool", name="register", arguments=register_args("meta_user")
    )
    token = registered["result"]["groknet_token"]
    me = mcp.call("call_groknet_tool", name="whoami", arguments={"groknet_token": token})
    assert me["result"]["handle"] == "meta_user"


def test_call_groknet_tool_surfaces_the_inner_tools_error_text(mcp) -> None:
    with pytest.raises(ToolError, match="@mail.grokbot.com"):
        mcp.call(
            "call_groknet_tool",
            name="register",
            arguments=register_args("meta_bad", email="x@gmail.com"),
        )


def test_call_groknet_tool_rejects_unknown_names(mcp) -> None:
    with pytest.raises(ToolError, match="list_groknet_tools"):
        mcp.call("call_groknet_tool", name="teleport", arguments={})
