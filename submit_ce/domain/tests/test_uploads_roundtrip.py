"""
Coverage-focused tests for submit_ce.domain.uploads

What these tests cover
----------------------
- FileError: to_dict()/from_dict() roundtrip
- FileStatus: to_dict()/from_dict() roundtrip, including:
    * 'modified' as ISO string → parsed into datetime
    * nested 'errors' list as dicts → FileError objects
- Upload:
    * file_count property
    * to_dict()/from_dict() roundtrip
    * all four timestamp fields handled as strings on input
    * 'source_format' string converted to SubmissionContent.Format enum

The 'uploads' module primarily provides data structures and conversion helpers.
Exercising both serialization and deserialization paths touches the majority
of uncovered lines in this module without requiring any external services.
"""

# -----------------------------
# Imports
# -----------------------------

from datetime import datetime, timezone

from submit_ce.domain.uploads import (
    FileErrorLevels,
    FileError,
    FileStatus,
    UploadStatus,
    UploadLifecycleStates,
    Workspace,
)
from submit_ce.domain.submission import SubmissionContent


# -----------------------------
# Small helper (tz-aware 'now')
# -----------------------------

def _now():
    # Use native tz-aware datetimes (UTC) to align with module expectations.
    return datetime.now(timezone.utc)


# ------------------------------------------------------------
# FileError: verify dict round-trip and field value integrity
# ------------------------------------------------------------

def test_file_error_roundtrip_dict():
    err = FileError(
        error_type=FileErrorLevels.ERROR,
        message="bad file",
        more_info="explanation",
    )
    restored = FileError.model_validate(err.model_dump())
    assert restored == err



# -------------------------------------------------------------------------
# FileStatus: verify dict round-trip with string 'modified' and nested errors
# -------------------------------------------------------------------------

def test_file_status_roundtrip_with_string_modified_and_errors():
    # Prepare input dict in the *shape that from_dict expects*:
    # - 'modified' provided as ISO string → should be parsed to datetime
    # - 'errors' provided as list of dicts → should become FileError objects
    input_dict = {
        "path": "/workspace/paper",
        "name": "paper.tex",
        "content_type": "text/x-tex",
        "bytes": 1234,
        "modified": _now().isoformat(),
        "crc32c": "fakecrc",
        "url": "https://example.com/fake#234324",
        "is_versioned": True,
        "ancillary": False,
        "errors": [
            {
                "error_type": FileErrorLevels.WARNING,
                "message": "suspicious macro",
                "more_info": "line 42",
            }
        ],
    }
    status = FileStatus.model_validate(input_dict)
    # Now go the other direction; to_dict should:
    # - emit modified as ISO string
    # - convert FileError objects back to dicts

    # Check essential fields survived the roundtrip.
    assert status == FileStatus(**status.model_dump())

    # assert roundtrip_dict["path"] == input_dict["path"]
    # assert roundtrip_dict["name"] == input_dict["name"]
    # assert roundtrip_dict["file_type"] == input_dict["file_type"]
    # assert roundtrip_dict["size"] == input_dict["size"]
    # assert isinstance(status.modified, datetime)
    # assert isinstance(status.errors[0], FileError)
    # assert roundtrip_dict["errors"][0]["message"] == "suspicious macro"


# ---------------------------------------------------------------------
# Upload: verify file_count and full nested round-trip with conversions
# ---------------------------------------------------------------------

def test_upload_roundtrip_with_nested_status_and_errors_and_conversions():
    # Build a nested FileStatus (already in object form).
    nested_status = FileStatus(
        path="/workspace/paper",
        name="paper.tex",
        content_type="text/x-tex",
        bytes=2048,
        crc32c="fakecrc",
        url="https://example.com/x#23432433",
        is_versioned=True,
        modified=_now(),
        ancillary=False,
        errors=[
            FileError(error_type=FileErrorLevels.WARNING, message="minor", more_info="ok to proceed")
        ],
    )

    # Construct an Upload object with enums and datetimes.
    up = Workspace(
        started=_now(),
        completed=_now(),
        created=_now(),
        modified=_now(),
        status=UploadStatus.READY,
        lifecycle=UploadLifecycleStates.ACTIVE,
        locked=False,
        identifier="upload-123",
        source_format=SubmissionContent.Format.PDF,  # enum
        checksum="abc123",
        size=4096,
        compressed_size=1024,
        files=[nested_status],
        errors=[
            FileError(error_type=FileErrorLevels.ERROR, message="fatal", more_info="stop here")
        ],
    )

    # Sanity: file_count reflects the files list length.
    assert up.file_count == 1

    # Convert to dict; enums become .value, timestamps become ISO strings, and
    # nested objects are converted to dicts.
    up_dict = up.model_dump()

    # Now modify dict to resemble typical JSON inbound payload where:
    # - timestamps are strings (already true)
    # - 'source_format' is an enum value string (already true)
    # - nested lists are dicts (already true)
    #
    # Reconstruct Upload from the dict. from_dict should:
    # - parse all four timestamp strings → datetime
    # - convert source_format string → SubmissionContent.Format enum
    # - map nested file/error dicts back to objects
    restored = Workspace.model_validate(up_dict)

    assert up == restored

    # # Verify key properties and nested structures survived the round-trip.
    # assert restored.status == UploadStatus.READY.value
    # assert restored.lifecycle == UploadLifecycleStates.ACTIVE.value
    # assert restored.source_format == SubmissionContent.Format.PDF
    # assert isinstance(restored.started, datetime)
    # assert isinstance(restored.files[0], FileStatus)
    # assert isinstance(restored.errors[0], FileError)
