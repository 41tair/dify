"""Command channel for external control of workflow execution"""

import queue
import threading
from abc import ABC, abstractmethod
from typing import Any, Optional


class CommandChannel(ABC):
    """Abstract base class for command channels"""

    @abstractmethod
    def send(self, command: Any) -> None:
        """Send a command to the engine"""
        pass

    @abstractmethod
    def get(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Get next command from the channel"""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all pending commands"""
        pass


class InMemoryCommandChannel(CommandChannel):
    """In-memory command channel using a queue"""

    def __init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()

    def send(self, command: Any) -> None:
        """Send a command to the engine"""
        with self._lock:
            self._queue.put(command)

    def get(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Get next command from the channel"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self) -> None:
        """Clear all pending commands"""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break