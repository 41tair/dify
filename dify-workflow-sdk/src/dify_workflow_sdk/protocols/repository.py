"""Repository protocol for data persistence"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class WorkflowExecution:
    """Workflow execution record"""
    execution_id: str
    workflow_id: str
    status: str  # "running", "completed", "failed", "aborted"
    inputs: Dict[str, Any]
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None


@dataclass
class NodeExecution:
    """Node execution record"""
    node_execution_id: str
    execution_id: str
    node_id: str
    node_type: str
    status: str  # "pending", "running", "completed", "failed", "skipped"
    inputs: Dict[str, Any]
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkflowRepository(ABC):
    """Abstract interface for workflow persistence"""

    @abstractmethod
    def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save a workflow execution record"""
        pass

    @abstractmethod
    def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get a workflow execution by ID"""
        pass

    @abstractmethod
    def update_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Update an existing workflow execution"""
        pass

    @abstractmethod
    def list_workflow_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[WorkflowExecution]:
        """List workflow executions with optional filtering"""
        pass

    @abstractmethod
    def save_node_execution(self, node_execution: NodeExecution) -> None:
        """Save a node execution record"""
        pass

    @abstractmethod
    def get_node_executions(self, execution_id: str) -> List[NodeExecution]:
        """Get all node executions for a workflow execution"""
        pass


class InMemoryWorkflowRepository(WorkflowRepository):
    """Simple in-memory repository for testing"""

    def __init__(self):
        self._workflow_executions: Dict[str, WorkflowExecution] = {}
        self._node_executions: Dict[str, List[NodeExecution]] = {}

    def save_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Save a workflow execution to memory"""
        self._workflow_executions[execution.execution_id] = execution
        if execution.execution_id not in self._node_executions:
            self._node_executions[execution.execution_id] = []

    def get_workflow_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """Get a workflow execution from memory"""
        return self._workflow_executions.get(execution_id)

    def update_workflow_execution(self, execution: WorkflowExecution) -> None:
        """Update a workflow execution in memory"""
        self._workflow_executions[execution.execution_id] = execution

    def list_workflow_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[WorkflowExecution]:
        """List workflow executions from memory"""
        executions = list(self._workflow_executions.values())

        # Filter by workflow_id
        if workflow_id:
            executions = [e for e in executions if e.workflow_id == workflow_id]

        # Filter by status
        if status:
            executions = [e for e in executions if e.status == status]

        # Apply limit
        return executions[:limit]

    def save_node_execution(self, node_execution: NodeExecution) -> None:
        """Save a node execution to memory"""
        execution_id = node_execution.execution_id
        if execution_id not in self._node_executions:
            self._node_executions[execution_id] = []
        self._node_executions[execution_id].append(node_execution)

    def get_node_executions(self, execution_id: str) -> List[NodeExecution]:
        """Get node executions from memory"""
        return self._node_executions.get(execution_id, [])