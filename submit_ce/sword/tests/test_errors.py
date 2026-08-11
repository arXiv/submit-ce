"""The error table must match ``arXiv::AtomPP::Config`` exactly.

The expected code numbers below are transcribed independently of
`submit_ce.sword.errors` (from ``Config.pm:76-198`` and the manual's table at
``submit_sword.md:810-841``) so this is a real cross-check of the port rather
than a restatement of it. These numbers are the machine-readable half of the
contract: clients switch on ``arxiv:errorcode``.
"""

import pytest

from submit_ce.sword import errors
from submit_ce.sword.errors import SwordFault

# mnemonic -> arxiv:errorcode
EXPECTED_CODES = {
    "EIMPL": 1,
    "EVPRQ": 2,
    "EVGRQ": 4,
    "EGTPT": 8,
    "EVCOL": 16,
    "EOVLD": 32,
    "ENAVL": 64,
    "ENNAM": 128,
    "ENCML": 256,
    "EVCML": 512,
    "ENPCT": 1024,
    "EVPCT": 2048,
    "EMPCT": 4096,
    "EVCTS": 8192,
    "ENCTS": 8193,
    "ERCTS": 8194,
    "EGCTS": 8195,
    "EGCCS": 8196,
    "ENSUM": 16384,
    "ENTIT": 32768,
    "EVTIT": 65536,
    "EMDTP": 131072,
    "ENMDE": 262144,
    "ENMDI": 524288,
    "EVMD5": 1048576,
    "EVLNK": 2097152,
    "ELKTP": 4194304,
    "ENREL": 8388608,
    "UNKNW": 16777216,
    "EAUTH": 33554432,
    "EBLOG": 67108864,
    "ENOWN": 134217728,
    "ENLIC": 268435456,
    "ENOID": 536870912,
    "ENVID": 1073741824,
    "EVXML": 2147483648,
    "EPSUB": 4294967296,
    "ERESM": 8589934592,
    "ETITL": 17179869184,
}

# Only the codes where legacy sets a status other than the 400 default.
EXPECTED_NON_400 = {
    "EIMPL": 501,
    "EOVLD": 503,
    "ENAVL": 503,
    "EMDTP": 415,
    "EVMD5": 412,
    "EAUTH": 401,
    "ENLIC": 412,
    "ESIZE": 413,      # an addition, not from Config.pm -- see ADDITIONS below
}

ADDITIONS = {
    "ESIZE": 34359738368,
}
"""Codes with no counterpart in ``Config.pm``.

Listed here so an addition has to be made deliberately: the assertions below keep
the legacy transcription pinned at exactly 39, and anything extra must be declared
in this dict to pass.
"""


def test_all_thirty_nine_legacy_codes_present():
    """The transcription still matches ``Config.pm`` exactly."""
    assert set(errors._TABLE_BY_MNEMONIC) == set(EXPECTED_CODES)
    assert len(errors._TABLE_BY_MNEMONIC) == 39


def test_additions_are_declared_and_do_not_collide():
    assert set(errors.ERRORS) == set(EXPECTED_CODES) | set(ADDITIONS)
    for mnemonic, code in ADDITIONS.items():
        assert errors.ERRORS[mnemonic].code == code
        assert code not in set(EXPECTED_CODES.values())


def test_esize_continues_the_power_of_two_sequence():
    """The numbers are OR-able, so an addition must not break that."""
    largest_legacy = max(EXPECTED_CODES.values())
    assert errors.ERRORS["ESIZE"].code == largest_legacy * 2


@pytest.mark.parametrize("mnemonic,code", sorted(EXPECTED_CODES.items()))
def test_code_number(mnemonic, code):
    assert errors.ERRORS[mnemonic].code == code


def test_codes_are_unique():
    codes = [row.code for row in errors.ERRORS.values()]
    assert len(codes) == len(set(codes))


def test_ten_codes_are_absent_from_the_published_manual():
    """The manual documents 2^0..2^28 only; these are the extras."""
    undocumented = {"ENCTS", "ERCTS", "EGCTS", "EGCCS",
                    "ENOID", "ENVID", "EVXML", "EPSUB", "ERESM", "ETITL"}
    assert undocumented <= set(errors.ERRORS)
    documented_max = 2 ** 28  # ENLIC, the last one in the manual's table
    assert all(errors.ERRORS[m].code > documented_max
               or errors.ERRORS[m].code in (8193, 8194, 8195, 8196)
               for m in undocumented)


