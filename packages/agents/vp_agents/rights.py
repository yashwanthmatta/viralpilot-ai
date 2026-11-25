"""Rights gate (part of the Content Acquisition and QC agents).

Default deny. A piece of content is eligible for commercial clipping and
redistribution only when:

* its licence is one of the allowed types below, and
* there is written evidence of that licence (a licence URL, a permission
  record, or the user's own-content declaration), and
* for licences that require credit, an attribution string is present.

"Publicly viewable" is NOT a licence. Anything unclear is rejected.
"""
from __future__ import annotations

from dataclasses import dataclass

from vp_shared.models import LicenseType

ALLOWED = {
    LicenseType.user_owned,
    LicenseType.creator_authorized,
    LicenseType.cc_by,
    LicenseType.cc_by_sa,
    LicenseType.cc0,
    LicenseType.public_domain,
    LicenseType.licensed_library,
}

NEEDS_ATTRIBUTION = {LicenseType.cc_by, LicenseType.cc_by_sa}

# Creative Commons licence URLs we recognise in feeds. NC (non-commercial)
# and ND (no-derivatives) licences are deliberately absent: clipping is a
# derivative and monetised channels are commercial.
_CC_URL_MAP = {
    "creativecommons.org/licenses/by/": LicenseType.cc_by,
    "creativecommons.org/licenses/by-sa/": LicenseType.cc_by_sa,
    "creativecommons.org/publicdomain/zero/": LicenseType.cc0,
    "creativecommons.org/publicdomain/mark/": LicenseType.public_domain,
}


@dataclass(frozen=True)
class RightsDecision:
    allowed: bool
    license_type: LicenseType
    reason: str


def license_from_url(url: str) -> LicenseType:
    u = (url or "").lower()
    if "-nc" in u or "-nd" in u or "/nc" in u or "/nd" in u:
        return LicenseType.unknown
    for needle, lic in _CC_URL_MAP.items():
        if needle in u:
            return lic
    return LicenseType.unknown


def evaluate(license_type: LicenseType, evidence: str, attribution: str = "") -> RightsDecision:
    if license_type not in ALLOWED:
        return RightsDecision(False, license_type, f"licence '{license_type.value}' does not permit commercial reuse")
    if not (evidence or "").strip():
        return RightsDecision(False, license_type, "no written evidence of the licence")
    if license_type in NEEDS_ATTRIBUTION and not (attribution or "").strip():
        return RightsDecision(False, license_type, "licence requires attribution but none is recorded")
    return RightsDecision(True, license_type, f"allowed under {license_type.value}: {evidence.strip()[:200]}")
