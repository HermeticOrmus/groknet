import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    # One lifespan per test session: the MCP session manager can only be started once.
    with TestClient(app) as c:
        yield c
