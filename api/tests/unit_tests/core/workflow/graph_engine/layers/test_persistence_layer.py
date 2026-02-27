from datetime import datetime
from unittest.mock import MagicMock

from core.app.workflow.layers import PersistenceWorkflowInfo, WorkflowPersistenceLayer
from core.workflow.entities import WorkflowStartReason
from core.workflow.enums import NodeType, SystemVariableKey, WorkflowType
from core.workflow.graph_events import (
    GraphRunStartedEvent,
    GraphRunSucceededEvent,
    NodeRunStartedEvent,
    NodeRunSucceededEvent,
)
from core.workflow.node_events import NodeRunResult
from core.workflow.runtime.node_execution_runtime_store import workflow_node_execution_runtime_store


class _VariablePoolStub:
    def __init__(self, workflow_execution_id: str) -> None:
        self._workflow_execution_id = workflow_execution_id

    def get_by_prefix(self, prefix: str):
        return {
            SystemVariableKey.WORKFLOW_EXECUTION_ID: self._workflow_execution_id,
        }


class _RuntimeStateStub:
    def __init__(self, workflow_execution_id: str) -> None:
        self.variable_pool = _VariablePoolStub(workflow_execution_id)
        self.total_tokens = 0
        self.node_run_steps = 0
        self.outputs = {}
        self.exceptions_count = 0


def test_persistence_layer_buffers_node_executions_until_graph_terminal_event() -> None:
    workflow_node_execution_runtime_store.clear_all()

    workflow_execution_repository = MagicMock()
    workflow_node_execution_repository = MagicMock()
    application_generate_entity = MagicMock()
    application_generate_entity.inputs = {}

    layer = WorkflowPersistenceLayer(
        application_generate_entity=application_generate_entity,
        workflow_info=PersistenceWorkflowInfo(
            workflow_id="workflow-1",
            workflow_type=WorkflowType.WORKFLOW,
            version="draft",
            graph_data={"nodes": [], "edges": []},
        ),
        workflow_execution_repository=workflow_execution_repository,
        workflow_node_execution_repository=workflow_node_execution_repository,
    )
    layer.initialize(
        graph_runtime_state=_RuntimeStateStub("run-1"),
        command_channel=MagicMock(),
    )
    layer.on_graph_start()

    layer.on_event(GraphRunStartedEvent(reason=WorkflowStartReason.INITIAL))

    start_at = datetime.now()
    layer.on_event(
        NodeRunStartedEvent(
            id="exec-1",
            node_id="node-1",
            node_type=NodeType.LLM,
            node_title="Node 1",
            predecessor_node_id=None,
            start_at=start_at,
        )
    )
    assert workflow_node_execution_repository.save.call_count == 0
    assert len(workflow_node_execution_runtime_store.list("run-1")) == 1

    layer.on_event(
        NodeRunSucceededEvent(
            id="exec-1",
            node_id="node-1",
            node_type=NodeType.LLM,
            start_at=start_at,
            node_run_result=NodeRunResult(inputs={"x": 1}, outputs={"y": 2}),
        )
    )
    assert workflow_node_execution_repository.save.call_count == 0
    snapshots = workflow_node_execution_runtime_store.list("run-1")
    assert len(snapshots) == 1
    assert snapshots[0].status == "succeeded"

    layer.on_event(GraphRunSucceededEvent(outputs={"final": "ok"}))

    workflow_node_execution_repository.save_batch.assert_called_once()
    batch_args = workflow_node_execution_repository.save_batch.call_args.args[0]
    assert len(batch_args) == 1
    assert batch_args[0].id == "exec-1"
    assert workflow_node_execution_runtime_store.list("run-1") == []

    # on_graph_end should not flush the same node execution again.
    layer.on_graph_end(None)
    workflow_node_execution_repository.save_batch.assert_called_once()
