"""The depositor client must build the requests a real client sends.

Request construction is tested against a recording stub rather than a server, so
these hold before any SWORD route exists. Reference: ``Test::Sword.pm:96-110``
for the headers and ``:144-156`` for the response parsing.
"""

import base64
import hashlib
from dataclasses import dataclass, field

import pytest

from submit_ce.sword.atom.render import render_error
from submit_ce.sword.errors import SwordFault
from submit_ce.sword.tests import client as sword_client
from submit_ce.sword.tests.client import (
    ATOM_ENTRY_TYPE,
    SwordClient,
    basic_auth,
    content_md5,
    content_md5_hex,
    deposit_headers,
)

PAYLOAD = b"a zip file, allegedly"


@dataclass
class RecordingHttp:
    """Captures calls instead of issuing them."""

    calls: list = field(default_factory=list)

    def _record(self, method, url, content=None, headers=None):
        self.calls.append({"method": method, "url": url,
                           "content": content, "headers": headers or {}})
        return "response"

    def get(self, url, headers=None):
        return self._record("GET", url, headers=headers)

    def post(self, url, content=None, headers=None):
        return self._record("POST", url, content=content, headers=headers)

    def put(self, url, content=None, headers=None):
        return self._record("PUT", url, content=content, headers=headers)


@pytest.fixture
def http():
    return RecordingHttp()


@pytest.fixture
def client(http):
    return SwordClient(http=http, username="vtex", password="s3cret")


# --------------------------------------------------------------- Content-MD5


def test_content_md5_is_padded_base64():
    digest = content_md5(PAYLOAD)
    assert digest == base64.b64encode(hashlib.md5(PAYLOAD).digest()).decode()
    assert digest.endswith("==")
    assert len(digest) == 24


def test_content_md5_matches_the_perl_construction():
    """Perl builds unpadded base64 then appends '==' (Test::Sword.pm:105)."""
    unpadded = base64.b64encode(hashlib.md5(PAYLOAD).digest()).decode().rstrip("=")
    assert content_md5(PAYLOAD) == unpadded + "=="


def test_content_md5_hex_is_lowercase():
    """The server accepts hex as well as base64 (AtomPP.pm:1507)."""
    assert content_md5_hex(PAYLOAD) == hashlib.md5(PAYLOAD).hexdigest()
    assert content_md5_hex(PAYLOAD).islower()


# ------------------------------------------------------------------- headers


def test_only_content_type_and_user_agent_by_default():
    headers = deposit_headers(content_type="application/zip")
    assert headers == {"Content-Type": "application/zip",
                       "User-Agent": "arXiv SWORD demo 1.1"}


def test_optional_headers_are_omitted_not_blank():
    """An empty ``X-No-Op`` would switch no-op ON (AtomPP.pm:896-901)."""
    headers = deposit_headers(content_type="application/zip")
    for name in ("X-No-Op", "X-Verbose", "X-On-Behalf-Of", "X-Packaging",
                 "Content-MD5"):
        assert name not in headers


def test_all_sword_headers_when_asked():
    headers = deposit_headers(
        content_type="application/zip",
        md5="p1T0tIZT/JyAgwevT+zHKw==",
        on_behalf_of='"A. Scientist" <ascientist@institution.edu>',
        verbose=True,
        no_op=True,
        packaging="http://purl.org/net/sword-types/bagit",
    )
    assert headers["Content-MD5"] == "p1T0tIZT/JyAgwevT+zHKw=="
    assert headers["X-On-Behalf-Of"] == '"A. Scientist" <ascientist@institution.edu>'
    assert headers["X-Verbose"] == "True"
    assert headers["X-No-Op"] == "True"
    assert headers["X-Packaging"] == "http://purl.org/net/sword-types/bagit"


def test_basic_auth_encodes_nickname_and_password():
    value = basic_auth("vtex", "s3cret")
    assert value.startswith("Basic ")
    decoded = base64.b64decode(value.split(" ", 1)[1]).decode()
    assert decoded == "vtex:s3cret"


def test_basic_auth_is_case_sensitive_in_the_username():
    """submit_sword.md:726-727 -- the authenticated username is case-sensitive."""
    assert basic_auth("vtex", "x") != basic_auth("VTEX", "x")


