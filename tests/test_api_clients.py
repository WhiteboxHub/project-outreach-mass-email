from api_clients.workflow_client import WorkflowClient
from api_clients.template_client import TemplateClient
from api_clients.delivery_engine_client import DeliveryEngineClient

def test_workflow_client_get():
    client = WorkflowClient()
    workflow = client.get(1)
    assert workflow is not None
    assert workflow["id"] == 1
    assert "workflow_key" in workflow

def test_workflow_client_get_by_key():
    client = WorkflowClient()
    workflow = client.get_by_key("daily_vendor_outreach")
    assert workflow is not None
    assert workflow["workflow_key"] == "daily_vendor_outreach"

def test_template_client_get():
    client = TemplateClient()
    template = client.get(1)
    assert template is not None
    assert template["id"] == 1
    assert "content_html" in template

def test_engine_client_get():
    client = DeliveryEngineClient()
    engine = client.get(1)
    assert engine is not None
    assert engine["id"] == 1
    assert "engine_type" in engine
