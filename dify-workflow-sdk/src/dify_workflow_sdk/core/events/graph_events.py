"""Graph-level events for workflow execution"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import GraphEngineEvent


@dataclass
class GraphRunStartedEvent(GraphEngineEvent):
    """Emitted when a graph run starts"""
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphRunSucceededEvent(GraphEngineEvent):
    """Emitted when a graph run completes successfully"""
    outputs: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0


@dataclass
class GraphRunFailedEvent(GraphEngineEvent):
    """Emitted when a graph run fails"""
    error: str = ""
    error_details: Optional[Dict[str, Any]] = None


@dataclass
class GraphRunAbortedEvent(GraphEngineEvent):
    """Emitted when a graph run is aborted"""
    reason: str = ""


@dataclass
class GraphRunPausedEvent(GraphEngineEvent):
    """Emitted when a graph run is paused"""
    reason: str = ""
    can_resume: bool = True