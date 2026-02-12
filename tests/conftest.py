import pytest
from app import app
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_workflow_data():
    return {
        "id": 1,
        "workflow_key": "test_workflow",
        "name": "Test Workflow",
        "workflow_type": "EMAIL_SENDER",
        "email_template_id": 1,
        "delivery_engine_id": 1,
        "recipient_list_sql": "SELECT * FROM test",
        "status": "active"
    }

@pytest.fixture
def mock_recipient_data():
    from models.recipient import Recipient
    return Recipient(
        email="test@example.com",
        name="Test User",
        metadata={"key": "value"}
    )
