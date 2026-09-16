"""The ``arxiv:errorcode`` table, ported from ``arXiv::AtomPP::Config``.

All 39 codes from ``arxiv-lib/lib/arXiv/AtomPP/Config.pm:76-198``. Ten of them
are absent from the published manual (which lists 29): the four non-power-of-two
category codes 8193-8196, and 2^29 through 2^34. Messages are transcribed
verbatim, typos included, because clients match on them -- ``03-cross.t`` asserts
on exact substrings.

Codes are powers of two so several can be OR'd together, except the 8193-8196
block which shares the 8192 "category element(s) invalid" family.

**HTTP status is a default, not a property of the code.** Legacy builds the
status separately from the error body: ``show_error`` falls back to 400 unless the
caller already set one (``AtomPP.pm:1530``). The same code can therefore appear
with different statuses -- ``EAUTH`` is 401 from the authorization gate
(``AtomPP.pm:184``) but 400 when posting to a collection the user lacks rights to
(``AtomPP.pm:222-227``), because that path sets no status. We default ``EAUTH`` to
401, since an authorization failure answering 400 is a legacy bug rather than a
contract; `SwordFault` takes an explicit ``status`` where a caller needs to match
legacy exactly.
"""

from dataclasses import dataclass
from typing import Optional

# SWORD's own error URIs (Config.pm:59-64).
_SWORD_ERROR = "http://purl.org/net/sword/error/"
E_CONTENT = _SWORD_ERROR + "ErrorContent"
E_CHECKSUM = _SWORD_ERROR + "ErrorChecksumMismatch"
E_BAD_REQUEST = _SWORD_ERROR + "ErrorBadRequest"
E_TARGET_OWNER_UNKNOWN = _SWORD_ERROR + "TargetOwnerUnknown"
E_MEDIATION_NOT_ALLOWED = _SWORD_ERROR + "MediationNotAllowed"
"""Defined in Config.pm:63 but never referenced by any error code."""

# arXiv help anchors (Config.pm:65-67). ``{site}`` is Perl's lowercased
# ``$THIS_SITE``.
E_LICENSE = "http://{site}/help/sword_errors#NeedLicenseApproval"
E_NOT_IMPLEMENTED = "http://{site}/help/sword_errors#NotImplemented"
E_UNKNOWN = "http://{site}/help/sword_errors#UnknownError"

UNKNOWN_ERROR_HREF = "http://arxiv.org/errors/UnknownError"
"""Used when a code carries no href (Error.pm:113).

Hardcoded to arxiv.org in the Perl -- it does *not* follow ``$THIS_SITE``.
"""


@dataclass(frozen=True)
class SwordErrorCode:
    """One row of the legacy ``%ECODES`` table."""

    mnemonic: str
    code: int
    message: str
    href_template: str
    status: int = 400

    def href(self, site: str) -> str:
        """Resolve the href, falling back the way Error.pm:113 does."""
        if not self.href_template:
            return UNKNOWN_ERROR_HREF
        return self.href_template.format(site=site.lower())


def _e(mnemonic, code, message, href, status=400) -> SwordErrorCode:
    return SwordErrorCode(mnemonic, code, message, href, status)


