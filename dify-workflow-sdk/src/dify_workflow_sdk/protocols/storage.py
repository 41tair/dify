"""Storage protocol for file management"""

from abc import ABC, abstractmethod
from typing import Any, BinaryIO, Dict, Optional


class FileInfo:
    """File information"""
    def __init__(
        self,
        file_id: str,
        name: str,
        size: int,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.file_id = file_id
        self.name = name
        self.size = size
        self.mime_type = mime_type
        self.metadata = metadata or {}


class FileStorage(ABC):
    """Abstract interface for file storage"""

    @abstractmethod
    def save(self, file: BinaryIO, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Save a file to storage.

        Args:
            file: File-like object to save
            metadata: Optional metadata to store with the file

        Returns:
            File ID for retrieving the file
        """
        pass

    @abstractmethod
    def load(self, file_id: str) -> BinaryIO:
        """
        Load a file from storage.

        Args:
            file_id: ID of the file to load

        Returns:
            File-like object

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        pass

    @abstractmethod
    def delete(self, file_id: str) -> bool:
        """
        Delete a file from storage.

        Args:
            file_id: ID of the file to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def exists(self, file_id: str) -> bool:
        """
        Check if a file exists.

        Args:
            file_id: ID of the file to check

        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    def get_info(self, file_id: str) -> Optional[FileInfo]:
        """
        Get file information.

        Args:
            file_id: ID of the file

        Returns:
            FileInfo object or None if not found
        """
        pass


class InMemoryFileStorage(FileStorage):
    """Simple in-memory file storage for testing"""

    def __init__(self):
        self._files: Dict[str, bytes] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._counter = 0

    def save(self, file: BinaryIO, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Save a file to memory"""
        self._counter += 1
        file_id = f"file_{self._counter}"

        content = file.read()
        self._files[file_id] = content
        self._metadata[file_id] = metadata or {}

        return file_id

    def load(self, file_id: str) -> BinaryIO:
        """Load a file from memory"""
        if file_id not in self._files:
            raise FileNotFoundError(f"File {file_id} not found")

        import io
        return io.BytesIO(self._files[file_id])

    def delete(self, file_id: str) -> bool:
        """Delete a file from memory"""
        if file_id in self._files:
            del self._files[file_id]
            del self._metadata[file_id]
            return True
        return False

    def exists(self, file_id: str) -> bool:
        """Check if a file exists"""
        return file_id in self._files

    def get_info(self, file_id: str) -> Optional[FileInfo]:
        """Get file information"""
        if file_id not in self._files:
            return None

        metadata = self._metadata.get(file_id, {})
        return FileInfo(
            file_id=file_id,
            name=metadata.get("name", file_id),
            size=len(self._files[file_id]),
            mime_type=metadata.get("mime_type", "application/octet-stream"),
            metadata=metadata,
        )