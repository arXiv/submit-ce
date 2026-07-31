"""XML namespaces, category schemes and version strings for arXiv SWORD.

Ported from ``arxiv-lib/lib/arXiv/AtomPP/Config.pm:50-57``.

**Every namespace URI is ``http://``, not ``https://``.** The published manual
(``arxiv-docs/source/help/submit_sword.md``) renders them with ``https``, but
that is an artifact of a docs-wide http->https rewrite; the wire format is and
always has been ``http``, and clients match on the literal string. The live
regression suite asserts the ``http`` form -- see
``arxiv-test-regression/pytest/tests/test_sword.py:67-68``. Changing these
breaks every existing depositor.
"""

ATOM = "http://www.w3.org/2005/Atom"
SWORD = "http://purl.org/net/sword/"
DCTERMS = "http://purl.org/dc/terms/"
ARXIV = "http://arxiv.org/schemas/atom/"

ARXIV_SCHEME = "http://arxiv.org/terms/arXiv/"
"""Scheme for arXiv categories; also the prefix on every category ``term``."""

MSC_SCHEME = "http://arxiv.org/terms/MSC2000"
ACM_SCHEME = "http://arxiv.org/terms/ACM1998"

SWORD_VERSION = "1.3"
"""Value of ``<sword:version>`` in the service document (ServiceDoc.pm:57-58).

The ticket says "SWORD 1.0"; the wire format is the v1 APP Profile 1.3.
"""

GENERATOR_VERSION = "1.1"
"""``version`` attribute on ``<generator>`` (Config.pm:46).

The manual's examples show ``0.9``; the code has emitted ``1.1`` for years.
"""

GENERATOR_NAME = "SWORD@arXiv.org"
ERROR_AUTHOR_NAME = "SWORD@arXiv"

NSMAP = {None: ATOM, "sword": SWORD, "arxiv": ARXIV}
"""Default prefix bindings: unprefixed elements are Atom.

Matches the legacy documents, whose root carries ``xmlns`` (Atom) plus
``xmlns:sword`` and ``xmlns:arxiv``.
"""


def qname(namespace: str, tag: str) -> str:
    """Build an lxml-style qualified name, e.g. ``{http://...}entry``."""
    return f"{{{namespace}}}{tag}"
