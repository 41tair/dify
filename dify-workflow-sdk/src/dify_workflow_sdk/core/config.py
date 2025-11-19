"""Workflow configuration"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class WorkflowConfig:
    """Configuration for workflow execution"""

    # Execution limits
    max_execution_steps: int = 500
    max_execution_time: float = 1200.0  # 20 minutes
    max_call_depth: int = 5

    # Node execution
    code_execution_timeout: int = 30  # seconds
    http_request_timeout: int = 30  # seconds

    # Engine settings
    debug: bool = False
    enable_parallel_execution: bool = True

    # Variable settings
    max_variable_size: int = 1024 * 1024  # 1MB

    # Iteration limits
    max_iteration_steps: int = 1000
    max_iteration_parallel_jobs: int = 10

    # Custom settings
    custom_settings: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate configuration values"""
        if self.max_execution_steps <= 0:
            raise ValueError("max_execution_steps must be positive")
        if self.max_execution_time <= 0:
            raise ValueError("max_execution_time must be positive")
        if self.max_call_depth <= 0:
            raise ValueError("max_call_depth must be positive")
        if self.code_execution_timeout <= 0:
            raise ValueError("code_execution_timeout must be positive")