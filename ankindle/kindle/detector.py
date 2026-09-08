import os
import glob

from ankindle.errors import KindleNotAttachedError, KindleNotReadableError


KINDLE_MOUNT_PATHS = [
    "/media/Kindle",
    "/media/kindle",
    "/media/*/Kindle",
    "/media/*/kindle",
    "/mnt/Kindle",
    "/mnt/kindle",
    "/run/media/*/Kindle",
    "/run/media/*/kindle",
]


def _resolve_paths(paths: list[str]) -> list[str]:
    resolved = []
    for path in paths:
        if "*" in path:
            resolved.extend(glob.glob(path))
        elif os.path.exists(path):
            resolved.append(path)
    return resolved


class KindleDetector:
    def __init__(self, mount_path: str | None = None):
        self.mount_path = mount_path or self._find_mount_path()

    def _find_mount_path(self) -> str | None:
        for path in _resolve_paths(KINDLE_MOUNT_PATHS):
            if os.access(path, os.R_OK):
                return path
        return None

    def detect_kindle(self) -> bool:
        if self.mount_path is None or not os.path.exists(self.mount_path):
            raise KindleNotAttachedError("Kindle is not attached")
        if not os.access(self.mount_path, os.R_OK):
            raise KindleNotReadableError("Kindle is attached but not readable")
        return True

    def get_helpful_message(self, error: Exception) -> str:
        if isinstance(error, KindleNotAttachedError):
            return (
                "Kindle device not found!\n\n"
                "Please connect your Kindle device using a USB cable and ensure it's in file transfer mode.\n"
                "You may need to:\n"
                "1. Connect your Kindle via USB\n"
                "2. Select 'Transfer files' when prompted on your Kindle\n"
                "3. Wait for the device to mount\n"
                "4. Try running the application again"
            )
        elif isinstance(error, KindleNotReadableError):
            return (
                "Kindle is connected but not accessible!\n\n"
                "The Kindle device is detected but cannot be read. This might be due to:\n"
                "1. Insufficient permissions - try running with sudo or check file permissions\n"
                "2. Device not in file transfer mode - ensure Kindle is set to 'Transfer files'\n"
                "3. Device is locked - unlock your Kindle and try again\n"
                "4. File system issues - try disconnecting and reconnecting the device"
            )
        return f"An unexpected error occurred: {error}"

    def find_kindle_mount_paths(self) -> list[str]:
        return _resolve_paths(KINDLE_MOUNT_PATHS)
