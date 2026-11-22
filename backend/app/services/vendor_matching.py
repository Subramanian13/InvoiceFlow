import hashlib
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Vendor, VendorStatus
from app.schemas.extraction import VendorCandidate, VendorMatchResult
from app.services.normalization import normalize_tax_identifier, normalize_vendor_name


def tax_fingerprint(value: str) -> str:
    normalized = normalize_tax_identifier(value)
    return hashlib.sha256((normalized or "").encode()).hexdigest()


def match_vendor(db: Session, vendor_name: str | None, tax_identifier: str | None) -> VendorMatchResult:
    vendors = db.scalars(select(Vendor).options(selectinload(Vendor.aliases)).order_by(Vendor.vendor_code)).all()
    normalized_name = normalize_vendor_name(vendor_name)
    name_matches: list[tuple[Vendor, str]] = []
    for vendor in vendors:
        legal = normalize_vendor_name(vendor.legal_name)
        display = normalize_vendor_name(vendor.display_name)
        aliases = {alias.alias_normalized for alias in vendor.aliases}
        if normalized_name and normalized_name == legal:
            name_matches.append((vendor, "EXACT_LEGAL_NAME"))
        elif normalized_name and normalized_name == display:
            name_matches.append((vendor, "EXACT_DISPLAY_NAME"))
        elif normalized_name and normalized_name in aliases:
            name_matches.append((vendor, "APPROVED_ALIAS"))

    tax_match = None
    tax_conflict = False
    if tax_identifier:
        fingerprint = tax_fingerprint(tax_identifier)
        tax_match = next((v for v in vendors if v.tax_id_verified_in_master and v.tax_id_fingerprint == fingerprint), None)
        tax_name_agrees = not normalized_name or bool(tax_match and any(v.id == tax_match.id for v, _ in name_matches))
        tax_conflict = tax_match is None or not tax_name_agrees or (name_matches and any(v.id != tax_match.id for v, _ in name_matches))

    if tax_identifier and tax_conflict:
        candidates = [candidate(v, method, False) for v, method in name_matches]
        if tax_match:
            candidates.insert(0, candidate(tax_match, "VERIFIED_MASTER_TAX_ID", False))
        return VendorMatchResult(
            evidence=["An extracted tax identifier was compared only with verified vendor-master fingerprints."],
            conflict_codes=["TAX_IDENTIFIER_MISMATCH" if tax_match is None else "TAX_NAME_CONFLICT"], candidates=candidates,
        )

    if tax_match:
        if tax_match.status != VendorStatus.ACTIVE:
            return VendorMatchResult(conflict_codes=["VENDOR_INACTIVE"], candidates=[candidate(tax_match, "VERIFIED_MASTER_TAX_ID", False)])
        return VendorMatchResult(matched_vendor_id=tax_match.id, match_method="VERIFIED_MASTER_TAX_ID", automatic_match_permitted=True,
            evidence=["Extracted tax identifier matched a previously verified vendor-master fingerprint; no external verification was performed."],
            candidates=[candidate(tax_match, "VERIFIED_MASTER_TAX_ID", True)])

    if len(name_matches) == 1:
        vendor, method = name_matches[0]
        if vendor.status != VendorStatus.ACTIVE:
            return VendorMatchResult(conflict_codes=["VENDOR_INACTIVE"], candidates=[candidate(vendor, method, False)])
        return VendorMatchResult(matched_vendor_id=vendor.id, match_method=method, automatic_match_permitted=True,
            evidence=[f"Normalized invoice vendor name matched by {method.lower().replace('_', ' ')}."], candidates=[candidate(vendor, method, True)])
    if len(name_matches) > 1:
        return VendorMatchResult(conflict_codes=["AMBIGUOUS_VENDOR_IDENTITY"], candidates=[candidate(v, m, False) for v, m in name_matches])

    fuzzy: list[VendorCandidate] = []
    if normalized_name:
        for vendor in vendors:
            comparisons = [normalize_vendor_name(vendor.legal_name), normalize_vendor_name(vendor.display_name), *[a.alias_normalized for a in vendor.aliases]]
            score = max(SequenceMatcher(None, normalized_name, item or "").ratio() for item in comparisons)
            if score >= 0.55:
                fuzzy.append(candidate(vendor, "FUZZY_NAME_SUGGESTION", False, score))
    fuzzy.sort(key=lambda item: item.similarity or 0, reverse=True)
    return VendorMatchResult(conflict_codes=["FUZZY_VENDOR_MATCH_REQUIRES_REVIEW" if fuzzy else "VENDOR_NOT_FOUND"], candidates=fuzzy[:3])


def candidate(vendor: Vendor, method: str, automatic: bool, similarity: float | None = None) -> VendorCandidate:
    return VendorCandidate(vendor_id=vendor.id, vendor_code=vendor.vendor_code, legal_name=vendor.legal_name,
        match_method=method, evidence=[f"Candidate master record {vendor.vendor_code}: {vendor.legal_name}."],
        automatic_match_permitted=automatic, similarity=round(similarity, 3) if similarity is not None else None)

