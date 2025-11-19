"""Event dispatcher for workflow execution"""

import logging
import queue
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Dispatcher:
    """Dispatches events during workflow execution"""

    def __init__(
        self,
        event_queue: queue.Queue[Any],
        execution_timeout: float = 1200.0,  # 20 minutes default
    ) -> None:
        """Initialize the dispatcher"""
        self._event_queue = event_queue
        self._execution_timeout = execution_timeout
        self._is_running = False
        self._stop_event = threading.Event()

    def dispatch_events(self) -> None:
        """Main dispatch loop for processing events"""
        self._is_running = True

        while self._is_running and not self._stop_event.is_set():
            try:
                # Get next event with timeout
                event = self._event_queue.get(timeout=0.1)

                # Process the event
                self._process_event(event)

                # Mark as processed
                self._event_queue.task_done()

            except queue.Empty:
                # No events available
                continue

            except Exception as e:
                logger.error(f"Error dispatching event: {e}", exc_info=True)

    def _process_event(self, event: Any) -> None:
        """Process a single event"""
        # Event processing logic will be implemented based on event types
        logger.debug(f"Processing event: {event}")

    def stop(self) -> None:
        """Stop the dispatcher"""
        self._is_running = False
        self._stop_event.set()