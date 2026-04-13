"""
dropbox_client.py
─────────────────
Handles all Dropbox operations:
  - List files in the incoming folder
  - Get a temporary download link (for Azure OCR)
  - Move files to completed or exception folders
"""

import dropbox
from dropbox.files import WriteMode


class DropboxClient:
    """Wrapper around the Dropbox SDK for receipt-processing operations."""

    def __init__(self, app_key: str, app_secret: str, refresh_token: str,
                 incoming_folder: str, completed_folder: str, exception_folder: str):
        self.incoming_folder = incoming_folder
        self.completed_folder = completed_folder
        self.exception_folder = exception_folder

        # Create the Dropbox client with a refresh token (long-lived)
        self.dbx = dropbox.Dropbox(
            app_key=app_key,
            app_secret=app_secret,
            oauth2_refresh_token=refresh_token,
        )

    # ── List incoming files ───────────────────────────────────────────

    def list_incoming_files(self) -> list[dict]:
        """
        Return a list of files in the incoming folder.
        Each item is a dict with keys: name, path, size, id.
        Returns an empty list if the folder is empty.
        """
        try:
            result = self.dbx.files_list_folder(self.incoming_folder)
        except dropbox.exceptions.ApiError as e:
            # Folder might not exist or be empty
            if e.error.is_path() and e.error.get_path().is_not_found():
                return []
            raise

        files = []
        for entry in result.entries:
            if isinstance(entry, dropbox.files.FileMetadata):
                files.append({
                    "name": entry.name,
                    "path": entry.path_display,
                    "size": entry.size,
                    "id": entry.id,
                })
        return files

    # ── Get a temporary download link ─────────────────────────────────

    def get_temp_link(self, file_path: str) -> str:
        """
        Get a temporary direct-download link for a file.
        Azure OCR can fetch the image from this URL.
        """
        result = self.dbx.files_get_temporary_link(file_path)
        return result.link

    # ── Move file to completed ────────────────────────────────────────

    def move_to_completed(self, source_path: str, merchant_name: str) -> str:
        """
        Move a processed receipt from /incoming to /completed.
        Uses Dropbox autorename to handle duplicate filenames automatically
        (no need for timestamp-based uniqueness in our code).

        Returns the new file path.
        """
        # Build a descriptive destination name
        original_name = source_path.rsplit("/", 1)[-1]
        safe_merchant = _sanitize_filename(merchant_name)
        dest_name = f"{safe_merchant} {original_name}"
        dest_path = f"{self.completed_folder}/{dest_name}"

        result = self.dbx.files_move_v2(
            source_path,
            dest_path,
            autorename=True,    # Dropbox handles uniqueness for us
        )
        return result.metadata.path_display

    # ── Move file to exception ────────────────────────────────────────

    def move_to_exception(self, source_path: str) -> str:
        """
        Move a receipt that couldn't be processed to /exception.
        Uses Dropbox autorename for uniqueness.

        Returns the new file path.
        """
        original_name = source_path.rsplit("/", 1)[-1]
        dest_path = f"{self.exception_folder}/{original_name}"

        result = self.dbx.files_move_v2(
            source_path,
            dest_path,
            autorename=True,
        )
        return result.metadata.path_display


def _sanitize_filename(name: str) -> str:
    """Remove characters that are problematic in file paths."""
    # Replace newlines and carriage returns
    name = name.replace("\n", " ").replace("\r", "")
    # Remove characters not allowed in Dropbox paths
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, "")
    return name.strip()
