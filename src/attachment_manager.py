#!/usr/bin/env python3
"""
Attachment Manager - Discord attachment file management system

This module is responsible for:
1. Asynchronous downloading of Discord attachments
2. File format validation and size limit management
3. Automatic file naming and duplicate avoidance
4. Storage management and automatic cleanup
5. Path generation for Claude Code integration

Extensibility points:
- Adding support for new file formats
- Implementing file conversion/processing features
- External storage integration (S3, GCS, etc.)
- Virus scanning and security features
- Metadata extraction and analysis
"""

import os
import sys
import secrets
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

# Add package root to path (for relative imports)
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import aiohttp
except ImportError:
    print("Error: aiohttp is not installed. Run: pip install aiohttp")
    sys.exit(1)

from config.settings import SettingsManager

# Logging configuration
logger = logging.getLogger(__name__)

@dataclass
class FileMetadata:
    """
    Data class for file metadata management

    Extension points:
    - Additional metadata fields
    - File analysis results
    - Conversion processing info
    """
    original_name: str
    saved_name: str
    file_path: str
    size: int
    mime_type: Optional[str] = None
    download_url: str = ""
    timestamp: str = ""

class FileValidator:
    """
    File validation processing

    Future extensions:
    - Detailed MIME type validation
    - File content scanning
    - Virus scan integration
    - Custom validation rules
    """

    # Supported image formats (extensible)
    SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff'}

    # File size limit (compliant with Discord limits; configurable in the future)
    MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB

    @classmethod
    def is_supported_format(cls, filename: str) -> bool:
        """
        Check if the file format is supported

        Extension points:
        - Dynamic supported format management
        - MIME type validation
        - Custom format definitions
        """
        return Path(filename).suffix.lower() in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def is_valid_size(cls, size: int) -> bool:
        """
        Check if the file size is within limits

        Extension points:
        - Per-user size limits
        - Dynamic limit configuration
        - Compression to bypass limits
        """
        return size <= cls.MAX_FILE_SIZE

    @classmethod
    def validate_attachment(cls, attachment) -> Tuple[bool, Optional[str]]:
        """
        Comprehensive attachment validation

        Args:
            attachment: Discord attachment object

        Returns:
            Tuple[bool, Optional[str]]: (validity flag, error message)
        """
        # File format check
        if not cls.is_supported_format(attachment.filename):
            return False, f"Unsupported file format: {attachment.filename}"

        # File size check
        if not cls.is_valid_size(attachment.size):
            return False, f"File too large ({attachment.size} bytes, max {cls.MAX_FILE_SIZE})"

        return True, None

