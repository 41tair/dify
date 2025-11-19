"""Base event classes for workflow execution"""

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class BaseEvent(ABC):
    """Base class for all events"""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEngineEvent(BaseEvent):
    """Base class for graph-level events"""
    graph_id: str = ""


@dataclass
class GraphNodeEventBase(BaseEvent):
    """Base class for node-level events"""
    node_id: str = ""
    node_type: str = ""