# -------------------------------------------------------------- request shapes


def test_collection_url_shape(client):
    assert client.collection_url("cs") == "/sword-app/cs-collection"


def test_service_document_request(client, http):
    client.service_document()
    call = http.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "/sword-app/servicedocument"
    assert call["headers"]["Authorization"].startswith("Basic ")
    assert "X-On-Behalf-Of" not in call["headers"]


def test_service_document_mediated(client, http):
    client.service_document(on_behalf_of="someone")
    assert http.calls[0]["headers"]["X-On-Behalf-Of"] == "someone"


def test_media_deposit_posts_payload_to_the_collection(client, http):
    client.deposit_media("cs", PAYLOAD, content_type="application/zip",
                         md5=content_md5(PAYLOAD))
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "/sword-app/cs-collection"
    assert call["content"] == PAYLOAD
    assert call["headers"]["Content-Type"] == "application/zip"
    assert call["headers"]["Content-MD5"] == content_md5(PAYLOAD)
    assert call["headers"]["Authorization"].startswith("Basic ")


def test_wrapper_deposit_uses_the_atom_entry_content_type(client, http):
    client.deposit_wrapper("cs", b"<entry/>")
    call = http.calls[0]
    assert call["headers"]["Content-Type"] == ATOM_ENTRY_TYPE
    assert call["url"] == "/sword-app/cs-collection"
    assert call["content"] == b"<entry/>"


def test_replace_puts_to_the_edit_href(client, http):
    client.replace("/sword-app/edit/09031234.atom", b"<entry/>")
    call = http.calls[0]
    assert call["method"] == "PUT"
    assert call["url"] == "/sword-app/edit/09031234.atom"
    assert call["headers"]["Content-Type"] == ATOM_ENTRY_TYPE


def test_deposit_forwards_optional_headers(client, http):
    client.deposit_media("cs", PAYLOAD, content_type="application/pdf",
                         on_behalf_of="author@example.org", no_op=True)
    headers = http.calls[0]["headers"]
    assert headers["X-On-Behalf-Of"] == "author@example.org"
    assert headers["X-No-Op"] == "True"


# ----------------------------------------------------------- response parsing

MEDIA_RESPONSE = b"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:sword="http://purl.org/net/sword/">
  <id>info:arxiv/app/08050001</id>
  <link rel="edit-media" href="https://arxiv.org/sword-app/edit/08050001"/>
  <link rel="edit" href="https://arxiv.org/sword-app/edit/08050001.atom"/>
  <link rel="alternate" href="http://arxiv.org/resolve/app/08050001"/>
</entry>
"""


def test_edit_media_link_is_extracted():
    """The value a wrapper's rel="related" link must carry."""
    assert sword_client.edit_media_link(MEDIA_RESPONSE) == \
        "https://arxiv.org/sword-app/edit/08050001"


def test_edit_and_alternate_links_are_extracted():
    assert sword_client.edit_link(MEDIA_RESPONSE) == \
        "https://arxiv.org/sword-app/edit/08050001.atom"
    assert sword_client.alternate_link(MEDIA_RESPONSE) == \
        "http://arxiv.org/resolve/app/08050001"


def test_missing_rel_returns_none():
    assert sword_client.edit_media_link(b'<entry xmlns="http://www.w3.org/2005/Atom"/>') is None


def test_entry_id_and_sword_id():
    assert sword_client.entry_id(MEDIA_RESPONSE) == "info:arxiv/app/08050001"
    assert sword_client.sword_id(MEDIA_RESPONSE) == 8050001


def test_sword_id_is_none_for_a_non_numeric_id():
    document = b'<entry xmlns="http://www.w3.org/2005/Atom"><id>arxiv:test::meta</id></entry>'
    assert sword_client.sword_id(document) is None


def test_error_code_and_summary_round_trip_our_own_renderer():
    document = render_error(SwordFault("EVCOL", "foobar"), site="arxiv.org")
    assert sword_client.error_code(document) == 16
    assert sword_client.error_summary(document) == "invalid collection: foobar"
