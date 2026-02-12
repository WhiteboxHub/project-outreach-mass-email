import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
from scheduler.schedule_runner import ScheduleRunner
from scheduler.scheduler_loop import SchedulerLoop

@pytest.mark.asyncio
@patch("scheduler.schedule_runner.WorkflowExecutor")
@patch("scheduler.schedule_runner.ScheduleClient")
@patch("scheduler.schedule_runner.WorkflowClient")
async def test_schedule_runner(MockWorkflowClient, MockScheduleClient, MockExecutor):
    # Setup
    runner = ScheduleRunner()
    
    # Mock Schedule
    MockScheduleClient.return_value.get.return_value = {
        "id": 1, "status": "active", "workflow_id": 101, "next_run_at": "2023-01-01T00:00:00"
    }
    
    # Mock Executor
    mock_execute = MockExecutor.return_value.execute_workflow
    mock_execute = AsyncMock(return_value={"status": "success"})
    MockExecutor.return_value.execute_workflow = mock_execute

    # Run
    await runner.run_schedule(1)
    
    # Assert
    # Verify execute_workflow called
    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[1]
    assert call_args["workflow_id"] == 101
    assert "run_id" in call_args
    
    # Verify schedule update
    MockScheduleClient.return_value.update.assert_called_once()


@pytest.mark.asyncio
@patch("scheduler.scheduler_loop.ScheduleClient")
@patch("scheduler.scheduler_loop.ScheduleRunner")
async def test_scheduler_loop(MockRunner, MockScheduleClient):
    # Setup
    # Create a loop with very short interval
    loop = SchedulerLoop(interval_seconds=0.1)
    
    # Mock Schedules
    # One due, one future
    due_time = (datetime.now() - timedelta(hours=1)).isoformat()
    future_time = (datetime.now() + timedelta(hours=1)).isoformat()
    
    MockScheduleClient.return_value.list.return_value = [
        {"id": 1, "status": "active", "next_run_at": due_time},
        {"id": 2, "status": "active", "next_run_at": future_time}
    ]
    
    # Mock Runner
    MockRunner.return_value.run_schedule = AsyncMock()
    
    # Run loop for one tick
    await loop._tick()
    
    # Assert
    # Should run schedule 1 but not 2
    MockRunner.return_value.run_schedule.assert_called_with(1)
    assert MockRunner.return_value.run_schedule.call_count == 1
