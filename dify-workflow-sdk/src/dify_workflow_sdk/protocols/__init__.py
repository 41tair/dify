"""Protocol interfaces for SDK extensibility"""

from .repository import (
    InMemoryWorkflowRepository,
    NodeExecution,
    WorkflowExecution,
    WorkflowRepository,
)
from .storage import FileInfo, FileStorage, InMemoryFileStorage

__all__ = [
    # Repository
    "WorkflowRepository",
    "WorkflowExecution",
    "NodeExecution",
    "InMemoryWorkflowRepository",
    # Storage
    "FileStorage",
    "FileInfo",
    "InMemoryFileStorage",
]