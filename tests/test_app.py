from fastapi.testclient import TestClient
from app import app
from unittest.mock import patch

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@patch("app.WorkflowExecutor")
def test_trigger_workflow(MockExecutor):
    mock_instance = MockExecutor.return_value
    
    response = client.post("/api/v1/trigger", json={"workflow_id": 1})
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "run_id" in data
    
    # Verify background task was added (indirectly via mock)
    # Since background tasks are hard to assert in integration tests without 
    # capturing the task list, we rely on the response for now.
    # A true unit test of the endpoint logic would verify the background task addition.
