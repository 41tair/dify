"""Simplified Graph Engine for standalone workflow execution"""

import contextvars
import logging
import queue
import threading
from collections.abc import Generator
from typing import Any, Dict, Optional, cast

from ..config import WorkflowConfig
from ..events.base import GraphEngineEvent, GraphNodeEventBase
from ..events.graph_events import (
    GraphRunAbortedEvent,
    GraphRunFailedEvent,
    GraphRunStartedEvent,
    GraphRunSucceededEvent,
)
from ..graph.graph import Graph
from ..runtime.graph_runtime_state import GraphRuntimeState
from .command_channel import CommandChannel, InMemoryCommandChannel
from .dispatcher import Dispatcher
from .worker import Worker

logger = logging.getLogger(__name__)


class GraphEngine:
    """
    Simplified queue-based graph execution engine.

    This is a standalone version extracted from Dify's workflow engine,
    with minimal dependencies and focused on core workflow execution.
    """

    def __init__(
        self,
        graph: Graph,
        config: Optional[WorkflowConfig] = None,
        command_channel: Optional[CommandChannel] = None,
    ) -> None:
        """Initialize the graph engine."""
        self._graph = graph
        self._config = config or WorkflowConfig()
        self._command_channel = command_channel or InMemoryCommandChannel()

        # Runtime state management
        self._graph_runtime_state = GraphRuntimeState(
            graph=graph,
            config=self._config,
        )

        # Execution queues
        self._ready_queue: queue.Queue[str] = queue.Queue()  # Node IDs ready to execute
        self._event_queue: queue.Queue[GraphNodeEventBase] = queue.Queue()

        # Execution state
        self._is_running = False
        self._execution_thread: Optional[threading.Thread] = None
        self._workers: list[Worker] = []

        # Context variables for worker threads
        self._context_vars = contextvars.copy_context()

        # Event collection
        self._events: list[GraphEngineEvent] = []

    def run(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        stream: bool = True,
    ) -> Generator[GraphEngineEvent, None, None]:
        """
        Execute the workflow graph.

        Args:
            inputs: Input variables for the workflow
            stream: If True, yield events as they occur. If False, collect all events.

        Yields:
            GraphEngineEvent instances during execution
        """
        if self._is_running:
            raise RuntimeError("Graph engine is already running")

        self._is_running = True
        self._events.clear()

        # Initialize runtime state with inputs
        if inputs:
            self._graph_runtime_state.set_inputs(inputs)

        # Emit start event
        start_event = GraphRunStartedEvent(
            graph_id=self._graph.graph_id,
            inputs=inputs or {},
        )
        if stream:
            yield start_event
        else:
            self._events.append(start_event)

        try:
            # Initialize execution by adding start node to ready queue
            start_node = self._graph.get_start_node()
            if start_node:
                self._ready_queue.put(start_node.id)

            # Start worker threads
            self._start_workers()

            # Main execution loop
            while self._is_running:
                # Check for commands (abort, pause, etc.)
                command = self._command_channel.get(timeout=0.1)
                if command:
                    self._handle_command(command)

                # Process events from workers
                try:
                    event = self._event_queue.get(timeout=0.1)

                    # Process the event
                    self._process_event(event)

                    # Yield or collect the event
                    if stream:
                        yield event
                    else:
                        self._events.append(event)

                    # Check if execution is complete
                    if self._is_execution_complete():
                        break

                except queue.Empty:
                    # No events available, continue
                    pass

                except Exception as e:
                    logger.error(f"Error processing event: {e}")
                    error_event = GraphRunFailedEvent(
                        graph_id=self._graph.graph_id,
                        error=str(e),
                    )
                    if stream:
                        yield error_event
                    else:
                        self._events.append(error_event)
                    break

            # Emit success event if completed normally
            if self._is_execution_complete() and not self._has_errors():
                outputs = self._graph_runtime_state.get_outputs()
                success_event = GraphRunSucceededEvent(
                    graph_id=self._graph.graph_id,
                    outputs=outputs,
                )
                if stream:
                    yield success_event
                else:
                    self._events.append(success_event)

        except Exception as e:
            logger.error(f"Graph execution failed: {e}")
            error_event = GraphRunFailedEvent(
                graph_id=self._graph.graph_id,
                error=str(e),
            )
            if stream:
                yield error_event
            else:
                self._events.append(error_event)

        finally:
            self._stop_workers()
            self._is_running = False

        # Return collected events if not streaming
        if not stream:
            for event in self._events:
                yield event

    def _start_workers(self) -> None:
        """Start worker threads for node execution."""
        # Start with a small number of workers
        num_workers = min(4, self._config.max_execution_steps)

        for i in range(num_workers):
            worker = Worker(
                worker_id=f"worker-{i}",
                ready_queue=self._ready_queue,
                event_queue=self._event_queue,
                graph=self._graph,
                graph_runtime_state=self._graph_runtime_state,
                context_vars=self._context_vars,
            )
            worker.start()
            self._workers.append(worker)

    def _stop_workers(self) -> None:
        """Stop all worker threads."""
        for worker in self._workers:
            worker.stop()

        # Wait for workers to finish
        for worker in self._workers:
            worker.join(timeout=5.0)

        self._workers.clear()

    def _process_event(self, event: GraphNodeEventBase) -> None:
        """Process an event from a worker."""
        # Update runtime state based on event
        self._graph_runtime_state.process_event(event)

        # Determine next nodes to execute based on the event
        if hasattr(event, 'node_id'):
            next_nodes = self._graph.get_next_nodes(event.node_id)
            for node in next_nodes:
                if self._graph_runtime_state.can_execute(node.id):
                    self._ready_queue.put(node.id)

    def _handle_command(self, command: Any) -> None:
        """Handle external commands like abort or pause."""
        if command.type == "abort":
            self._abort_execution()
        elif command.type == "pause":
            self._pause_execution()

    def _abort_execution(self) -> None:
        """Abort the current execution."""
        self._is_running = False
        abort_event = GraphRunAbortedEvent(
            graph_id=self._graph.graph_id,
            reason="User requested abort",
        )
        self._event_queue.put(abort_event)

    def _pause_execution(self) -> None:
        """Pause the current execution."""
        # Implementation depends on requirements
        pass

    def _is_execution_complete(self) -> bool:
        """Check if the workflow execution is complete."""
        return (
            self._ready_queue.empty() and
            self._graph_runtime_state.all_nodes_completed() and
            not any(worker.is_busy() for worker in self._workers)
        )

    def _has_errors(self) -> bool:
        """Check if any errors occurred during execution."""
        return self._graph_runtime_state.has_errors()

    def abort(self) -> None:
        """Abort the current execution from external caller."""
        self._command_channel.send({"type": "abort"})

    def pause(self) -> None:
        """Pause the current execution from external caller."""
        self._command_channel.send({"type": "pause"})