from pathlib import Path


class FileStoreMixin():
    """Utility functions for FileStore."""


    def strip_submission_prefix(self, filename: str|Path) -> str:
        """Removes the leading `/{submission_id}` from a filename path."""
        return "/".join(str(filename).split("/")[2:])
