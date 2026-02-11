import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from executor.workflow_executor import WorkflowExecutor
from executor.template_renderer import TemplateRenderer
from executor.recipient_resolver import RecipientResolver
from executor.engine_builder import EngineBuilder
from models.recipient import Recipient
from utils.retry import RetryManager
import asyncio

# --- Template Tests ---
def test_template_renderer_strict():
    renderer = TemplateRenderer()
    template = "Hello {{ name }}"
    
    # Success
    assert renderer.render(template, {"name": "World"}) == "Hello World"
    
    # Fail strict
    with pytest.raises(ValueError):
        renderer.render(template, {}) # Missing 'name'

def test_template_validation():
    renderer = TemplateRenderer()
    template = "Hello {{ name }} and {{ other }}"
    
    missing = renderer.validate(template, {"name": "World"})
    assert "other" in missing
    assert "name" not in missing

# --- Engine Builder Tests ---
def test_engine_builder_validation():
    # Valid
    config = {"engine_type": "SMTP", "from_email": "a@b.com", "status": "active"}
    assert EngineBuilder.build(config) is not None
    
    # Invalid: Inactive
    with pytest.raises(ValueError, match="not active"):
        EngineBuilder.build({**config, "status": "inactive"})
        
    # Invalid: Missing field (SendGrid)
    # Using the string value directly since we know it from the Enum definition (likely "SENDGRID")
    with pytest.raises(ValueError, match="requires 'api_key'"):
        EngineBuilder.build({"engine_type": "SENDGRID", "from_email": "a@b.com"})

# --- Workflow Executor Tests ---

@pytest.mark.asyncio
@patch("executor.workflow_executor.WorkflowClient")
@patch("executor.workflow_executor.TemplateClient")
@patch("executor.workflow_executor.DeliveryEngineClient")
@patch("executor.workflow_executor.LogClient")
@patch("executor.workflow_executor.RecipientResolver")
@patch("executor.workflow_executor.EngineBuilder")
async def test_workflow_executor_retry_logic(
    MockEngineBuilder, MockRecipientResolver, MockLogClient, 
    MockEngineClient, MockTemplateClient, MockWorkflowClient
):
    # Setup Mocks
    MockWorkflowClient.return_value.get.return_value = {
        "id": 1, "email_template_id": 1, "delivery_engine_id": 1, "recipient_list_sql": "sql"
    }
    MockTemplateClient.return_value.get.return_value = {
        "subject": "Hi {{ recipient_name }}", "content_html": "Body"
    }
    MockEngineClient.return_value.get.return_value = {
        "engine_type": "SMTP", "from_email": "test@test.com", 
        "rate_limit_per_minute": 600, "status": "active"
    }
    MockRecipientResolver.return_value.resolve.return_value = [
        Recipient(email="r1@test.com", name="R1", metadata={})
    ]

    # Mock Sender with transient failure then success
    mock_sender = MockEngineBuilder.build.return_value
    # 1st call raises transient error, 2nd call succeeds
    mock_sender.send = AsyncMock(side_effect=[Exception("Connection timeout"), True])

    # Execute
    executor = WorkflowExecutor()
    result = await executor.execute_workflow(workflow_id=1, run_id="retry_test")

    # Assert
    assert result["status"] == "success"
    assert result["processed"] == 1
    # Check that send was called twice (1 failure + 1 retry)
    assert mock_sender.send.call_count == 2

@pytest.mark.asyncio
@patch("executor.workflow_executor.WorkflowClient")
@patch("executor.workflow_executor.TemplateClient")
@patch("executor.workflow_executor.DeliveryEngineClient")
@patch("executor.workflow_executor.LogClient")
@patch("executor.workflow_executor.RecipientResolver")
@patch("executor.workflow_executor.EngineBuilder")
async def test_workflow_executor_template_fail(
    MockEngineBuilder, MockRecipientResolver, MockLogClient, 
    MockEngineClient, MockTemplateClient, MockWorkflowClient
):
    # Setup Mocks
    MockWorkflowClient.return_value.get.return_value = {"id": 1, "email_template_id": 1, "delivery_engine_id": 1, "recipient_list_sql": "sql"}
    
    # Template requires 'unknown_var' NOT in recipient context
    MockTemplateClient.return_value.get.return_value = {
        "subject": "Hi", "content_html": "Body {{ unknown_var }}"
    }
    
    MockEngineClient.return_value.get.return_value = {"engine_type": "SMTP", "from_email": "test@test.com", "status": "active"}
    
    MockRecipientResolver.return_value.resolve.return_value = [
        Recipient(email="r1@test.com", name="R1", metadata={})
    ]

    # Execute
    executor = WorkflowExecutor()
    result = await executor.execute_workflow(workflow_id=1, run_id="tpl_fail_test")

    # Assert
    assert result["status"] == "failed"
    assert "Template validation failed" in result["error"]
