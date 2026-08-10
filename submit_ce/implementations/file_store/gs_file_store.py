"""Implementation of `FileStore` using Google Storage (GS)."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import IO, List, Optional
import json
import io
import logging
import posixpath
import tarfile
import zipfile
from typing_extensions import override

from arxiv.files import FileObj, FileDoesNotExist
from arxiv.files.object_store import GsObjectStore
from google.cloud.storage.blob import Blob
from yarl import URL

from submit_ce.api import SubmissionFileStore
from submit_ce.domain import Workspace
from submit_ce.domain.uploads import UploadLifecycleStates, UploadStatus, FileStatus
from submit_ce.domain.uploads import SubmitFile, is_file_tgz

from google.cloud import storage

from submit_ce.implementations.file_store.file_store_mixin import FileStoreMixin


logger = logging.getLogger(__file__)

# FileObj is designed so that Blob is a duck type of it.
# This same line is in arxiv.file.object_store
FileObj.register(Blob)

class GsFileStore(SubmissionFileStore, FileStoreMixin):
    """Functions for storing and getting source files using Google Storage (GS).

    For keys this will use a similar "shard id" used in the legacy system. The
    first four digits of the ID we'll call a "shard id". The shard id is used to
    create a directory that in turn holds a directory for each id's files.

    For example, id ``65393829`` would have a directory at
    ``{PREFIX}/6539/65393829``.

    To use this, the following config parameters must be set:

    - ``GS_BUCKET``: google storage bucket to use
    - ``GS_PREFIX``: a prefix to use after the ``GS_BUCKET`` and before the shard id. May be ""

    Pass a ``client`` to inject a pre-configured ``storage.Client`` If omitted,
    ``storage.Client()`` is used and credentials/endpoint are resolved from the
    environment as usual.

    2025-07-17: initial work
    """

    def __init__(self,
                 gs_bucket: str,
                 gs_prefix: str = "data/new",
                 source_prefix: str = "src",
                 client: Optional[storage.Client] = None,
                 qa_bucket: Optional[str] = None,
                 qa_prefix: str = "",
                 ):
        self.gs_bucket = gs_bucket
        """GS bucket to store the files."""
        self.gs_prefix = gs_prefix
        """Prefix in the {gs_bucket}/{shard}/{id} directory to store the source."""
        self.source_prefix = source_prefix
        """Prefix for source files"""

        if self.gs_prefix.startswith("/"):
            self.gs_prefix = self.gs_prefix[1:]
        if self.gs_prefix is None:
            self.gs_prefix = ""

        self.qa_prefix = (qa_prefix or "")
        """Prefix under the QA bucket for the submission-snapshot meta.json."""
        if self.qa_prefix.startswith("/"):
            self.qa_prefix = self.qa_prefix[1:]

        self.storage_client = client if client is not None else storage.Client()
        self.bucket = self.storage_client.bucket(self.gs_bucket)
        self.obj_store = GsObjectStore(self.bucket)

        self.qa_bucket = self.storage_client.bucket(qa_bucket) if qa_bucket else None
        """GS bucket for QA submission-snapshot metadata, or None if not configured."""
        self.qa_obj_store = GsObjectStore(self.qa_bucket) if self.qa_bucket else None


    @override
    def get_source_file_info(self, submission_id: str, path: Path|str) -> FileStatus:
        get_path = posixpath.join(self._source_path(submission_id), str(path))
        self._check_path_safe(submission_id, get_path)
        blob = self.bucket.get_blob(get_path)
        if blob is None:
            raise FileNotFoundError(f"File {path} does not exist in source for submission {submission_id}")
        return self._blob_to_file_status(submission_id, blob)

    @override
    def delete_source_file(self, submission_id: str, path: Path|str) -> Optional[FileStatus]:
        del_path = posixpath.join(self._source_path(submission_id), str(path))
        self._check_path_safe(submission_id, del_path)
        blob = self.bucket.get_blob(del_path)
        if blob is not None:
            file = self._blob_to_file_status(submission_id, blob)
            blob.delete()
            return file
        else:
            return None

    @override
    def get_workspace(self, submission_id: str) -> Workspace:
        src_dir = self._source_path(submission_id)
        files: List[FileStatus] = []
        for blob in self.bucket.client.list_blobs(self.bucket, prefix=src_dir):
            files.append(self._blob_to_file_status(submission_id, blob))

        return Workspace(
            identifier=submission_id,
            checksum='fake-checksum-asdf1234',
            size=sum([file.bytes for file in files if file]),
            started=datetime.now(),  # TODO bogus
            completed=datetime.now(),  # TODO bogus
            created=datetime.now(),  # TODO bogus
            modified=datetime.now(),  # TODO bogus
            status=UploadStatus.READY,
            lifecycle=UploadLifecycleStates.ACTIVE,
            locked=False,
            files=files,
            errors=[]
        )

    @override
    def store_source_file(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size: int) -> FileStatus:
        """Stores a file for a submission."""
        store_at = posixpath.join(self._source_path(submission_id), content.filename)
        self._check_path_safe(submission_id, store_at)
        blob = self.bucket.blob(store_at)
        blob.upload_from_file(content.stream, content_type=content.content_type)
        blob.reload()
        return self._blob_to_file_status(submission_id, blob)

    @override
    def store_source_package(self,
                     submission_id: str,
                     content: SubmitFile,
                     chunk_size: int) -> List[FileStatus]:
        """Store a source package for a submission."""

        # Upload the entire package file, because
        # - the legacy code seems to keep the gz current, and
        # - tex2pdf-api/preflight needs a path to a zip in a bucket.
        package_path = self._source_package_path(submission_id)
        package_blob = self.bucket.blob(package_path)
        content.stream.seek(0)
        package_blob.upload_from_file(content.stream, content_type=content.content_type)

        content.stream.seek(0)
        files = []
        src_dir = self._source_path(submission_id)

        is_zip = (content.content_type in ('application/zip', 'application/x-zip-compressed', 'application/x-zip')
                  or (content.filename and content.filename.endswith('.zip')))

        if is_zip:
            with zipfile.ZipFile(content.stream) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    # Normalize the member path before building the object key.
                    # Archives packed with `tar -C dir .` (and some zips) prefix
                    # every entry with "./", which would otherwise become a
                    # literal "./" segment in the GCS key (".../src/./main.tex")
                    # and never match the normalized filenames preflight reports
                    # -- silently breaking file deletion. normpath collapses
                    # "./" and redundant segments; skip the archive root itself.
                    # (SUBMISSION-224)
                    rel = posixpath.normpath(info.filename)
                    if rel in (".", ""):
                        continue
                    store_at = posixpath.join(src_dir, rel)
                    self._check_path_safe(submission_id, store_at)
                    with zf.open(info) as file:
                        blob = self.bucket.blob(store_at)
                        blob.upload_from_file(file, size=info.file_size)
                        files.append(self._blob_to_file_status(submission_id, blob))
        elif is_file_tgz(content):
            with tarfile.open(fileobj=content.stream, mode="r:*") as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    with extracted as file:
                        # Strip the "./" prefix that `tar -C dir .` adds; see the
                        # zip branch above (SUBMISSION-224).
                        rel = posixpath.normpath(member.name)
                        if rel in (".", ""):
                            continue
                        store_at = posixpath.join(src_dir, rel)
                        self._check_path_safe(submission_id, store_at)
                        blob = self.bucket.blob(store_at)
                        blob.upload_from_file(file, size=member.size)
                        files.append(self._blob_to_file_status(submission_id, blob))
        else:
            raise ValueError(f"Unsupported source package content type: {content.content_type!r}")

        return files

    @override
    def get_preview(self, submission_id: str) -> FileObj:
        preview_path = self._preview_path(submission_id)
        preview = self.bucket.blob(preview_path)
        if preview.exists():
            # bucket.blob() returns a local reference with empty _properties;
            # .exists() does a HEAD but doesn't populate metadata. Without
            # reload(), preview.size and preview.crc32c are both None and
            # the route layer's set_etag()/Content-Length header crash on
            # None. This matters in particular for PDFs that arrived in
            # the bucket via something other than our store_preview() path
            # (e.g., hand-copied for testing).
            try:
                preview.reload()
            except Exception as exc:
                logger.debug("preview reload failed for %s: %s",
                             preview_path, exc)
            return preview
        else:
            return FileDoesNotExist(preview_path)

    @override
    def store_preview(self, submission_id: str,
                      content: IO[bytes],
                      chunk_size: int = 4096) -> str:
        """Store a preview PDF for a submission."""
        preview_path = self._preview_path(submission_id)
        blob = self.bucket.blob(preview_path)
        blob.upload_from_file(content)
        blob.reload()
        return blob.crc32c

    @override
    def does_nostamp_preview_exist(self, submission_id: str) -> bool:
        """Whether an unstamped ``<submission_id>-nostamp.pdf`` exists."""
        return self.bucket.blob(
            self._nostamp_preview_path(submission_id)).exists()

    @override
    def delete_nostamp_preview(self, submission_id: str) -> None:
        """Delete ``<submission_id>-nostamp.pdf`` if it exists."""
        blob = self.bucket.blob(self._nostamp_preview_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def store_directives(self, submission_id: str, content: dict) -> str:
        """Store directives.json for a submission."""
        directives_path = self._directives_path(submission_id)
        blob = self.bucket.blob(directives_path)
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')
        blob.reload()
        return blob.crc32c

    def get_source_checksum(self, submission_id: str) -> str:
        """Get the checksum of the source package for a submission."""
        return self._get_checksum(self._source_package_path(submission_id))

    @override
    def does_source_exist(self, submission_id: str) -> bool:
        """Determine whether source has been deposited for a submission."""
        return self.bucket.blob(self._source_package_path(submission_id)).exists()

    @override
    def build_source_package(self, submission_id: str) -> bytes:
        """Build a fresh .tar.gz from the current source files in the bucket.

        Walks the submission's ``src/`` directory, fetches each blob,
        and packs the contents into a gzipped tarball returned as
        bytes. The persisted ``<submission_id>.tar.gz`` is NOT touched
        by this method -- use :meth:`write_source_package` for that.

        Files that are listed in the workspace but whose blobs cannot
        be read are skipped with a warning rather than aborting the
        build. Returns the gzipped tarball bytes; if the workspace is
        empty, returns an empty (but valid) gzipped tar.
        """
        workspace = self.get_workspace(submission_id)
        buf = io.BytesIO()
        files_added = 0
        files_skipped = 0
        if workspace and workspace.files:
            with tarfile.open(fileobj=buf, mode='w:gz') as tar:
                for f in workspace.files:
                    blob = self.get_source_file(
                        submission_id=submission_id, path=f.path)
                    if isinstance(blob, FileDoesNotExist):
                        logger.warning(
                            "build_source_package: workspace lists %s but "
                            "blob is missing for submission %s; skipping",
                            f.path, submission_id,
                        )
                        files_skipped += 1
                        continue
                    try:
                        data = blob.download_as_bytes()
                    except Exception as exc:
                        logger.warning(
                            "build_source_package: could not read %s for "
                            "submission %s: %s; skipping",
                            f.path, submission_id, exc,
                        )
                        files_skipped += 1
                        continue

                    info = tarfile.TarInfo(name=f.path)
                    info.size = len(data)
                    updated = getattr(blob, 'updated', None) or datetime.now()
                    try:
                        info.mtime = int(updated.timestamp())
                    except (AttributeError, TypeError):
                        info.mtime = int(datetime.now().timestamp())
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(data))
                    files_added += 1
        else:
            # No files: still emit a syntactically valid (empty) gzipped tar
            with tarfile.open(fileobj=buf, mode='w:gz'):
                pass
        logger.info(
            "build_source_package: built tarball for submission %s "
            "(files_added=%d, files_skipped=%d, size_bytes=%d)",
            submission_id, files_added, files_skipped, buf.tell(),
        )
        return buf.getvalue()

    @override
    def write_source_package(self, submission_id: str) -> None:
        """Build the source package and upload it to the canonical path.

        Overwrites any existing ``<submission_id>.tar.gz`` so callers
        that resolve the source URL (e.g., the preflight API) see
        current source rather than a stale snapshot from a previous
        compile.
        """
        data = self.build_source_package(submission_id)
        package_path = self._source_package_path(submission_id)
        blob = self.bucket.blob(package_path)
        blob.upload_from_file(io.BytesIO(data), content_type='application/gzip')
        logger.info(
            "write_source_package: wrote %s (size_bytes=%d)",
            package_path, len(data),
        )

    @override
    def delete_source_package(self, submission_id: str) -> None:
        """Delete the persisted ``<submission_id>.tar.gz`` if it exists."""
        blob = self.bucket.blob(self._source_package_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_source_package(self, submission_id: str) -> FileObj:
        """Retrieve the persisted ``<submission_id>.tar.gz`` source package."""
        package_path = self._source_package_path(submission_id)
        blob = self.bucket.blob(package_path)
        if blob.exists():
            # See get_preview: bucket.blob() returns a reference with empty
            # metadata; reload so size/crc32c are populated for the route's
            # Content-Length / ETag handling.
            try:
                blob.reload()
            except Exception as exc:
                logger.debug("source package reload failed for %s: %s",
                             package_path, exc)
            return blob
        return FileDoesNotExist(package_path)

    @override
    def get_preview_checksum(self, submission_id: str) -> str:
        """Get the checksum of the preview PDF for a submission."""
        return self._get_checksum(self._preview_path(submission_id))

    @override
    def does_preview_exist(self, submission_id: str) -> bool:
        """Determine whether a preview has been deposited for a submission."""
        return self.bucket.blob(self._preview_path(submission_id)).exists()

    @override
    def get_source_file(self, submission_id: str, path: Path|str) -> FileObj:
        src_path = posixpath.join(self._source_path(submission_id), str(path))
        self._check_path_safe(submission_id, src_path)
        blob = self.bucket.blob(src_path)
        if blob.exists():
            return blob
        else:
            return FileDoesNotExist(src_path)

    @override
    def delete_workspace(self, submission_id: str) -> None:
        blobs = self.bucket.list_blobs(prefix=self._source_path(submission_id))
        for blob in blobs:
            blob.delete()

    @override
    def is_available(self) -> bool:
        """Determine whether the filesystem is available."""
        try:
            return self.bucket.exists()
        except Exception as ex:
            logger.error(f"Could not check if bucket exists: {ex}")
            return False

    @override
    def delete_all_source_files(self, submission_id: str) -> None:
        blobs = self.bucket.list_blobs(prefix=self._source_path(submission_id))
        for blob in blobs:
            blob.delete()

    @override
    def delete_preview(self, submission_id: str) -> None:
        preview_path = self._preview_path(submission_id)
        blob = self.bucket.blob(preview_path)
        if blob.exists():
            blob.delete()

    @override
    def get_directives(self, submission_id: str) -> FileObj:
        path = self._directives_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_directives(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._directives_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_directives_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._directives_path(submission_id))

    @override
    def does_directives_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._directives_path(submission_id)).exists()

    @override
    def store_user_decisions(self, submission_id: str, content: dict) -> str:
        blob = self.bucket.blob(self._user_decisions_path(submission_id))
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')
        blob.reload()
        return blob.crc32c

    @override
    def get_user_decisions(self, submission_id: str) -> FileObj:
        path = self._user_decisions_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_user_decisions(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._user_decisions_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_user_decisions_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._user_decisions_path(submission_id))

    @override
    def does_user_decisions_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._user_decisions_path(submission_id)).exists()

    @override
    def store_compile_log(self, submission_id: str,
                          content: IO[bytes],
                          chunk_size: int = 4096) -> str:
        """Store the compile log for a submission."""
        path = self._compile_log_path(submission_id)
        blob = self.bucket.blob(path)
        blob.upload_from_file(content)
        blob.reload()
        return blob.crc32c

    @override
    def uncompress_compile_tarball(self, submission_id: str) -> None:
        """Download outcome tarball, read outcome-src.json for pdf and main.log filenames, then store them."""
        blob = self.bucket.blob(self._outcome_path(submission_id))

        with tarfile.open(fileobj=io.BytesIO(blob.download_as_bytes()), mode='r:gz') as tar:
            outcome_member = next(
                (m for m in tar.getmembers() if posixpath.basename(m.name) == 'outcome-src.json'),
                None,
            )
            if outcome_member is None:
                raise FileNotFoundError(f"outcome-src.json not found in outcome tarball for submission {submission_id}")
            extracted = tar.extractfile(outcome_member)
            if extracted is None:
                raise RuntimeError(f"Could not extract outcome-src.json for submission {submission_id}")
            outcome = json.load(extracted)

            pdf_name = outcome.get("pdf_file")

            # tex2pdf names the log after the main TeX file (e.g. 'paper.log'),
            # not always 'main.log', so we can't hardcode the key. Pick the
            # .log whose stem matches the produced PDF, else the first .log.
            out_files = outcome.get("out_files", {}) or {}
            log_candidates = [
                info.get("name", key)
                for key, info in out_files.items()
                if str(key).endswith(".log")
                or str(info.get("name", "")).endswith(".log")
            ]
            log_name = None
            if pdf_name:
                pdf_stem = posixpath.splitext(pdf_name)[0]
                log_name = next(
                    (n for n in log_candidates
                     if posixpath.splitext(n)[0] == pdf_stem),
                    None,
                )
            if log_name is None and log_candidates:
                log_name = log_candidates[0]
            if log_name is None:
                logger.warning(
                    "uncompress_compile_tarball: no .log found in outcome "
                    "out_files for submission %s (status=%s, out_files keys=%s)",
                    submission_id, outcome.get("status"), list(out_files.keys()),
                )

            for member in tar.getmembers():
                name = posixpath.basename(member.name)
                if name == log_name:
                    extracted = tar.extractfile(member)
                    if extracted is not None:
                        self.store_compile_log(submission_id, extracted)
                elif pdf_name and name == pdf_name:
                    extracted = tar.extractfile(member)
                    if extracted is not None:
                        self.store_preview(submission_id, extracted)

    @override
    def get_compile_log(self, submission_id: str) -> FileObj:
        path = self._compile_log_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_compile_log(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._compile_log_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_compile_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._compile_log_path(submission_id))

    @override
    def does_compile_log_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._compile_log_path(submission_id)).exists()

    @override
    def get_compile_json(self, submission_id: str) -> FileObj:
        path = self._compile_json_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_compile_json(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._compile_json_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_compile_json_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._compile_json_path(submission_id))

    @override
    def does_compile_json_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._compile_json_path(submission_id)).exists()

    @override
    def get_preflight(self, submission_id: str) -> FileObj:
        path = self._preflight_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_preflight(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._preflight_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_preflight_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._preflight_path(submission_id))

    @override
    def does_preflight_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._preflight_path(submission_id)).exists()

    @override
    def get_request_log(self, submission_id: str) -> FileObj:
        path = self._request_log_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_request_log(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._request_log_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_request_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._request_log_path(submission_id))

    @override
    def does_request_log_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._request_log_path(submission_id)).exists()

    @override
    def get_source_log(self, submission_id: str) -> FileObj:
        path = self._source_log_path(submission_id)
        blob = self.bucket.blob(path)
        return blob if blob.exists() else FileDoesNotExist(path)

    @override
    def delete_source_log(self, submission_id: str) -> None:
        blob = self.bucket.blob(self._source_log_path(submission_id))
        if blob.exists():
            blob.delete()

    @override
    def get_source_log_checksum(self, submission_id: str) -> str:
        return self._get_checksum(self._source_log_path(submission_id))

    @override
    def does_source_log_exist(self, submission_id: str) -> bool:
        return self.bucket.blob(self._source_log_path(submission_id)).exists()

    def _get_checksum(self, path: str) -> str:
        """Return the crc32c checksum of the blob at ``path``.

        Returns an empty string when the blob doesn't exist or has no
        crc32c (rather than ``None``), so callers feeding the value
        into ``Response.set_etag()`` and ``Content-Length`` headers
        don't crash. This matters in particular for blobs that arrived
        in the bucket via something other than our upload paths (e.g.
        hand-copied for testing), which may lack a crc32c on the
        object.
        """
        item = self.bucket.get_blob(path)
        return (item.crc32c or "") if item is not None else ""

    def _submission_path(self, submission_id: str) -> str:
        """Gets GS filesystem structure ex /{rootdir}/{first 4 digits of submission id}/{submission id}"""
        return posixpath.join(self.gs_prefix, submission_id)

    def _source_path(self, submission_id: int|str) -> str:
        """Get the source path for the submission_id"""
        return posixpath.join(self._submission_path(str(submission_id)), self.source_prefix)

    def _source_package_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), f'{submission_id}.tar.gz')

    def _preview_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), f'{submission_id}.pdf')

    def _nostamp_preview_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), f'{submission_id}-nostamp.pdf')

    def _qa_meta_json_path(self, submission_id: str) -> str:
        """QA-bucket object path, e.g. ``{qa_prefix}/4848983/4848983.meta.json``."""
        return posixpath.join(self.qa_prefix, str(submission_id), f'{submission_id}.meta.json')

    def _preflight_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'gcp_preflight.json')

    def _directives_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'directives.json')

    def _user_decisions_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'user_decisions.json')

    def _compile_log_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'gcp_compile.log')

    def _outcome_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'outcome.tgz')

    @override
    def get_source_package_checksum(self, submission_id: str) -> str:
        return self.get_source_checksum(submission_id)

    def _compile_json_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'gcp_compile.json')

    def _full_base_path(self) -> str:
        return f'gs://{self.gs_bucket}'

    @override
    def get_full_submission_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._submission_path(submission_id)}'

    @override
    def get_full_submission_source_path(self, submission_id: str) -> str:
        # The trailing slash is needed.
        return f'{self._full_base_path()}/{self._submission_path(submission_id)}/{self.source_prefix}/'

    @override
    def get_full_source_package_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._source_package_path(submission_id)}'

    @override
    def get_full_preflight_package_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._preflight_path(submission_id)}'

    @override
    def get_full_directives_package_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._directives_path(submission_id)}'

    @override
    def get_full_outcome_path(self, submission_id: str) -> str:
        return f'{self._full_base_path()}/{self._outcome_path(submission_id)}'

    def _request_log_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'gcp_request.log')

    def _source_log_path(self, submission_id: str) -> str:
        return posixpath.join(self._submission_path(submission_id), 'source.log')

    @override
    def store_zzrm(self, submission_id: str, content: dict) -> None:
        path = posixpath.join(self._source_path(submission_id), '00README.json')
        blob = self.bucket.blob(path)
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')

    @override
    def store_qa_metadata(self, submission_id: str, content: dict) -> None:
        """Store the QA submission-snapshot meta.json in the QA bucket.

        Writes to ``gs://{qa_bucket}/{qa_prefix}/{submission_id}/{submission_id}.meta.json``.
        """
        if self.qa_bucket is None:
            raise RuntimeError("QA bucket is not configured; cannot store QA metadata")
        path = self._qa_meta_json_path(submission_id)
        blob = self.qa_bucket.blob(path)
        data = json.dumps(content).encode('utf-8')
        blob.upload_from_file(io.BytesIO(data), content_type='application/json')

    #: QA snapshot artifact key -> path-builder method. Mirrors
    #: ``upload_submission_files`` in the QA generator (arxiv-qa
    #: snapshot_submission). Keys are the QA-facing names; the paths resolve to
    #: the actual objects in this store.
    _QA_ARTIFACT_PATHS = (
        ("pdf", "_preview_path"),
        ("source", "_source_package_path"),
        ("directives.json", "_directives_path"),
        ("gcp-compile.json", "_compile_json_path"),
        ("gcp_compile.log", "_compile_log_path"),
        ("gcp_preflight.json", "_preflight_path"),
        ("source.log", "_source_log_path"),
    )

    @override
    def get_qa_artifact_info(self, submission_id: str) -> tuple[dict[str, str], dict[str, str]]:
        """Return ``(urls, crc32c)`` for QA artifacts present in the bucket.

        Each URL includes the GS object generation
        (``gs://{bucket}/{name}#{generation}``). A single ``get_blob`` per
        artifact supplies both the generation and crc32c; artifacts with no
        object are omitted (matching the QA snapshot generator).
        """
        urls: dict[str, str] = {}
        crc32c: dict[str, str] = {}
        for key, path_method in self._QA_ARTIFACT_PATHS:
            path = getattr(self, path_method)(submission_id)
            blob = self.bucket.get_blob(path)
            if blob is None:
                continue
            urls[key] = f"gs://{self.gs_bucket}/{blob.name}#{blob.generation}"
            crc32c[key] = blob.crc32c or ""
        return urls, crc32c

    def _blob_to_file_status(self, submission_id: str, blob: Blob) -> FileStatus:
        src_dir = self._source_path(submission_id)
        anc_dir = posixpath.join(src_dir, "anc")
        # TODO blob.name is Optional[str]; figure out when it can actually be None
        if blob.name is None:
            raise ValueError(f"Blob has no name for submission {submission_id}")
        file_path = blob.name
        return FileStatus(path=file_path.removeprefix(src_dir + '/'),
                   name=posixpath.basename(file_path),
                   content_type=blob.content_type or 'application/octet-stream',
                   bytes=blob.size,
                   crc32c=blob.crc32c,
                   modified=blob.updated,
                   ancillary=file_path.startswith(anc_dir + '/'),
                   url=URL(f"gs://{blob.bucket.name}/{blob.name}#{blob.generation}"),
                   is_versioned=True,
                   errors=[])  # TODO not sure where to get errors from

    def _check_path_safe(self, submission_id: int|str, path: str) -> None:
        """Checks if a path is safely part of the files for `submission_id`.

        Raises an error if the path is not under the `self._source_path()` for
        `submission_id`
        """
        if not path.startswith(self._source_path(submission_id)):
            raise RuntimeError(f"Path {path} not part of submission_id {submission_id}")

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"gs_bucket={self.gs_bucket},"
                f"gs_prefix={self.gs_prefix},"
                f"source_prefix={self.source_prefix})")
