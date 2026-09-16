"""SWORD request-header parsing and checksum verification.

Ports ``process_sword_headers`` (``AtomPP.pm:849-915``) and the MD5 checks
(``AtomPP.pm:1501-1510``).
"""

import base64
import hashlib

import pytest

from submit_ce.sword.errors import SwordFault
from submit_ce.sword.request import (
    is_no_op,
    parse_deposit_headers,
    parse_disposition_filename,
    parse_on_behalf_of,
    verify_md5,
)

PAYLOAD = b"a zip file, allegedly"


# --------------------------------------------------------------- X-On-Behalf-Of


def test_name_and_address_are_split():
    """The format the manual documents (submit_sword.md:524)."""
    name, email = parse_on_behalf_of('"A. Scientist" <ascientist@institution.edu>')
    assert name == "A. Scientist"
    assert email == "ascientist@institution.edu"


def test_unquoted_display_name():
    name, email = parse_on_behalf_of("A Scientist <a@example.org>")
    assert name == "A Scientist"
    assert email == "a@example.org"


def test_bare_address_has_an_empty_name():
    name, email = parse_on_behalf_of("a@example.org")
    assert name == ""
    assert email == "a@example.org"


@pytest.mark.parametrize("value", ["", "not an email", "A. Scientist", "<>"])
def test_unusable_on_behalf_of_is_evcml(value):
    with pytest.raises(SwordFault) as excinfo:
        parse_on_behalf_of(value)
    assert excinfo.value.error.mnemonic == "EVCML"
    assert excinfo.value.error.code == 512
    assert "X-On-Behalf-Of header must have" in excinfo.value.summary


def test_address_validation_does_not_query_dns():
    """Deliverability checks would put a DNS lookup in every deposit path.

    A domain that does not resolve must still parse. If DNS were being consulted
    this would fail -- and under the suite's socket guard it would fail loudly.
    """
    address = "someone@no-such-domain-xyz123456.com"
    _, email = parse_on_behalf_of(address)
    assert email == address


@pytest.mark.parametrize("address", [
    "someone@example.invalid",
    "someone@host.localhost",
    "someone@thing.test",
])
def test_reserved_domains_are_refused(address):
    """Stricter than legacy, deliberately.

    ``Email::Valid->address`` is syntax-only, so legacy accepted RFC 2606
    special-use domains. They cannot receive mail, and the contact address exists
    precisely so arXiv can send the identifier and paper password
    (``submit_sword.md:68-72``) -- accepting one guarantees that never arrives.
    """
    with pytest.raises(SwordFault) as excinfo:
        parse_on_behalf_of(address)
    assert excinfo.value.error.mnemonic == "EVCML"


# ------------------------------------------------------------------- X-No-Op


def test_no_op_absent_is_off():
    assert is_no_op(None) is False


@pytest.mark.parametrize("value", ["True", "true", "1", "yes", "", "  "])
def test_any_value_but_false_enables_no_op(value):
    """AtomPP.pm:896-901 -- even an empty header switches it on."""
    assert is_no_op(value) is True


@pytest.mark.parametrize("value", ["false", "False", "FALSE", " false "])
def test_literal_false_disables_no_op(value):
    assert is_no_op(value) is False


# -------------------------------------------------------- Content-Disposition


def test_filename_is_extracted():
    assert parse_disposition_filename('attachment; filename=paper.zip') == \
        "paper.zip"


def test_disposition_without_a_filename():
    assert parse_disposition_filename("attachment") is None
    assert parse_disposition_filename(None) is None


def test_non_ascii_filename_is_reduced_to_its_ascii_run():
    """Legacy keeps only the ASCII portion (AtomPP.pm:862-864)."""
    assert parse_disposition_filename("attachment; filename=café.zip") == "caf"


# ------------------------------------------------------------------ packaging


def test_bagit_packaging_is_accepted():
    headers = parse_deposit_headers({
        "Content-Type": "application/zip",
        "X-Packaging": "http://purl.org/net/sword-types/bagit"})
    assert headers.packaging == "http://purl.org/net/sword-types/bagit"


