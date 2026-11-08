"""Validate the frozen Phase 3B.3 protocol and acquire only its six ranges."""
import json
from pathlib import Path

from .development import GROUPS, MODEL_SEEDS, TREES
from .expansion import FROZEN_DIGEST, PLAN, acquire_stage, frozen_plan
from .features import FEATURES, SCHEMA_VERSION, WINDOW
from .perturbations import FAMILIES, SEEDS
from .pilot import MIB, digest

CONFIG = Path("docs/phase3b3-protocol.json")
RAW = Path("data/raw/phase3b3")
SIZES = {"static": 256, "temporal": 128, "full": 256}
LIMITS = (4500, 3072 * MIB, 10800)
STORAGE = 768 * MIB


def protocol():
    config = json.loads(CONFIG.read_bytes())
    expected = dict(
        version=1, plan_sha256=FROZEN_DIGEST,
        roles=["train"] * 4 + ["development"] * 2 + ["calibration"] * 2 + ["test"] * 4,
        feature_schema=SCHEMA_VERSION, lookback_seconds=WINDOW, scoring_seconds=1800,
        groups={group: [FEATURES[i] for i in columns] for group, columns in GROUPS.items()},
        baseline={"mad_multiplier": 1.4826, "iqr_divisor": 1.349, "legacy_resolution": False},
        forest={"sizes": SIZES, "seeds": list(MODEL_SEEDS), "trees": TREES},
        interventions={"families": {family: list(levels) for family, levels in FAMILIES.items()},
                       "seeds": list(SEEDS), "sender_target_divisor": 100},
        alert={"divisor": 100, "tie_domain": "xrpl-alert-budget-v1",
               "calibration": "pooled_clean_key_at_k_strict_greater",
               "ranking": "per_block_top_k"},
        acquisition={"attempts": LIMITS[0], "charged_bytes": LIMITS[1],
                     "seconds": LIMITS[2], "cache_bytes": STORAGE},
    )
    source = Path(__file__).parent
    expected["frozen_source_sha256"] = {
        name: digest((source / name).read_bytes().replace(b"\r\n", b"\n"))
        for name in ("baseline.py", "development.py", "features.py", "isolation.py", "perturbations.py")
    }
    if config != expected:
        raise ValueError("Phase 3B.3 configuration or frozen scorer source differs")
    blocks = frozen_plan(PLAN)
    if [block["role"] for block in blocks] != config["roles"]:
        raise ValueError("unexpected chronological split")
    return config, blocks


def acquire():
    _, blocks = protocol()
    acquire_stage(RAW, blocks[6:], 7, LIMITS, STORAGE)


if __name__ == "__main__":
    acquire()
