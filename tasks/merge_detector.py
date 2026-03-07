"""Detect asset items that likely refer to the same asset across snapshots."""

from difflib import SequenceMatcher

from db import queries


def _normalize(s: str) -> str:
    """Lowercase, strip whitespace and common suffixes."""
    s = (s or "").strip().lower()
    # Remove common suffixes that don't help matching
    for suffix in [" acc", " dist", " ucits", " etf", " fund", " (acc)", " (dist)"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    return s


def _similar(a: str, b: str) -> float:
    """Return similarity ratio between 0 and 1."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def detect_overlaps() -> list[dict]:
    """Find pairs of asset items that likely refer to the same asset.

    Returns list of dicts with keys:
        asset_name_a, ticker_a, asset_name_b, ticker_b, reason
    """
    assets = queries.get_all_unique_assets()
    asset_list = [dict(a) for a in assets]
    suggestions = []
    seen_pairs = set()

    for i, a in enumerate(asset_list):
        for j, b in enumerate(asset_list):
            if j <= i:
                continue

            name_a = a.get("asset_name") or ""
            name_b = b.get("asset_name") or ""
            ticker_a = (a.get("ticker") or "").strip().upper()
            ticker_b = (b.get("ticker") or "").strip().upper()

            # Skip if both are empty
            if not name_a and not name_b:
                continue

            pair_key = tuple(sorted([name_a.lower(), name_b.lower()]))
            if pair_key in seen_pairs:
                continue

            reason = None

            # 1. Same ticker (non-empty) but different names
            if ticker_a and ticker_b and ticker_a == ticker_b and name_a != name_b:
                reason = f"Same ticker ({ticker_a}) with different names"

            # 2. Very similar names (>0.8 similarity)
            elif name_a and name_b and _similar(name_a, name_b) > 0.8 and name_a != name_b:
                ratio = _similar(name_a, name_b)
                reason = f"Similar names ({ratio:.0%} match)"

            # 3. One name contains the other
            elif name_a and name_b and name_a != name_b:
                na, nb = _normalize(name_a), _normalize(name_b)
                if len(na) > 3 and len(nb) > 3:
                    if na in nb or nb in na:
                        reason = "One name is a substring of the other"

            # 4. Same ticker prefix with different suffixes (e.g. VUAA vs VUAA.L)
            if not reason and ticker_a and ticker_b and ticker_a != ticker_b:
                base_a = ticker_a.split(".")[0]
                base_b = ticker_b.split(".")[0]
                if base_a == base_b and len(base_a) >= 2:
                    reason = f"Same ticker base ({base_a}) with different suffixes"

            if reason:
                seen_pairs.add(pair_key)
                suggestions.append({
                    "asset_name_a": name_a,
                    "ticker_a": a.get("ticker"),
                    "asset_name_b": name_b,
                    "ticker_b": b.get("ticker"),
                    "reason": reason,
                })

    return suggestions


def run_merge_detection() -> int:
    """Detect overlaps and create merge suggestions. Returns count of new suggestions."""
    overlaps = detect_overlaps()
    count = 0
    for ov in overlaps:
        queries.add_merge_suggestion(
            ov["asset_name_a"], ov["ticker_a"],
            ov["asset_name_b"], ov["ticker_b"],
            ov["reason"],
        )
        count += 1
    return count