class FileNamingStrategy:
    """
    File naming strategy

    Future extensions:
    - Customizable naming rules
    - Per-user namespaces
    - Content-based naming
    - Duplicate avoidance algorithms
    """

    @staticmethod
    def generate_unique_filename(original_name: str) -> str:
        """
        Generate a unique filename

        Extension points:
        - Configurable naming patterns
        - Hash-based naming
        - Custom date format

        Args:
            original_name: Original filename

        Returns:
            str: Generated unique filename
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = secrets.token_hex(3)  # 6-character random string
        extension = Path(original_name).suffix.lower()

        # Default handling when no extension is present
        if not extension:
            extension = '.bin'

        return f"IMG_{timestamp}_{random_suffix}{extension}"

class StorageManager:
    """
    Storage management system

    Future extensions:
    - External storage support (S3, GCS, etc.)
    - Storage tiering
    - Automatic backups
    - Capacity limit management
    """

    def __init__(self, config_dir: Path):
        """
        Initialize the storage manager

        Args:
            config_dir: Configuration directory path
        """
        self.config_dir = config_dir
        self.attachments_dir = config_dir / 'attachments'
        self.ensure_storage_directory()

    def ensure_storage_directory(self):
        """
        Create/verify the storage directory

        Extension points:
        - Optimizing permission settings
        - Managing multiple directories
        - Capacity monitoring
        """
        try:
            self.attachments_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Storage directory ensured: {self.attachments_dir}")
        except Exception as e:
            logger.error(f"Failed to create storage directory: {e}")
            raise

    def get_storage_path(self, filename: str) -> Path:
        """
        Get the file storage path

        Extension points:
        - Directory hierarchy (e.g., by date)
        - Load-balanced directory selection
        - Duplicate file handling
        """
        return self.attachments_dir / filename

    def cleanup_old_files(self, max_age_days: int = 1) -> int:
        """
        Clean up old files

        Extension points:
        - Detailed deletion policies
        - Archiving
        - Pre-deletion notifications

        Args:
            max_age_days: Retention period (in days)

        Returns:
            int: Number of deleted files
        """
        if not self.attachments_dir.exists():
            return 0

        try:
            cutoff_time = datetime.now() - timedelta(days=max_age_days)
            deleted_count = 0

            for file_path in self.attachments_dir.glob('IMG_*'):
                try:
                    # Get the file's modification time
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                    if file_mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(f"Deleted old attachment: {file_path.name}")

                except OSError as e:
                    logger.warning(f"Failed to delete {file_path.name}: {e}")
                    continue

            if deleted_count > 0:
                logger.info(f"Cleanup completed: {deleted_count} files deleted")

            return deleted_count

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0

    def get_storage_info(self) -> Dict[str, Any]:
        """
        Get storage usage information

        Extension points:
        - Detailed statistics
        - File type analysis
        - Usage forecasting
        """
        try:
            if not self.attachments_dir.exists():
                return {
                    'total_files': 0,
                    'total_size': 0,
                    'total_size_mb': 0.0,
                    'directory': str(self.attachments_dir)
                }

            files = list(self.attachments_dir.glob('IMG_*'))
            total_size = sum(f.stat().st_size for f in files if f.is_file())

            return {
                'total_files': len(files),
                'total_size': total_size,
                'total_size_mb': round(total_size / 1024 / 1024, 2),
                'directory': str(self.attachments_dir),
                'last_updated': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting storage info: {e}")
            return {
                'total_files': 0,
                'total_size': 0,
                'total_size_mb': 0.0,
                'directory': str(self.attachments_dir),
                'error': str(e)
            }

class AttachmentDownloader:
    """
    Asynchronous file download processing

    Future extensions:
    - Concurrent download limit control
    - Progress display
    - Retry mechanism
    - Bandwidth throttling
    """

    # Configurable constants (to be moved to config file in the future)
    DOWNLOAD_TIMEOUT_SECONDS = 30
    MAX_CONCURRENT_DOWNLOADS = 5

    def __init__(self, storage_manager: StorageManager):
        """
        Initialize the downloader

        Args:
            storage_manager: Storage manager instance
        """
        self.storage_manager = storage_manager
        self.file_validator = FileValidator()
        self.naming_strategy = FileNamingStrategy()

    async def download_attachment(self, attachment) -> Optional[FileMetadata]:
        """
        Asynchronously download a Discord attachment

        Extension points:
        - Progress callbacks
        - Partial download support
        - Download priority control

        Args:
            attachment: Discord attachment object

        Returns:
            Optional[FileMetadata]: Metadata on successful download
        """
        try:
            # Step 1: File validation
            is_valid, error_msg = self.file_validator.validate_attachment(attachment)
            if not is_valid:
                logger.warning(f"Invalid attachment {attachment.filename}: {error_msg}")
                return None

            # Step 2: Generate filename
            saved_filename = self.naming_strategy.generate_unique_filename(attachment.filename)
            file_path = self.storage_manager.get_storage_path(saved_filename)

            # Step 3: Perform download
            success = await self._perform_download(attachment.url, file_path)
            if not success:
                return None

            # Step 4: Create metadata
            metadata = FileMetadata(
                original_name=attachment.filename,
                saved_name=saved_filename,
                file_path=str(file_path.absolute()),
                size=attachment.size,
                download_url=attachment.url,
                timestamp=datetime.now().isoformat()
            )

            logger.info(f"Downloaded attachment: {saved_filename} ({attachment.size} bytes)")
            return metadata

        except Exception as e:
            logger.error(f"Error downloading {attachment.filename}: {e}")
            return None

    async def _perform_download(self, url: str, file_path: Path) -> bool:
        """
        Perform the actual download

        Extension points:
        - Chunked downloading
        - Resume capability
        - Progress notifications
        """
        try:
            timeout = aiohttp.ClientTimeout(total=self.DOWNLOAD_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()

                        # Save file
                        with open(file_path, 'wb') as f:
                            f.write(content)

                        # Set permissions (read-only)
                        os.chmod(file_path, 0o644)

                        return True
                    else:
                        logger.error(f"HTTP {response.status} for URL: {url}")
                        return False

        except asyncio.TimeoutError:
            logger.error(f"Download timeout for URL: {url}")
            return False
        except Exception as e:
            logger.error(f"Download error for URL {url}: {e}")
            return False

class AttachmentManager:
    """
    Integrated attachment file management class

    Architecture features:
    - High concurrency via asynchronous processing
    - Extensibility through modular design
    - Robust error handling
    - Automatic resource management

    Extensible elements:
    - File conversion processing
    - Metadata extraction
    - External API integration
    - Statistics and analytics
    - Backup and sync
    """

    def __init__(self):
        """
        Initialize the attachment manager
        """
        self.settings = SettingsManager()
        self.storage_manager = StorageManager(self.settings.config_dir)
        self.downloader = AttachmentDownloader(self.storage_manager)

    async def process_attachments(self, attachments) -> List[str]:
        """
        Process multiple attachments in parallel

        Extension points:
        - Processing priority control
        - Real-time progress display
        - Detailed result analysis

        Args:
            attachments: List of Discord attachment objects

        Returns:
            List[str]: List of successfully saved file paths
        """
        if not attachments:
            return []

        logger.info(f"Processing {len(attachments)} attachment(s)")

        # Execute parallel downloads
        tasks = [self.downloader.download_attachment(attachment) for attachment in attachments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        successful_paths = []
        failed_count = 0

        for result in results:
            if isinstance(result, FileMetadata):
                successful_paths.append(result.file_path)
            elif isinstance(result, Exception):
                logger.error(f"Attachment processing failed: {result}")
                failed_count += 1
            else:
                # None case (validation failure, etc.)
                failed_count += 1

        # Log processing results
        logger.info(f"Attachment processing completed: {len(successful_paths)} success, {failed_count} failed")

        return successful_paths

    def cleanup_old_files(self, max_age_days: int = 1) -> int:
        """
        Clean up old files (synchronous wrapper)

        Args:
            max_age_days: Retention period (in days)

        Returns:
            int: Number of deleted files
        """
        return self.storage_manager.cleanup_old_files(max_age_days)

    def get_storage_info(self) -> Dict[str, Any]:
        """
        Get storage information (synchronous wrapper)

        Returns:
            Dict[str, Any]: Storage usage information
        """
        return self.storage_manager.get_storage_info()

# Test/debug functions
async def test_attachment_manager():
    """
    Test AttachmentManager operation

    Extension points:
    - Unit test implementation
    - Performance testing
    - Stress testing
    """
    manager = AttachmentManager()

    print(f"Storage directory: {manager.storage_manager.attachments_dir}")
    print(f"Storage info: {manager.get_storage_info()}")

    # Cleanup test
    deleted = manager.cleanup_old_files()
    print(f"Cleanup: {deleted} files deleted")

if __name__ == "__main__":
    asyncio.run(test_attachment_manager())
