"""Base node class for workflow nodes"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Generator, Optional, Union

from ...core.events.node_events import NodeRunStreamChunkEvent
from ...core.runtime.variable_pool import VariablePool


@dataclass
class NodeRunResult:
    """Result from running a node"""
    outputs: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


NodeOutput = Union[NodeRunResult, Generator[NodeRunStreamChunkEvent, None, NodeRunResult]]


class BaseNode(ABC):
    """
    Base class for all workflow nodes.

    Each node type should inherit from this class and implement the _run method.
    """

    def __init__(
        self,
        node_id: str,
        node_data: Dict[str, Any],
        variable_pool: Optional[VariablePool] = None,
    ):
        """
        Initialize the node.

        Args:
            node_id: Unique identifier for this node instance
            node_data: Node configuration data from the workflow definition
            variable_pool: Variable pool for accessing workflow variables
        """
        self.node_id = node_id
        self.node_data = node_data
        self.variable_pool = variable_pool or VariablePool()
        self.node_type = self._get_node_type()

    @classmethod
    def _get_node_type(cls) -> str:
        """Get the node type identifier"""
        # Default implementation uses class name
        return cls.__name__.lower().replace("node", "")

    def run(self, inputs: Dict[str, Any]) -> NodeOutput:
        """
        Execute the node.

        Args:
            inputs: Input data for the node

        Returns:
            NodeRunResult or generator of events
        """
        # Validate inputs
        self._validate_inputs(inputs)

        # Run the node implementation
        return self._run(inputs)

    @abstractmethod
    def _run(self, inputs: Dict[str, Any]) -> NodeOutput:
        """
        Internal implementation of node execution.

        This method should be implemented by each node type.

        Args:
            inputs: Validated input data

        Returns:
            NodeRunResult or generator of events
        """
        pass

    def _validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """
        Validate node inputs.

        Override this method to add custom validation.

        Args:
            inputs: Input data to validate

        Raises:
            ValueError: If inputs are invalid
        """
        # Default implementation does no validation
        pass

    def get_variable(self, selector: str) -> Any:
        """
        Get a variable from the variable pool.

        Args:
            selector: Variable selector (e.g., "node_id.variable_name")

        Returns:
            Variable value or None if not found
        """
        return self.variable_pool.get(selector)

    def set_variable(self, selector: str, value: Any) -> None:
        """
        Set a variable in the variable pool.

        Args:
            selector: Variable selector (e.g., "node_id.variable_name")
            value: Value to set
        """
        self.variable_pool.set(selector, value)

    def resolve_template(self, template: str) -> str:
        """
        Resolve variable references in a template string.

        Args:
            template: Template string with variable references

        Returns:
            Resolved string
        """
        return self.variable_pool.resolve_template(template)


class SimpleNode(BaseNode):
    """
    Simple node implementation for nodes that don't need streaming output.

    Subclasses should implement the execute method instead of _run.
    """

    def _run(self, inputs: Dict[str, Any]) -> NodeRunResult:
        """Run the node and return result"""
        outputs = self.execute(inputs)
        return NodeRunResult(outputs=outputs)

    @abstractmethod
    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the node logic.

        Args:
            inputs: Input data

        Returns:
            Output dictionary
        """
        pass


class StreamingNode(BaseNode):
    """
    Base class for nodes that support streaming output.

    Subclasses should implement the stream method.
    """

    def _run(self, inputs: Dict[str, Any]) -> Generator[NodeRunStreamChunkEvent, None, NodeRunResult]:
        """Run the node with streaming output"""
        # Stream chunks
        outputs = {}
        chunk_index = 0

        for chunk, is_final in self.stream(inputs):
            if isinstance(chunk, str):
                # Emit stream chunk event
                yield NodeRunStreamChunkEvent(
                    node_id=self.node_id,
                    node_type=self.node_type,
                    chunk=chunk,
                    chunk_index=chunk_index,
                    is_final=is_final,
                )
                chunk_index += 1

                # Accumulate output
                if "content" not in outputs:
                    outputs["content"] = ""
                outputs["content"] += chunk
            else:
                # Non-string chunk, add to outputs
                outputs.update(chunk)

        # Return final result
        return NodeRunResult(outputs=outputs)

    @abstractmethod
    def stream(self, inputs: Dict[str, Any]) -> Generator[tuple[Union[str, Dict], bool], None, None]:
        """
        Stream output from the node.

        Args:
            inputs: Input data

        Yields:
            Tuple of (chunk, is_final) where chunk is either a string or dict
        """
        pass