"""High-level workflow engine API"""

import logging
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Union

from ..config import WorkflowConfig
from ..events.base import GraphEngineEvent
from ..graph import Graph
from .graph_engine import GraphEngine
from .command_channel import CommandChannel, InMemoryCommandChannel
from ...parsers.yaml_parser import YAMLParser
from ...protocols.repository import WorkflowRepository, InMemoryWorkflowRepository
from ...protocols.storage import FileStorage, InMemoryFileStorage

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    High-level API for executing workflows.

    This is the main entry point for using the SDK.
    """

    def __init__(
        self,
        workflow: Optional[Union[str, Dict[str, Any], Graph]] = None,
        config: Optional[WorkflowConfig] = None,
        repository: Optional[WorkflowRepository] = None,
        file_storage: Optional[FileStorage] = None,
        command_channel: Optional[CommandChannel] = None,
    ):
        """
        Initialize the workflow engine.

        Args:
            workflow: Can be:
                - Path to YAML file (str)
                - Workflow dictionary
                - Graph object
            config: Workflow configuration
            repository: Optional repository for persisting executions
            file_storage: Optional file storage implementation
            command_channel: Optional command channel for external control
        """
        self.config = config or WorkflowConfig()
        self.repository = repository or InMemoryWorkflowRepository()
        self.file_storage = file_storage or InMemoryFileStorage()
        self.command_channel = command_channel or InMemoryCommandChannel()

        # Load the workflow
        self.graph = self._load_workflow(workflow) if workflow else None
        self._engine: Optional[GraphEngine] = None

    def _load_workflow(self, workflow: Union[str, Dict[str, Any], Graph]) -> Graph:
        """
        Load workflow from various formats.

        Args:
            workflow: Workflow in various formats

        Returns:
            Graph object
        """
        if isinstance(workflow, Graph):
            return workflow

        if isinstance(workflow, str):
            # Assume it's a file path
            path = Path(workflow)
            if path.exists():
                if path.suffix in ['.yml', '.yaml']:
                    workflow_data = YAMLParser.parse_file(str(path))
                    return YAMLParser.workflow_to_graph(workflow_data)
                else:
                    raise ValueError(f"Unsupported file format: {path.suffix}")
            else:
                # Try parsing as YAML string
                try:
                    workflow_data = YAMLParser.parse(workflow)
                    return YAMLParser.workflow_to_graph(workflow_data)
                except Exception:
                    raise ValueError(f"File not found and not valid YAML: {workflow}")

        if isinstance(workflow, dict):
            # Workflow dictionary
            return YAMLParser.workflow_to_graph(workflow)

        raise ValueError(f"Unsupported workflow type: {type(workflow)}")

    def load_workflow(self, workflow: Union[str, Dict[str, Any], Graph]) -> None:
        """
        Load a new workflow.

        Args:
            workflow: Workflow in various formats
        """
        self.graph = self._load_workflow(workflow)
        self._engine = None

    def run(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        stream: bool = True,
    ) -> Generator[GraphEngineEvent, None, None]:
        """
        Execute the workflow.

        Args:
            inputs: Input variables for the workflow
            stream: If True, yield events as they occur

        Yields:
            GraphEngineEvent instances during execution

        Returns:
            Generator of events
        """
        if not self.graph:
            raise RuntimeError("No workflow loaded")

        # Create graph engine
        self._engine = GraphEngine(
            graph=self.graph,
            config=self.config,
            command_channel=self.command_channel,
        )

        # Run the workflow
        yield from self._engine.run(inputs=inputs, stream=stream)

    def run_sync(self, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute the workflow synchronously and return final outputs.

        Args:
            inputs: Input variables for the workflow

        Returns:
            Final workflow outputs
        """
        outputs = {}
        errors = []

        for event in self.run(inputs=inputs, stream=False):
            event_type = event.__class__.__name__

            if "Succeeded" in event_type and hasattr(event, 'outputs'):
                outputs = event.outputs
            elif "Failed" in event_type:
                errors.append(getattr(event, 'error', 'Unknown error'))

        if errors:
            raise RuntimeError(f"Workflow failed: {'; '.join(errors)}")

        return outputs

    def abort(self) -> None:
        """Abort the current workflow execution"""
        if self._engine:
            self._engine.abort()

    def pause(self) -> None:
        """Pause the current workflow execution"""
        if self._engine:
            self._engine.pause()

    def get_input_schema(self) -> Dict[str, Any]:
        """
        Get the input schema for the loaded workflow.

        Returns:
            Dictionary describing input variables
        """
        if not self.graph:
            raise RuntimeError("No workflow loaded")

        schema = {}

        # Find start nodes and extract variables
        for node in self.graph.nodes.values():
            if node.type == "start":
                variables = node.data.get("variables", [])
                for var in variables:
                    var_name = var.get("variable", var.get("label"))
                    if var_name:
                        schema[var_name] = {
                            "type": var.get("type", "string"),
                            "required": var.get("required", False),
                            "default": var.get("default"),
                            "description": var.get("desc", var.get("description", "")),
                        }

        return schema

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        """
        Validate inputs against the workflow schema.

        Args:
            inputs: Input variables to validate

        Returns:
            True if valid, False otherwise
        """
        schema = self.get_input_schema()

        for var_name, var_config in schema.items():
            if var_config.get("required") and var_name not in inputs:
                logger.error(f"Required input '{var_name}' not provided")
                return False

            if var_name in inputs:
                value = inputs[var_name]
                expected_type = var_config.get("type", "string")

                # Basic type validation
                if expected_type == "integer" and not isinstance(value, int):
                    try:
                        int(value)
                    except (TypeError, ValueError):
                        logger.error(f"Input '{var_name}' cannot be converted to integer")
                        return False
                elif expected_type == "float" and not isinstance(value, (int, float)):
                    try:
                        float(value)
                    except (TypeError, ValueError):
                        logger.error(f"Input '{var_name}' cannot be converted to float")
                        return False
                elif expected_type == "boolean" and not isinstance(value, bool):
                    if not isinstance(value, str) or value.lower() not in ("true", "false", "yes", "no", "1", "0"):
                        logger.error(f"Input '{var_name}' is not a valid boolean")
                        return False

        return True

    @classmethod
    def from_yaml_file(cls, file_path: str, **kwargs) -> "WorkflowEngine":
        """
        Create a WorkflowEngine from a YAML file.

        Args:
            file_path: Path to YAML file
            **kwargs: Additional arguments for WorkflowEngine

        Returns:
            WorkflowEngine instance
        """
        return cls(workflow=file_path, **kwargs)

    @classmethod
    def from_yaml_string(cls, yaml_content: str, **kwargs) -> "WorkflowEngine":
        """
        Create a WorkflowEngine from a YAML string.

        Args:
            yaml_content: YAML string content
            **kwargs: Additional arguments for WorkflowEngine

        Returns:
            WorkflowEngine instance
        """
        workflow_data = YAMLParser.parse(yaml_content)
        return cls(workflow=workflow_data, **kwargs)