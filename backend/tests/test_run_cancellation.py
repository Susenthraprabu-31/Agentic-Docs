from app.queue.run_cancellation import (
    RunCancelledError,
    check_run_cancelled,
    clear_run_cancelled,
    is_run_cancelled,
    mark_run_cancelled,
)


def test_run_cancellation_flags():
    run_id = "test-run-123"
    assert not is_run_cancelled(run_id)
    mark_run_cancelled(run_id)
    assert is_run_cancelled(run_id)
    try:
        check_run_cancelled(run_id)
        raised = False
    except RunCancelledError:
        raised = True
    assert raised
    clear_run_cancelled(run_id)
    assert not is_run_cancelled(run_id)
