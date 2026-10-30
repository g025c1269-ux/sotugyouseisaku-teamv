"""Read-only status classification for population aggregates and numeric inspection."""
import json
import math
from pathlib import Path

LEVELS = ("LOW", "MID", "HIGH")
DATA_PATH = Path(__file__).with_name("data") / "status_explanations.json"


class StatusExplainer:
    def __init__(self, data_path=DATA_PATH):
        self.data = json.loads(Path(data_path).read_text(encoding="utf-8"))
        self.modes = self.data["modes"]
        self.stats = self.data["stats"]
        self.keys = tuple(s["key"] for s in self.stats)
        if len(set(self.keys)) != len(self.keys):
            raise ValueError("Duplicate status key")
        for stat in self.stats:
            if stat["source"] not in ("gene", "energy_ratio"):
                raise ValueError("Unknown status source")
            low, high = stat["thresholds"]
            if not 0 < low < high < 1:
                raise ValueError("Invalid thresholds")

    def classify(self, key, value):
        stat = self.stats[self.keys.index(key)]
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key}: expected a finite value in [0, 1]")
        low, high = stat["thresholds"]
        return "LOW" if value < low else "MID" if value < high else "HIGH"

    @staticmethod
    def current_mode():
        import config
        return "nn" if config.USE_NEUROEVOLUTION else "rule"
