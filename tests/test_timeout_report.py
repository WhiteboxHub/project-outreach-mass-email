"""
tests/test_timeout_report.py
────────────────────────────
Verifies our two fixes:
  1. send_run_report is called even when the executor times out.
  2. ScheduleRunner passes timeout_seconds=7200 to execute_workflow.
"""
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from models.recipient import Recipient


# ─────────────────────────────────────────────────────────────────────────────
# Fix 1: send_run_report must fire even on TIMED_OUT
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("executor.workflow_executor.send_run_report")
@patch("executor.workflow_executor.asyncio.sleep", new_callable=lambda: lambda *a, **kw: AsyncMock())
@patch("executor.workflow_executor.WorkflowClient")
@patch("executor.workflow_executor.TemplateClient")
@patch("executor.workflow_executor.DeliveryEngineClient")
@patch("executor.workflow_executor.LogClient")
@patch("executor.workflow_executor.RecipientResolver")
@patch("executor.workflow_executor.EngineBuilder")
async def test_send_report_on_timeout(
    MockEngineBuilder, MockRecipientResolver, MockLogClient,
    MockEngineClient, MockTemplateClient, MockWorkflowClient,
    mock_sleep,
    mock_send_report,
):
    """
    When timeout_seconds=0, the deadline is already passed by the time
    the post-send check runs. The executor must still call send_run_report
    with final_status='timed_out'.
    """
    from executor.workflow_executor import WorkflowExecutor

    # --- workflow stub ---
    MockWorkflowClient.return_value.get.return_value = {
        "id": 1,
        "name": "Daily Outreach",
        "email_template_id": 1,
        "delivery_engine_id": 1,
        "recipient_list_sql": "SELECT ...",
        "parameters_config": None,
    }
    MockTemplateClient.return_value.get.return_value = {
        "subject": "Hi there",
        "content_html": "Hello!",
    }
    MockEngineClient.return_value.get.return_value = {
        "engine_type": "SMTP",
        "from_email": "test@test.com",
        "rate_limit_per_minute": 6000,
        "batch_size": 10,
        "status": "active",
    }

    # One valid recipient
    MockRecipientResolver.return_value.resolve.return_value = (
        [Recipient(email="vendor@example.com", name="V", metadata={})],
        [],
    )

    # Sender succeeds immediately
    mock_sender = MockEngineBuilder.build.return_value
    mock_sender.send = AsyncMock(return_value=True)

    # Log client returns a valid log id
    MockLogClient.return_value.create.return_value = 42
    MockLogClient.return_value.update.return_value = None

    executor = WorkflowExecutor()

    # timeout_seconds=0 → deadline = start_time → any real elapsed time > deadline
    result = await executor.execute_workflow(
        workflow_id=1,
        run_id="timeout_test",
        schedule_id=99,
        timeout_seconds=0,
    )

    # --- Assertions ---
    assert result["status"] == "timed_out", f"Expected timed_out, got: {result}"

    # send_run_report MUST have been called
    assert mock_send_report.called, "send_run_report was NOT called on timeout!"

    call_kwargs = mock_send_report.call_args.kwargs
    assert call_kwargs.get("final_status") == "timed_out", (
        f"Expected final_status='timed_out', got {call_kwargs.get('final_status')}"
    )
    assert call_kwargs.get("schedule_id") == 99

    print(f"\n[PASS] send_run_report called on timeout with: {call_kwargs}")


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2: ScheduleRunner must pass timeout_seconds=7200 to execute_workflow
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("scheduler.schedule_runner.ScheduleClient")
@patch("scheduler.schedule_runner.WorkflowClient")
@patch("scheduler.schedule_runner.WorkflowExecutor")
async def test_schedule_runner_passes_7200_timeout(
    MockExecutor, MockWorkflowClient, MockScheduleClient
):
    """
    For a daily_vendor_outreach schedule, execute_workflow must be called
    with timeout_seconds=7200.
    """
    from scheduler.schedule_runner import ScheduleRunner

    # --- schedule stub (daily_vendor_outreach) ---
    MockScheduleClient.return_value.get.return_value = {
        "id": 5,
        "status": "active",
        "workflow_id": 10,
        "workflow_key": "daily_vendor_outreach",
        "run_parameters": {"trigger_type": "daily"},
        "next_run_at": "2023-01-01T00:00:00",
        "frequency": "daily",
        "is_running": False,
    }
    MockScheduleClient.return_value.lock_schedule.return_value = True
    MockScheduleClient.return_value.update.return_value = None

    # --- workflow stub ---
    MockWorkflowClient.return_value.get.return_value = {
        "id": 10,
        "recipient_list_sql": "SELECT id, email as vendor_email FROM outreach_emails",
        "email_template_id": 1,
        "delivery_engine_id": 1,
    }
    MockWorkflowClient.return_value.execute_sql.return_value = [
        {"id": 1, "vendor_email": "a@b.com"}
    ]

    # execute_workflow mock — just return success
    mock_execute = AsyncMock(return_value={"status": "success", "processed": 1, "failed": 0})
    MockExecutor.return_value.execute_workflow = mock_execute

    # patch _load_candidates and _update_candidate_metrics so they don't hit DB
    runner = ScheduleRunner()
    runner._update_candidate_metrics = MagicMock()

    primary = {
        "id": 7, "full_name": "Alice", "email": "alice@test.com",
        "run_daily_workflow": True, "daily_outreach_limit": 5,
        "max_outreach_limit": 500, "total_outreach_count": 0, "fcount": 0,
    }
    with patch.object(runner, "_load_candidates", new=AsyncMock(return_value=[primary])):
        with patch.object(runner.workflow_executor.engine_client, "get_candidate_credentials",
                          return_value={"email": "alice@test.com", "candidate_name": "Alice",
                                        "imap_password": "pw", "password": None}):
            await runner.run_schedule(schedule_id=5)

    # Check that execute_workflow was called with timeout_seconds=7200
    assert mock_execute.called, "execute_workflow was never called"

    call_kwargs = mock_execute.call_args.kwargs
    timeout = call_kwargs.get("timeout_seconds")
    assert timeout == 7200, f"Expected timeout_seconds=7200, got {timeout}"

    print(f"\n[PASS] execute_workflow called with timeout_seconds={timeout}")
