"""Node-level events for workflow execution"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import GraphNodeEventBase


@dataclass
class NodeRunStartedEvent(GraphNodeEventBase):
    """Emitted when a node execution starts"""
    node_data: Dict[str, Any] = field(default_factory=dict)
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeRunSucceededEvent(GraphNodeEventBase):
    """Emitted when a node execution succeeds"""
    outputs: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0


@dataclass
class NodeRunFailedEvent(GraphNodeEventBase):
    """Emitted when a node execution fails"""
    error: str = ""
    error_details: Optional[Dict[str, Any]] = None
    can_retry: bool = False


@dataclass
class NodeRunStreamChunkEvent(GraphNodeEventBase):
    """Emitted for streaming output from a node"""
    chunk: str = ""
    chunk_index: int = 0
    is_final: bool = False