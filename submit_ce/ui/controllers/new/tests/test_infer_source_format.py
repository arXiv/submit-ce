"""Tests for ``_infer_source_format``.

Ancillary files do not decide the format, as in preflight, which Submission 1.5
takes the format from.
"""

import posixpath
from datetime import datetime

from submit_ce.domain.uploads import FileStatus, SourceFormat
from submit_ce.ui.controllers.new.upload import _infer_source_format


def _files(*paths):
    return [FileStatus(path=path, name=posixpath.basename(path),
                       content_type='application/octet-stream', bytes=1,
                       crc32c='fakecrc', url=f'https://example.com/{path}',
                       is_versioned=True, modified=datetime.now(),
                       ancillary=path.startswith('anc/'))
            for path in paths]


def test_pdf_with_ancillary_files_is_pdf():
    assert _infer_source_format(_files('paper.pdf', 'anc/data.csv')) == SourceFormat.PDF


def test_ancillary_tex_does_not_make_it_tex():
    assert _infer_source_format(_files('paper.pdf', 'anc/code.tex')) == SourceFormat.PDF
