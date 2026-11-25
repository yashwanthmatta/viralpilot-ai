from vp_agents import rights
from vp_shared.models import LicenseType as L


def test_unknown_licence_rejected():
    assert not rights.evaluate(L.unknown, "https://example.com").allowed


def test_missing_evidence_rejected():
    assert not rights.evaluate(L.user_owned, "  ").allowed


def test_cc_by_needs_attribution():
    assert not rights.evaluate(L.cc_by, "https://creativecommons.org/licenses/by/4.0/").allowed
    assert rights.evaluate(L.cc_by, "https://creativecommons.org/licenses/by/4.0/", "Jane Doe").allowed


def test_licence_urls():
    assert rights.license_from_url("https://creativecommons.org/licenses/by/4.0/") == L.cc_by
    assert rights.license_from_url("https://creativecommons.org/licenses/by-sa/4.0/") == L.cc_by_sa
    assert rights.license_from_url("https://creativecommons.org/publicdomain/zero/1.0/") == L.cc0
    # Non-commercial and no-derivatives licences must never be accepted.
    assert rights.license_from_url("https://creativecommons.org/licenses/by-nc/4.0/") == L.unknown
    assert rights.license_from_url("https://creativecommons.org/licenses/by-nd/4.0/") == L.unknown
    assert rights.license_from_url("https://creativecommons.org/licenses/by-nc-sa/4.0/") == L.unknown
    assert rights.license_from_url("All rights reserved") == L.unknown
