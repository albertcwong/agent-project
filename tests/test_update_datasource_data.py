"""Test that the agent can call the update-datasource-data tool."""

from pathlib import Path

import pytest

# Ensure agent-project root on path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_root))

from agent.loop import run_agent_loop_stream
from agent.prompts import get_system_prompt
from evaluation.mocks import MockMCPPool


@pytest.mark.asyncio
async def test_agent_calls_update_datasource_data():
    """Agent executes update-datasource-data when user confirms the write action."""
    mock_pool = MockMCPPool(
        fixtures_dir=Path(__file__).parent.parent / "evaluation" / "mocks" / "fixtures",
        conversation_state={"currentDatasourceId": "ds-123"},
    )
    mock_pool.discovered_ids.add("ds-123")
    pool_dict = mock_pool.get_pool_dict()
    server_configs = [{"id": "mock", "url": "http://mock"}]

    confirmed_action = {
        "toolName": "update-datasource-data",
        "arguments": {"datasourceId": "ds-123", "contentBase64": "dGVzdC1kYXRh"},
    }

    async for _ in run_agent_loop_stream(
        question="Update the Flag Log datasource with new data",
        system_prompt=get_system_prompt(""),
        server_configs=server_configs,
        write_confirmation={"scope": "session"},
        confirmed_action=confirmed_action,
        _pool_override=pool_dict,
    ):
        pass

    tool_sequence = mock_pool.get_tool_sequence()
    assert "update-datasource-data" in tool_sequence
    call = next(c for c in mock_pool.call_log if c["tool"] == "update-datasource-data")
    assert call["args"].get("datasourceId") == "ds-123"