@pytest.mark.parametrize("mnemonic,status", sorted(EXPECTED_NON_400.items()))
def test_non_default_status(mnemonic, status):
    assert errors.ERRORS[mnemonic].status == status


def test_everything_else_defaults_to_400():
    for mnemonic, row in errors.ERRORS.items():
        if mnemonic not in EXPECTED_NON_400:
            assert row.status == 400, mnemonic


def test_by_code_lookup():
    assert errors.BY_CODE[512] is errors.ERRORS["EVCML"]


def test_lookup_rejects_unknown_mnemonic():
    with pytest.raises(KeyError, match="no such SWORD error mnemonic"):
        errors.lookup("NOPE")


# ---------------------------------------------------------------- href values


def test_sword_error_hrefs_are_the_purl_uris():
    assert errors.ERRORS["EVMD5"].href("arxiv.org") == \
        "http://purl.org/net/sword/error/ErrorChecksumMismatch"
    assert errors.ERRORS["EVCOL"].href("arxiv.org") == \
        "http://purl.org/net/sword/error/ErrorContent"
    assert errors.ERRORS["EAUTH"].href("arxiv.org") == \
        "http://purl.org/net/sword/error/TargetOwnerUnknown"


def test_site_is_interpolated_and_lowercased():
    assert errors.ERRORS["ENLIC"].href("ArXiv.ORG") == \
        "http://arxiv.org/help/sword_errors#NeedLicenseApproval"
    assert errors.ERRORS["EIMPL"].href("export.arxiv.org") == \
        "http://export.arxiv.org/help/sword_errors#NotImplemented"


def test_codes_without_an_href_fall_back():
    """Error.pm:113 substitutes a fixed arxiv.org URL, ignoring THIS_SITE."""
    for mnemonic in ("EOVLD", "ENAVL", "EVTIT", "UNKNW"):
        assert errors.ERRORS[mnemonic].href("example.org") == \
            "http://arxiv.org/errors/UnknownError", mnemonic


def test_every_href_is_http_not_https():
    for mnemonic, row in errors.ERRORS.items():
        href = row.href("arxiv.org")
        assert href.startswith("http://"), mnemonic
        assert not href.startswith("https://"), mnemonic


# ------------------------------------------------------------------- summary


def test_summary_without_detail_is_the_bare_message():
    assert SwordFault("ENCTS").summary == \
        "new submissions may not exceed 4 secondary categories"


def test_summary_with_detail_is_colon_joined():
    """Error.pm:107-111."""
    fault = SwordFault("EVCOL", "foobar")
    assert fault.summary == "invalid collection: foobar"


def test_summary_strips_a_trailing_newline_from_detail():
    """The Perl chomps ``$extrainfo`` before appending it."""
    assert SwordFault("EVCOL", "foobar\n").summary == "invalid collection: foobar"


def test_status_can_be_overridden_for_legacy_parity():
    """EAUTH answers 400 on one legacy path; a caller can still ask for that."""
    assert SwordFault("EAUTH").status == 401
    assert SwordFault("EAUTH", status=400).status == 400


def test_fault_accepts_a_code_object_as_well_as_a_mnemonic():
    fault = SwordFault(errors.ERRORS["ENLIC"])
    assert fault.error.code == 268435456
    assert fault.status == 412


# --------------------------------------- exact strings the Perl suite asserts


def test_messages_asserted_by_03_cross_t():
    """Substrings ``arxiv-lib/t/arxiv_atompp/03-cross.t`` matches on."""
    gen_ph = SwordFault("EVCTS", "cross to 'physics.gen-ph' not allowed")
    assert "category element(s) invalid: cross to 'physics.gen-ph' not allowed" \
        in gen_ph.summary

    assert "new submissions may not exceed 4 secondary categories" \
        in SwordFault("ENCTS").summary

    assert ("Crosses to general categories are not permitted in addition to "
            "other categories in the respective archives") in SwordFault("EGCTS").summary

    assert ("Crosses are not permitted when the primary category is also a "
            "general category") in SwordFault("EGCCS").summary

    assert "no such category: 'cond-mat'" \
        in SwordFault("EVCTS", "no such category: 'cond-mat'").summary


def test_code_asserted_by_04_suspect_t():
    """``04-suspect.t`` asserts ``errorcode>512`` for a suspect contributor."""
    assert errors.ERRORS["EVCML"].code == 512
    fault = SwordFault("EVCML", "arXiv does not accept third party submission "
                                "for author, they must submit directly")
    assert "must submit directly" in fault.summary
