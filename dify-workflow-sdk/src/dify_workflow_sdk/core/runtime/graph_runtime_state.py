"""Runtime state management for workflow execution"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from ..config import WorkflowConfig
from ..events.base import GraphNodeEventBase
from ..graph.graph import Graph
from .variable_pool import VariablePool

logger = logging.getLogger(__name__)


class NodeState(Enum):
    """State of a node during execution"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeExecution:
    """Track execution state of a single node"""
    node_id: str
    state: NodeState = NodeState.PENDING
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retry_count: int = 0


class GraphRuntimeState:
    """
    Manages the runtime state of a workflow graph execution.

    This includes:
    - Node execution states
    - Variable pool for data passing
    - Execution history
    - Error tracking
    """

    def __init__(self, graph: Graph, config: Optional[WorkflowConfig] = None):
        """Initialize runtime state"""
        self.graph = graph
        self.config = config or WorkflowConfig()

        # Node execution tracking
        self.node_executions: Dict[str, NodeExecution] = {}
        self.completed_nodes: Set[str] = set()
        self.failed_nodes: Set[str] = set()
        self.running_nodes: Set[str] = set()

        # Variable pool for data passing between nodes
        self.variable_pool = VariablePool()

        # Execution metrics
        self.total_steps = 0
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        # Error tracking
        self.errors: List[Dict[str, Any]] = []

        # Initialize node execution states
        for node_id in graph.get_all_node_ids():
            self.node_executions[node_id] = NodeExecution(node_id=node_id)

    def set_inputs(self, inputs: Dict[str, Any]) -> None:
        """Set the initial inputs for the workflow"""
        self.variable_pool.set_user_inputs(inputs)

    def get_outputs(self) -> Dict[str, Any]:
        """Get the final outputs from the workflow"""
        outputs = {}

        # Find end nodes and collect their outputs
        for node_id, node in self.graph.nodes.items():
            if node.type == "end":
                execution = self.node_executions.get(node_id)
                if execution and execution.state == NodeState.SUCCEEDED:
                    outputs.update(execution.outputs)

        return outputs

    def get_node_inputs(self, node_id: str) -> Dict[str, Any]:
        """Get inputs for a specific node"""
        inputs = {}

        # Get data from previous nodes through variable pool
        node = self.graph.get_node(node_id)
        if not node:
            return inputs

        # Special handling for start node
        if node.type == "start":
            return self.variable_pool.get_user_inputs()

        # Get inputs from variable mappings in node data
        if "variable_mapping" in node.data:
            for key, selector in node.data["variable_mapping"].items():
                value = self.variable_pool.get(selector)
                if value is not None:
                    inputs[key] = value

        # Get inputs from previous node outputs
        prev_nodes = self.graph.get_previous_nodes(node_id)
        for prev_node in prev_nodes:
            prev_execution = self.node_executions.get(prev_node.id)
            if prev_execution and prev_execution.outputs:
                # Add previous node outputs to variable pool
                for key, value in prev_execution.outputs.items():
                    self.variable_pool.set(f"{prev_node.id}.{key}", value)
                    # Also add to inputs if not already present
                    if key not in inputs:
                        inputs[key] = value

        return inputs

    def set_node_outputs(self, node_id: str, outputs: Dict[str, Any]) -> None:
        """Set outputs for a specific node"""
        execution = self.node_executions.get(node_id)
        if execution:
            execution.outputs = outputs
            execution.state = NodeState.SUCCEEDED
            self.completed_nodes.add(node_id)
            self.running_nodes.discard(node_id)

            # Store outputs in variable pool
            for key, value in outputs.items():
                self.variable_pool.set(f"{node_id}.{key}", value)

    def set_node_error(self, node_id: str, error: str) -> None:
        """Set error for a specific node"""
        execution = self.node_executions.get(node_id)
        if execution:
            execution.error = error
            execution.state = NodeState.FAILED
            self.failed_nodes.add(node_id)
            self.running_nodes.discard(node_id)
            self.errors.append({
                "node_id": node_id,
                "error": error,
            })

    def mark_node_running(self, node_id: str) -> None:
        """Mark a node as running"""
        execution = self.node_executions.get(node_id)
        if execution:
            execution.state = NodeState.RUNNING
            self.running_nodes.add(node_id)
            import time
            execution.start_time = time.time()

    def mark_node_completed(self, node_id: str) -> None:
        """Mark a node as completed"""
        execution = self.node_executions.get(node_id)
        if execution:
            execution.state = NodeState.SUCCEEDED
            self.completed_nodes.add(node_id)
            self.running_nodes.discard(node_id)
            import time
            execution.end_time = time.time()

    def can_execute(self, node_id: str) -> bool:
        """Check if a node can be executed"""
        execution = self.node_executions.get(node_id)
        if not execution:
            return False

        # Already executed or running
        if execution.state in [NodeState.SUCCEEDED, NodeState.RUNNING, NodeState.FAILED]:
            return False

        # Check if all previous nodes have completed
        prev_nodes = self.graph.get_previous_nodes(node_id)
        for prev_node in prev_nodes:
            prev_execution = self.node_executions.get(prev_node.id)
            if not prev_execution or prev_execution.state != NodeState.SUCCEEDED:
                return False

        # Check execution limits
        if self.total_steps >= self.config.max_execution_steps:
            logger.warning(f"Execution step limit reached: {self.config.max_execution_steps}")
            return False

        return True

    def all_nodes_completed(self) -> bool:
        """Check if all nodes have been completed"""
        for execution in self.node_executions.values():
            if execution.state in [NodeState.PENDING, NodeState.RUNNING]:
                return False
        return True

    def has_errors(self) -> bool:
        """Check if any errors occurred during execution"""
        return len(self.errors) > 0 or len(self.failed_nodes) > 0

    def process_event(self, event: GraphNodeEventBase) -> None:
        """Process an event and update runtime state"""
        if hasattr(event, 'node_id'):
            node_id = event.node_id
            event_type = event.__class__.__name__

            if "Started" in event_type:
                self.mark_node_running(node_id)
            elif "Succeeded" in event_type:
                if hasattr(event, 'outputs'):
                    self.set_node_outputs(node_id, event.outputs)
                else:
                    self.mark_node_completed(node_id)
            elif "Failed" in event_type:
                error = getattr(event, 'error', 'Unknown error')
                self.set_node_error(node_id, error)

        self.total_steps += 1

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get a summary of the execution state"""
        return {
            "total_nodes": len(self.node_executions),
            "completed_nodes": len(self.completed_nodes),
            "failed_nodes": len(self.failed_nodes),
            "running_nodes": len(self.running_nodes),
            "total_steps": self.total_steps,
            "has_errors": self.has_errors(),
            "errors": self.errors,
        }