def test_zipit_packaging_is_accepted():
    headers = parse_deposit_headers({
        "Content-Type": "application/zip",
        "X-Packaging": "http://arxiv.org/schemas/zipit"})
    assert headers.packaging == "http://arxiv.org/schemas/zipit"


def test_mets_dspace_packaging_is_refused():
    """Config.pm:201 maps it to 0, which AtomPP.pm:907 treats as unsupported."""
    with pytest.raises(SwordFault) as excinfo:
        parse_deposit_headers({
            "Content-Type": "application/zip",
            "X-Packaging": "http://purl.org/net/sword-types/mets/dspace"})
    assert excinfo.value.status == 415


def test_dataconservancy_packaging_is_refused():
    """Truthy in legacy, but its handler is dead code (plan decision 2)."""
    with pytest.raises(SwordFault) as excinfo:
        parse_deposit_headers({
            "Content-Type": "application/zip",
            "X-Packaging": "http://datapub.dataconservancy.org/package"})
    assert excinfo.value.status == 415


def test_unknown_packaging_is_refused():
    with pytest.raises(SwordFault):
        parse_deposit_headers({"Content-Type": "application/zip",
                               "X-Packaging": "http://example.org/whatever"})


# ------------------------------------------------------------- header assembly


def test_minimal_headers():
    headers = parse_deposit_headers({"Content-Type": "application/zip"})
    assert headers.content_type == "application/zip"
    assert headers.md5 is None
    assert headers.contact_email is None
    assert headers.verbose is False
    assert headers.no_op is False
    assert headers.packaging is None


def test_full_headers():
    headers = parse_deposit_headers({
        "Content-Type": "application/zip",
        "Content-MD5": "abc==",
        "X-On-Behalf-Of": '"A. Scientist" <a@example.org>',
        "X-Verbose": "True",
        "X-No-Op": "True",
        "X-Packaging": "http://purl.org/net/sword-types/bagit",
        "User-Agent": "arXiv SWORD demo 1.1",
        "Content-Disposition": "attachment; filename=paper.zip",
    })
    assert headers.md5 == "abc=="
    assert headers.contact_name == "A. Scientist"
    assert headers.contact_email == "a@example.org"
    assert headers.verbose is True
    assert headers.no_op is True
    assert headers.user_agent == "arXiv SWORD demo 1.1"
    assert headers.filename == "paper.zip"


def test_empty_on_behalf_of_is_treated_as_absent():
    headers = parse_deposit_headers({"Content-Type": "application/zip",
                                     "X-On-Behalf-Of": ""})
    assert headers.on_behalf_of is None
    assert headers.contact_email is None


def test_content_type_parameters_are_preserved():
    """The value is echoed verbatim into the response entry's summary."""
    headers = parse_deposit_headers(
        {"Content-Type": "application/atom+xml;type=entry"})
    assert headers.content_type == "application/atom+xml;type=entry"


# ----------------------------------------------------------------- Content-MD5


def test_no_checksum_supplied_is_accepted():
    verify_md5(PAYLOAD, None)
    verify_md5(PAYLOAD, "")


def test_base64_checksum_is_accepted():
    digest = base64.b64encode(hashlib.md5(PAYLOAD).digest()).decode()
    verify_md5(PAYLOAD, digest)


def test_hex_checksum_is_accepted():
    """AtomPP.pm:1507 also accepts the lowercase hex digest."""
    verify_md5(PAYLOAD, hashlib.md5(PAYLOAD).hexdigest())


def test_uppercase_hex_checksum_is_accepted():
    """check_md5hex lowercases the supplied value before comparing."""
    verify_md5(PAYLOAD, hashlib.md5(PAYLOAD).hexdigest().upper())


def test_mismatched_checksum_is_412():
    with pytest.raises(SwordFault) as excinfo:
        verify_md5(PAYLOAD, "0" * 32)
    assert excinfo.value.error.mnemonic == "EVMD5"
    assert excinfo.value.status == 412
    assert excinfo.value.summary == "MD5 sum did not match"


def test_checksum_of_different_content_is_refused():
    digest = base64.b64encode(hashlib.md5(b"something else").digest()).decode()
    with pytest.raises(SwordFault):
        verify_md5(PAYLOAD, digest)
