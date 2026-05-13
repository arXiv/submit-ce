"""Custom Jinja2 filters."""

from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime
from locale import strxfrm
from pathlib import Path
from typing import List, Tuple, Callable

from arxiv import taxonomy
from pytz import UTC

from submit_ce.domain.process import ProcessStatus
from submit_ce.domain.uploads import FileStatus
from submit_ce.ui.controllers.new.upload import group_files, tidy_filesize
from .tex_filters import compilation_log_display
from submit_ce.domain.compilation import Compilation


# additions for compilation log markup


def timesince(timestamp: datetime, default: str = "just now") -> str:
    """Format a :class:`datetime` as a relative duration in plain English."""
    diff = datetime.now(tz=UTC) - timestamp
    periods = (
        (diff.days / 365, "year", "years"),
        (diff.days / 30, "month", "months"),
        (diff.days / 7, "week", "weeks"),
        (diff.days, "day", "days"),
        (diff.seconds / 3600, "hour", "hours"),
        (diff.seconds / 60, "minute", "minutes"),
        (diff.seconds, "second", "seconds"),
    )
    for period, singular, plural in periods:
        if period > 1:
            return "%d %s ago" % (period, singular if period == 1 else plural)
    return default


def just_updated(status: FileStatus, seconds: int = 2) -> bool:
    """
    Filter to determine whether a specific file was just touched.

    Parameters
    ----------
    status : :class:`FileStatus`
        Represents the state of the uploaded file, as conveyed by the file
        management service.
    seconds : int
        Threshold number of seconds for determining whether a file was just
        touched.

    Returns
    -------
    bool

    Examples
    --------

    .. code-block:: html

       <p>
           This item
           {% if item|just_updated %}was just updated
           {% else %}has been sitting here for a while
           {% endif %}.
       </p>

    """
    now = datetime.now(tz=UTC)
    return abs((now - status.modified).seconds) < seconds


def get_category_name(category: str) -> str:
    """
    Get the display name for a category in the :mod:`base:taxonomy`.

    Parameters
    ----------
    category : str
        Canonical category ID, e.g. ``astro-ph.HE``.

    Returns
    -------
    str
        Display name for the category.

    Raises
    ------
    KeyError
        Raised if the specified category is not found in the active categories.

    """
    cat = taxonomy.definitions.CATEGORIES.get(category, None)
    if not cat:
        return "--Unknown Category--"
    else:
        return cat.full_name


def process_status_display(status: ProcessStatus.Status) -> str:
    if status is ProcessStatus.Status.REQUESTED:
        return "in progress"
    elif status is ProcessStatus.Status.FAILED:
        return "failed"
    elif status is ProcessStatus.Status.SUCCEEDED:
        return "suceeded"
    raise ValueError("Unknown status")


def compilation_status_display(status: Compilation.Status) -> str:
    if status is Compilation.Status.IN_PROGRESS:
        return "in progress"
    elif status is Compilation.Status.FAILED:
        return "failed"
    elif status is Compilation.Status.SUCCEEDED:
        return "suceeded"
    raise ValueError("Unknown status")


def group_preflight_files(files: list) -> OrderedDict:
    """Group preflight file dicts by directory, top-level files first then subdirs."""
    tree: dict = {}
    for f in files:
        path = Path(f['filename'])
        level = tree
        for p in reversed(path.parents):
            if str(p) == '.':
                continue
            level = level.setdefault(p.name, {})
        level[path.name] = f

    def _order(node: dict) -> OrderedDict:
        file_items = [(k, v) for k, v in node.items() if 'filename' in v]
        dir_items  = [(k, v) for k, v in node.items() if 'filename' not in v]
        ordered = OrderedDict()
        for k, v in sorted(file_items, key=lambda kv: strxfrm(kv[0].casefold())):
            ordered[k] = v
        for k, v in sorted(dir_items, key=lambda kv: strxfrm(kv[0].casefold())):
            ordered[k] = _order(v)
        return ordered

    return _order(tree)


def pluralize(number, singular="", plural="s"):
    if number == 1:
        return singular
    else:
        return plural

def get_filters() -> List[Tuple[str, Callable]]:
    """Get the filter functions available in this module."""
    return [
        ('group_files', group_files),
        ('timesince', timesince),
        ('just_updated', just_updated),
        ('get_category_name', get_category_name),
        ('process_status_display', process_status_display),
        ('compilation_status_display', compilation_status_display),
        ('tidy_filesize', tidy_filesize),
        ('asdict', asdict),
        ('compilation_log_display', compilation_log_display),
        ('pluralize', pluralize),
        ('group_preflight_files', group_preflight_files),
    ]
