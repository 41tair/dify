from datetime import datetime, timedelta

from core.workflow.runtime.node_execution_runtime_store import (
    NodeExecutionRuntimeSnapshot,
    workflow_node_execution_runtime_store,
)


def test_runtime_store_upsert_and_ordered_list() -> None:
    workflow_node_execution_runtime_store.clear_all()

    now = datetime.now()
    workflow_node_execution_runtime_store.upsert(
        workflow_run_id="run-1",
        snapshot=NodeExecutionRuntimeSnapshot(
            execution_id="exec-2",
            node_id="node-2",
            node_type="llm",
            title="node-2",
            index=2,
            status="running",
            elapsed_time=0.2,
            created_at=now + timedelta(seconds=1),
            finished_at=None,
        ),
    )
    workflow_node_execution_runtime_store.upsert(
        workflow_run_id="run-1",
        snapshot=NodeExecutionRuntimeSnapshot(
            execution_id="exec-1",
            node_id="node-1",
            node_type="start",
            title="node-1",
            index=1,
            status="succeeded",
            elapsed_time=0.1,
            created_at=now,
            finished_at=now + timedelta(seconds=1),
        ),
    )

    snapshots = workflow_node_execution_runtime_store.list("run-1")
    assert [snapshot.execution_id for snapshot in snapshots] == ["exec-1", "exec-2"]


def test_runtime_store_clear() -> None:
    workflow_node_execution_runtime_store.clear_all()

    workflow_node_execution_runtime_store.upsert(
        workflow_run_id="run-2",
        snapshot=NodeExecutionRuntimeSnapshot(
            execution_id="exec-1",
            node_id="node-1",
            node_type="start",
            title="node-1",
            index=1,
            status="running",
            elapsed_time=0.0,
            created_at=datetime.now(),
            finished_at=None,
        ),
    )
    assert len(workflow_node_execution_runtime_store.list("run-2")) == 1

    workflow_node_execution_runtime_store.clear("run-2")
    assert workflow_node_execution_runtime_store.list("run-2") == []
