"""Worker thread for executing workflow nodes"""

import contextvars
import logging
import queue
import threading
import time
from typing import Any, Optional

from ..events.node_events import (
    NodeRunFailedEvent,
    NodeRunStartedEvent,
    NodeRunSucceededEvent,
)
from ..graph.graph import Graph
from ..runtime.graph_runtime_state import GraphRuntimeState

logger = logging.getLogger(__name__)


class Worker(threading.Thread):
    """Worker thread that executes nodes from the ready queue"""

    def __init__(
        self,
        worker_id: str,
        ready_queue: queue.Queue[str],
        event_queue: queue.Queue[Any],
        graph: Graph,
        graph_runtime_state: GraphRuntimeState,
        context_vars: contextvars.Context,
    ) -> None:
        """Initialize worker thread"""
        super().__init__(name=f"WorkflowWorker-{worker_id}")
        self.worker_id = worker_id
        self._ready_queue = ready_queue
        self._event_queue = event_queue
        self._graph = graph
        self._graph_runtime_state = graph_runtime_state
        self._context_vars = context_vars

        self._stop_event = threading.Event()
        self._is_busy = False

    def run(self) -> None:
        """Main worker loop"""
        logger.debug(f"Worker {self.worker_id} started")

        # Run in the captured context
        for item in self._context_vars:
            pass  # Context is automatically applied

        while not self._stop_event.is_set():
            try:
                # Get next node to execute
                node_id = self._ready_queue.get(timeout=0.5)

                # Mark as busy
                self._is_busy = True

                # Execute the node
                self._execute_node(node_id)

                # Mark task as done
                self._ready_queue.task_done()

            except queue.Empty:
                # No work available, continue waiting
                continue

            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}", exc_info=True)

            finally:
                self._is_busy = False

        logger.debug(f"Worker {self.worker_id} stopped")

    def _execute_node(self, node_id: str) -> None:
        """Execute a single node"""
        try:
            # Get the node from the graph
            node = self._graph.get_node(node_id)
            if not node:
                logger.error(f"Node {node_id} not found in graph")
                return

            # Emit node started event
            start_event = NodeRunStartedEvent(
                node_id=node_id,
                node_type=node.type,
                node_data=node.data,
            )
            self._event_queue.put(start_event)

            # Get node inputs from runtime state
            inputs = self._graph_runtime_state.get_node_inputs(node_id)

            # Create node instance and execute
            node_instance = self._create_node_instance(node)
            if node_instance:
                # Execute the node
                result = node_instance.run(inputs)

                # Extract outputs from result
                if hasattr(result, 'outputs'):
                    outputs = result.outputs
                elif isinstance(result, dict):
                    outputs = result
                else:
                    outputs = {}

                # Store outputs in runtime state
                self._graph_runtime_state.set_node_outputs(node_id, outputs)

                # Emit success event
                success_event = NodeRunSucceededEvent(
                    node_id=node_id,
                    node_type=node.type,
                    outputs=outputs,
                )
                self._event_queue.put(success_event)

            else:
                # Node type not implemented, skip with warning
                logger.warning(f"Node type {node.type} not implemented, skipping node {node_id}")
                success_event = NodeRunSucceededEvent(
                    node_id=node_id,
                    node_type=node.type,
                    outputs={},
                )
                self._event_queue.put(success_event)

        except Exception as e:
            logger.error(f"Error executing node {node_id}: {e}", exc_info=True)
            error_event = NodeRunFailedEvent(
                node_id=node_id,
                node_type=node.type if node else "unknown",
                error=str(e),
            )
            self._event_queue.put(error_event)

    def _create_node_instance(self, node: Any) -> Optional[Any]:
        """Create an instance of the node for execution"""
        from ...nodes.builtin import get_node_class

        # Get the node class based on type
        node_class = get_node_class(node.type)
        if not node_class:
            return None

        # Create and return node instance
        return node_class(
            node_id=node.id,
            node_data=node.data,
            variable_pool=self._graph_runtime_state.variable_pool,
        )

    def stop(self) -> None:
        """Signal the worker to stop"""
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the worker to finish"""
        super().join(timeout)

    def is_busy(self) -> bool:
        """Check if the worker is currently executing a node"""
        return self._is_busy