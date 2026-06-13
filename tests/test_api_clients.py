from unittest.mock import patch, MagicMock
from api_clients.workflow_client import WorkflowClient
from api_clients.template_client import TemplateClient
from api_clients.delivery_engine_client import DeliveryEngineClient
from api_clients.candidate_client import CandidateClient

@patch('requests.Session.get')
def test_workflow_client_get(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "workflow_key": "daily_vendor_outreach"}
    mock_get.return_value = mock_resp

    client = WorkflowClient()
    workflow = client.get(1)
    assert workflow is not None
    assert workflow["id"] == 1
    assert "workflow_key" in workflow
    mock_get.assert_called_once_with("http://localhost:8000/api/orchestrator/workflows/1", params=None)

@patch('requests.Session.get')
def test_workflow_client_get_by_key(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "workflow_key": "daily_vendor_outreach"}
    mock_get.return_value = mock_resp

    client = WorkflowClient()
    workflow = client.get_by_key("daily_vendor_outreach")
    assert workflow is not None
    assert workflow["workflow_key"] == "daily_vendor_outreach"
    mock_get.assert_called_once_with("http://localhost:8000/api/orchestrator/workflows/key/daily_vendor_outreach", params=None)

@patch('requests.Session.get')
def test_template_client_get(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "content_html": "<html></html>"}
    mock_get.return_value = mock_resp

    client = TemplateClient()
    template = client.get(1)
    assert template is not None
    assert template["id"] == 1
    assert "content_html" in template
    mock_get.assert_called_once_with("http://localhost:8000/api/orchestrator/email-template/1", params=None)

@patch('requests.Session.get')
def test_engine_client_get(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "engine_type": "smtp"}
    mock_get.return_value = mock_resp

    client = DeliveryEngineClient()
    engine = client.get(1)
    assert engine is not None
    assert engine["id"] == 1
    assert "engine_type" in engine
    mock_get.assert_called_once_with("http://localhost:8000/api/orchestrator/delivery-engine/1", params=None)

@patch('requests.Session.get')
def test_candidate_client_get_outreach(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 665, "email": "johora@gmail.com"}]
    mock_get.return_value = mock_resp

    client = CandidateClient()
    candidates = client.get_outreach_candidates()
    assert isinstance(candidates, list)
    assert len(candidates) == 1
    assert candidates[0]["id"] == 665
    mock_get.assert_called_once_with("http://localhost:8000/api/orchestrator/candidates/outreach", params=None)

@patch('requests.Session.post')
def test_candidate_client_update_metrics(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}
    mock_post.return_value = mock_resp

    client = CandidateClient()
    success = client.update_candidate_metrics(665, 0)
    assert success is True
    mock_post.assert_called_once_with("http://localhost:8000/api/orchestrator/candidates/665/metrics", json={"sent_count": 0})

