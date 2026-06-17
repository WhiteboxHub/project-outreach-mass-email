import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from utils.report_mailer import _build_combined_html, send_combined_run_report
from scheduler.schedule_runner import ScheduleRunner


def test_build_combined_html():
    reports = [
        {
            "run_id": "run_1",
            "final_status": "success",
            "success_count": 5,
            "failed_count": 0,
            "started_at": datetime(2026, 6, 17, 3, 0, 0),
            "finished_at": datetime(2026, 6, 17, 3, 5, 0),
            "recipient_results": [
                {"email": "v1@test.com", "status": "success"},
                {"email": "v2@test.com", "status": "skipped", "reason": "invalid email"}
            ],
            "execution_context": {
                "candidate_name": "Ramadevi Sunkavalli",
                "candidate_email": "ramaadevisunkavalli@gmail.com",
                "primary_candidate": "Ramadevi Sunkavalli (ramaadevisunkavalli@gmail.com)",
                "backup_candidates": "Ayesha Tafheem (ayshatafhim@gmail.com)"
            },
            "error_summary": None
        },
        {
            "run_id": "run_2",
            "final_status": "failed",
            "success_count": 0,
            "failed_count": 3,
            "started_at": datetime(2026, 6, 17, 3, 5, 0),
            "finished_at": datetime(2026, 6, 17, 3, 10, 0),
            "recipient_results": [
                {"email": "v3@test.com", "status": "failed", "error": "SMTP failed"}
            ],
            "execution_context": {
                "candidate_name": "Ayesha Tafheem",
                "candidate_email": "ayshatafhim@gmail.com",
                "primary_candidate": "Ramadevi Sunkavalli (ramaadevisunkavalli@gmail.com)",
                "backup_candidates": "Ayesha Tafheem (ayshatafhim@gmail.com)"
            },
            "error_summary": "Some recipients failed"
        }
    ]

    html = _build_combined_html(
        workflow_name="Daily Vendor Outreach",
        schedule_id=1,
        reports=reports
    )

    assert "Daily Vendor Outreach" in html
    assert "Consolidated Report" in html
    assert "Ramadevi Sunkavalli" in html
    assert "Ayesha Tafheem" in html
    # Check aggregate KPIs: 5 sent, 3 failed, 1 skipped -> 9 total fetched
    assert "5" in html  # ok count
    assert "3" in html  # fail count
    assert "1" in html  # skip count
    assert "9" in html  # total fetched


@patch("utils.report_mailer.smtplib.SMTP")
@patch("utils.report_mailer.os.getenv")
def test_send_combined_run_report(mock_getenv, mock_smtp):
    # Setup environment mocks
    env_vars = {
        "REPORT_EMAIL_TO": "admin@test.com",
        "REPORT_EMAIL_FROM": "wbl@test.com",
        "REPORT_SMTP_HOST": "smtp.test.com",
        "REPORT_SMTP_PORT": "587",
        "REPORT_SMTP_USER": "user",
        "REPORT_SMTP_PASSWORD": "pw"
    }
    mock_getenv.side_effect = lambda k, default=None: env_vars.get(k, default)

    reports = [
        {
            "run_id": "run_1",
            "final_status": "success",
            "success_count": 1,
            "failed_count": 0,
            "started_at": datetime.now(),
            "finished_at": datetime.now(),
            "recipient_results": [],
            "execution_context": {},
            "error_summary": None
        }
    ]

    # SMTP context manager mock
    smtp_instance = MagicMock()
    mock_smtp.return_value.__enter__.return_value = smtp_instance

    success = send_combined_run_report(
        workflow_name="Outreach Workflow",
        schedule_id=42,
        reports=reports
    )

    assert success
    mock_smtp.assert_called_once_with("smtp.test.com", 587, timeout=30)
    smtp_instance.login.assert_called_once_with("user", "pw")
    smtp_instance.sendmail.assert_called_once()


@pytest.mark.asyncio
@patch("scheduler.schedule_runner.ScheduleClient")
@patch("scheduler.schedule_runner.WorkflowClient")
@patch("scheduler.schedule_runner.WorkflowExecutor")
@patch("utils.report_mailer.send_combined_run_report")
async def test_schedule_runner_consolidated_report(
    mock_send_combined, MockExecutor, MockWorkflowClient, MockScheduleClient
):
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

    MockWorkflowClient.return_value.get.return_value = {
        "id": 10,
        "name": "Daily Outreach Workflow",
        "recipient_list_sql": "SELECT ...",
        "email_template_id": 1,
        "delivery_engine_id": 1,
    }
    MockWorkflowClient.return_value.execute_sql.return_value = [
        {"id": 1, "vendor_email": "v1@test.com"},
        {"id": 2, "vendor_email": "v2@test.com"}
    ]

    # Executor returns success result with report_data
    mock_report_data = {
        "run_id": "run_5_7",
        "final_status": "success",
        "success_count": 2,
        "failed_count": 0,
        "started_at": datetime.now(),
        "finished_at": datetime.now(),
        "recipient_results": [],
        "execution_context": {"primary_candidate": "Alice", "backup_candidates": "None"},
        "error_summary": None
    }
    mock_execute = AsyncMock(return_value={
        "status": "success",
        "processed": 2,
        "failed": 0,
        "report_data": mock_report_data
    })
    MockExecutor.return_value.execute_workflow = mock_execute

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

    # Verify send_report=False was passed to execute_workflow
    assert mock_execute.called
    call_kwargs = mock_execute.call_args.kwargs
    assert call_kwargs.get("send_report") is False

    # Verify send_combined_run_report was called
    mock_send_combined.assert_called_once_with(
        workflow_name="Daily Outreach Workflow",
        schedule_id=5,
        reports=[mock_report_data]
    )
