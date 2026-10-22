"""Read-only, deterministic explanations. No Pygame or external service required."""
import argparse
import csv
import itertools
import json
import math
from pathlib import Path

LEVELS = ("LOW", "MID", "HIGH")
DATA_PATH = Path(__file__).with_name("data") / "status_explanations.json"


class StatusExplainer:
    def __init__(self, data_path=DATA_PATH):
        self.data = json.loads(Path(data_path).read_text(encoding="utf-8"))
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
            for field in ("descriptions", "strengths", "weaknesses"):
                if any(not stat[field].get(level, "").strip() for level in LEVELS):
                    raise ValueError("Missing status text")
        ids = set()
        for rule in self.data["relations"]:
            if rule["id"] in ids or not rule["text"].strip():
                raise ValueError("Duplicate or empty relation")
            ids.add(rule["id"])
            if rule.get("species") not in (None, *self.data["species"]):
                raise ValueError("Unknown species in rule")
            if any(k not in self.keys or v not in LEVELS for k, v in rule["when"].items()):
                raise ValueError("Unknown status/level in rule")
        for key, text in self.data["special"].items():
            parts = key.split("|")
            if (len(parts) != len(self.keys) + 1 or parts[0] not in self.data["species"]
                    or any(v not in LEVELS for v in parts[1:]) or not text.strip()):
                raise ValueError("Invalid exact combination")

    def classify(self, key, value):
        stat = self.stats[self.keys.index(key)]
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key}: expected a finite value in [0, 1]")
        low, high = stat["thresholds"]
        return "LOW" if value < low else "MID" if value < high else "HIGH"

    def explain_values(self, species, genes, energy_ratio):
        if species not in self.data["species"]:
            raise ValueError("Unknown species")
        values = {s["key"]: float(genes[s["key"]]) if s["source"] == "gene"
                  else float(energy_ratio) for s in self.stats}
        levels = {k: self.classify(k, v) for k, v in values.items()}
        key = "|".join([species] + [levels[k] for k in self.keys])
        matched = [r for r in self.data["relations"]
                   if r.get("species", species) == species
                   and all(levels[k] == v for k, v in r["when"].items())]
        relationships = list(dict.fromkeys(r["text"] for r in matched))
        covered = {key for rule in matched for key in rule["when"]}
        # Explain each ability once: pair rules take precedence over single-stat text.
        descriptions = [s["descriptions"][levels[s["key"]]] for s in self.stats
                        if s["key"] not in covered]
        headline = self.data["special"].get(key, "")
        summary = "".join(([headline] if headline else []) + relationships + descriptions)
        return {
            "key": key, "species": species, "species_label": self.data["species"][species],
            "values": values, "levels": levels, "summary": summary,
            "relationships": relationships,
            "strengths": list(dict.fromkeys(s["strengths"][levels[s["key"]]] for s in self.stats)),
            "weaknesses": list(dict.fromkeys(s["weaknesses"][levels[s["key"]]] for s in self.stats)),
            "unclassified_genes": sorted(set(genes) - {s["key"] for s in self.stats if s["source"] == "gene"}),
        }

    def explain_organism(self, org, world):
        import config
        if not math.isfinite(org.energy) or not math.isfinite(org.max_energy):
            raise ValueError("Non-finite energy")
        if org.max_energy <= 0:
            raise ValueError("Energy capacity must be positive")
        # Negative energy can occur on the death step; classify it as depleted.
        ratio = max(0.0, min(1.0, org.energy / org.max_energy))
        result = self.explain_values(org.org_type, org.genes, ratio)
        zone = world.get_zone(org.x, org.y)
        result["state"] = {"energy": org.energy, "max_energy": org.max_energy,
                           "age": org.age, "alive": org.alive, "x": org.x, "y": org.y,
                           "zone": zone, "temperature": config.TEMPERATURE}
        temp_cost = org._calc_temp_penalty(world)
        move_cost = org._move_energy_cost(world)
        base = (config.HERBIVORE_BASE_ENERGY_COST if org.org_type == "herbivore"
                else config.CARNIVORE_BASE_ENERGY_COST) * (0.5 + org.genes["metabolism"])
        # These existing helpers only read state. Never call a behavior or random movement helper.
        result["costs"] = {"temperature": temp_cost, "base": base, "move": move_cost}
        result["context"] = [self.data["context"]["costs"].format(
            temperature=config.TEMPERATURE, ideal=org.genes["cold_resistance"] * 40,
            temp_cost=temp_cost, base=base, move=move_cost)]
        if org.org_type == "carnivore":
            tolerance = org.genes["river_tolerance"]
            fish = self.data["context"]["fish_positive" if tolerance > .8 else "fish_zero"]
            result["context"].append(fish)
        if not org.alive:
            result["context"].append(self.data["context"]["dead"])
        if result["unclassified_genes"]:
            result["context"].append(self.data["text"]["unknown"])
        return result

    def combinations(self, species):
        """Yield every final explanation, using interval midpoints as examples."""
        for combination in itertools.product(LEVELS, repeat=len(self.stats)):
            values = {}
            for stat, level in zip(self.stats, combination):
                bounds = (0.0, *stat["thresholds"], 1.0)
                i = LEVELS.index(level)
                values[stat["key"]] = (bounds[i] + bounds[i + 1]) / 2
            genes = {s["key"]: values[s["key"]] for s in self.stats if s["source"] == "gene"}
            yield self.explain_values(species, genes, values["energy_ratio"])

    def export_csv(self, path):
        with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["species", "key", *self.keys, "summary", "strengths", "weaknesses"])
            for species in self.data["species"]:
                for r in self.combinations(species):
                    writer.writerow([r["species_label"], r["key"], *r["levels"].values(),
                                     r["summary"], "／".join(r["strengths"]), "／".join(r["weaknesses"])])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="全組み合わせの解説をCSV出力")
    parser.add_argument("--export", type=Path, required=True)
    args = parser.parse_args()
    StatusExplainer().export_csv(args.export)
    print(f"Saved: {args.export}")