# Order follows Config.pm. Statuses other than 400 are the ones legacy sets
# explicitly; the anchor for each is noted.
_TABLE = [
    _e("EIMPL", 1, "method not supported", E_NOT_IMPLEMENTED, 501),          # AtomPP.pm:417,541
    _e("EVPRQ", 2, "unrecognized POST request", E_BAD_REQUEST),
    _e("EVGRQ", 4, "unrecognized GET request", E_BAD_REQUEST),
    _e("EGTPT", 8, "GET not supported for this request. Use POST instead", E_BAD_REQUEST),
    _e("EVCOL", 16, "invalid collection", E_CONTENT),
    _e("EOVLD", 32, "momentary overload. Try again in a few seconds", "", 503),  # AtomPP.pm:1263
    _e("ENAVL", 64, "service temporarily unavailable", "", 503),             # AtomPP.pm:258,501
    _e("ENNAM", 128, "No author name", E_CONTENT),
    _e("ENCML", 256, "No contact email", E_CONTENT),
    _e("EVCML", 512, "invalid contact email", E_CONTENT),
    _e("ENPCT", 1024, "No primary category specified", E_CONTENT),
    _e("EVPCT", 2048, "primary category invalid", E_CONTENT),
    _e("EMPCT", 4096, "more than one primary category specified", E_CONTENT),
    _e("EVCTS", 8192, "category element(s) invalid", E_CONTENT),
    _e("ENCTS", 8193, "new submissions may not exceed 4 secondary categories", E_CONTENT),
    _e("ERCTS", 8194,
       "replacement submissions must have no category elements or a set of "
       "category elements that matches the existing categories.", E_CONTENT),
    _e("EGCTS", 8195,
       "Crosses to general categories are not permitted in addition to other "
       "categories in the respective archives", E_CONTENT),
    _e("EGCCS", 8196,
       "Crosses are not permitted when the primary category is also a general "
       "category", E_CONTENT),
    _e("ENSUM", 16384,
       "No summary or summary too short. A summary is required metadata by arXiv",
       E_CONTENT),
    _e("ENTIT", 32768, "No title", E_CONTENT),
    _e("EVTIT", 65536, "title conflicting", ""),
    _e("EMDTP", 131072, "media type specified is not supported", E_CONTENT, 415),  # AtomPP.pm:278,312,478,483,910
    _e("ENMDE", 262144, "No media entries found in the author's workspace", E_BAD_REQUEST),
    _e("ENMDI", 524288, "No (media-) entry with specified/requested id", E_BAD_REQUEST),
    _e("EVMD5", 1048576, "MD5 sum did not match", E_CHECKSUM, 412),          # AtomPP.pm:252,495
    _e("EVLNK", 2097152, "link href could not be parsed", E_BAD_REQUEST),
    _e("ELKTP", 4194304, "MIME type of link could not be parsed", E_BAD_REQUEST),
    _e("ENREL", 8388608, 'No media entries with link attribute rel="related"', E_BAD_REQUEST),
    _e("UNKNW", 16777216, "unspecified error, contact the server administrator", ""),
    _e("EAUTH", 33554432, "Not Authorized", E_TARGET_OWNER_UNKNOWN, 401),    # AtomPP.pm:184
    _e("EBLOG", 67108864,
       '/edit called on invalid identifier or from link of rel="edit-media"',
       E_BAD_REQUEST),
    _e("ENOWN", 134217728, "No access, not the owner of the requested entry", E_BAD_REQUEST),
    _e("ENLIC", 268435456, "No valid license on file", E_LICENSE, 412),      # AtomPP.pm:192
    _e("ENOID", 536870912, "No ID for replacement", E_BAD_REQUEST),
    _e("ENVID", 1073741824, "Invalid ID for replacement", E_BAD_REQUEST),
    _e("EVXML", 2147483648, "XML does not validate", E_CONTENT),
    _e("EPSUB", 4294967296, "submission pending, not replaceable", E_BAD_REQUEST),
    # "ResouceMap" is misspelled in Config.pm:189 and kept verbatim. Unreachable
    # in this port: DCSIP/OAI-ORE support is out of scope.
    _e("ERESM", 8589934592, "OAI-ORE ResouceMap could not be parsed", E_CONTENT),
    _e("ETITL", 17179869184, "An item with identical title already exists.", E_CONTENT),
]
"""The legacy 39, and only those. Additions go in `_ADDITIONS`."""

_ADDITIONS = [
    _e("ESIZE", 34359738368, "deposit exceeds the maximum upload size",
       E_CONTENT, 413),
]
"""Codes with no counterpart in ``Config.pm``.

Kept separate so `_TABLE` stays a faithful transcription that
``test_errors.py`` can cross-check against ``Config.pm:76-198``.

``ESIZE`` covers an oversize deposit, for which legacy had no code at all. Its cap
was ``$CGI::POST_MAX`` (``AtomPP.pm:9``), enforced by CGI.pm *before* the SWORD
code ran: CGI.pm stopped reading, set ``$CGI::cgi_error`` to "413 Request entity
too large", and since nothing in ``arXiv::AtomPP`` ever checked that variable the
request continued with an empty body and failed further down as though the content
were malformed. There is therefore no legacy errorcode to be compatible with, and
overloading ``EMDTP`` -- "media type specified is not supported" -- would produce a
document that contradicts its own summary.

``34359738368`` is 2^35, continuing the powers-of-two sequence so the OR-ing that
the code numbers are designed for keeps working. 413 is the status CGI.pm named.
"""

_TABLE_BY_MNEMONIC: dict[str, SwordErrorCode] = {
    row.mnemonic: row for row in _TABLE}
"""The legacy transcription alone, so tests can pin it at exactly 39."""

ERRORS: dict[str, SwordErrorCode] = {
    row.mnemonic: row for row in _TABLE + _ADDITIONS}
BY_CODE: dict[int, SwordErrorCode] = {
    row.code: row for row in _TABLE + _ADDITIONS}


def lookup(mnemonic: str) -> SwordErrorCode:
    """Fetch a code by mnemonic.

    Error.pm:96-98 also accepts the literal integer 401 as an alias for EAUTH;
    callers here raise `SwordFault` directly, so that alias is not reproduced.
    """
    try:
        return ERRORS[mnemonic]
    except KeyError:
        raise KeyError(f"no such SWORD error mnemonic: {mnemonic!r}") from None


class SwordFault(Exception):
    """A SWORD error to be rendered as a ``<sword:error>`` document.

    ``detail`` becomes the ``": extra"`` suffix on the summary, exactly as
    Error.pm:107-111 builds it.
    """

    def __init__(self,
                 error: SwordErrorCode | str,
                 detail: str = "",
                 status: Optional[int] = None):
        self.error = lookup(error) if isinstance(error, str) else error
        self.detail = detail
        self.status = status if status is not None else self.error.status
        super().__init__(self.summary)

    @property
    def summary(self) -> str:
        """``message`` alone, or ``"message: detail"`` (Error.pm:107-111)."""
        if not self.detail:
            return self.error.message
        return f"{self.error.message}: {self.detail.rstrip(chr(10))}"
