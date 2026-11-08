"""Train-only robust deviation and fixed-budget chronological calibration."""
from hashlib import sha256
from math import floor, isfinite
from statistics import median, quantiles


def fit(rows, names, *, legacy_resolution=False):
    if not rows:
        raise ValueError("no training rows")
    model = {}
    for name, column in zip(names, zip(*rows, strict=True), strict=True):
        levels = set(column)
        if len(levels) == 1:
            continue
        center = median(column)
        scale = 1.4826 * median(abs(value - center) for value in column)
        method = "mad"
        if not scale:
            q1, _, q3 = quantiles(column, n=4, method="inclusive")
            scale = (q3 - q1) / 1.349
            method = "iqr"
        if not scale:
            if not legacy_resolution:
                continue
            # Phase 2 reference only. Spacing need not measure dispersion.
            levels = sorted(levels)
            scale = min(b - a for a, b in zip(levels, levels[1:]))
            method = "observed_resolution"
        model[name] = {"median": center, "scale": scale, "method": method}
    return model


def score(values, names, model):
    deviations = {
        name: abs(value - model[name]["median"]) / model[name]["scale"]
        for name, value in zip(names, values, strict=True) if name in model
    }
    if not deviations:
        return 0.0, None
    driver = max(deviations, key=deviations.get)
    return deviations[driver], driver


def threshold(scores):
    if not scores:
        raise ValueError("no calibration scores")
    # Strict comparison excludes every row tied at the cutoff.
    return sorted(scores, reverse=True)[floor(len(scores) / 100)]


def alert_key(value, identity):
    """Common score order for calibration and fixed-budget ranking."""
    if not isfinite(value) or not isinstance(identity, str) or not identity:
        raise ValueError("expected finite score and stable observation identity")
    tie = sha256(b"xrpl-alert-budget-v1\x00" + identity.encode("utf-8")).digest()
    return value, tie.hex(), identity


def alert_cutoff(rows):
    keys = sorted((alert_key(*row) for row in rows), reverse=True)
    if not keys or len({key[2] for key in keys}) != len(keys):
        raise ValueError("expected nonempty calibration with unique identities")
    return keys[len(keys) // 100]


def budget_summary(rows, cutoff):
    counts = dict(rows=0, alerts=0, above_score=0, tied_score=0, alerted_ties=0)
    for row in rows:
        key = alert_key(*row)
        counts["rows"] += 1
        counts["alerts"] += key > cutoff
        counts["above_score"] += key[0] > cutoff[0]
        counts["tied_score"] += key[0] == cutoff[0]
        counts["alerted_ties"] += key[0] == cutoff[0] and key > cutoff
    return counts
