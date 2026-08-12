import posixpath
from pathlib import Path
from typing import Optional


# Shown to the user (via the upload controller's flash) when an uploaded
# archive contains a member whose path is absolute or escapes the submission
# directory with "..". Kept generic and non-technical.
UNSAFE_ARCHIVE_MEMBER = (
    "We couldn't process your uploaded archive because it contains a file "
    "with an unsafe path. Please repackage your files using relative paths "
    "inside the archive (no leading '/' and no '..')."
)


def safe_member_rel(raw_name: str) -> Optional[str]:
    """Normalize an archive member path and reject unsafe ones.

    Returns the normalized, submission-relative path for `raw_name`, or None
    for the archive root itself (".", "") which callers should skip.

    Raises ValueError if the member path is absolute or points outside the
    submission's source directory via "..". `posixpath.normpath` collapses
    "./" and redundant segments (see SUBMISSION-224) but deliberately keeps
    leading "..", so a traversal like "../../etc/x" survives normalization and
    is caught here rather than silently producing a key/path outside the
    submission.
    """
    if posixpath.isabs(raw_name):
        raise ValueError(UNSAFE_ARCHIVE_MEMBER)
    rel = posixpath.normpath(raw_name)
    if rel in (".", ""):
        return None
    if rel == ".." or rel.startswith("../") or "/../" in rel:
        raise ValueError(UNSAFE_ARCHIVE_MEMBER)
    return rel


class FileStoreMixin():
    """Utility functions for FileStore."""


    def strip_submission_prefix(self, filename: str|Path) -> str:
        """Removes the leading `/{submission_id}` from a filename path."""
        return "/".join(str(filename).split("/")[2:])
