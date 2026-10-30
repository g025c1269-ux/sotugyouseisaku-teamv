"""ゲームモードのMPとスキルの効果。数値は data/game_rules.json と data/skills.json にある (ここには直書きしない)。

GameState: MP (使うと減り、世代とともに回復する) と、スキルが使えるかの判定。
apply_skill(world, skill, cell, species): スキルの効果を世界に与える。使えなかったときは None (MPは減らさない)。
"""
import json
from pathlib import Path

import numpy as np

import config
from organism import Organism

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_rules(path=DATA_DIR / "game_rules.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_game_skills(path=DATA_DIR / "skills.json"):
    """ゲームで使うスキルの定義 (コスト・パラメータ・キーを含む)。"""
    with open(path, encoding="utf-8") as f:
        return [{**s, "cost": int(s["cost"]), "params": s.get("params", {}), "key": str(s["key"])}
                for s in json.load(f)["skills"]]


class GameState:
    def __init__(self, rules=None, skills=None):
        self.rules = rules if rules is not None else load_rules()
        self.skills = skills if skills is not None else load_game_skills()
        self.mp_max = float(self.rules["mp_max"])
        self.mp = self.mp_max                                    # 開始時は最大
        self.regen_per_step = float(self.rules["mp_regen_per_generation"]) / config.MAX_STEPS_PER_GEN

    def tick(self):
        """1ステップ進むごとに呼ぶ (一時停止中は呼ばない)。"""
        self.mp = min(self.mp_max, self.mp + self.regen_per_step)

    def can_use(self, skill):
        return self.mp >= skill["cost"]

    def spend(self, skill):
        self.mp = max(0.0, self.mp - skill["cost"])


def _land_cells_within(world, cell, radius):
    """cell (x, y) から半径 radius マス以内の、海でないマスの一覧。"""
    cx, cy = cell
    n = config.GRID_SIZE
    cells = []
    for x in range(max(0, cx - radius), min(n, cx + radius + 1)):
        for y in range(max(0, cy - radius), min(n, cy + radius + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 and world.get_zone(x, y) != "sea":
                cells.append((x, y))
    return cells


def _food(world, skill, cell):
    p = skill["params"]
    free = [c for c in _land_cells_within(world, cell, p["radius"]) if not world.food_grid[c]]
    if not free:
        return None
    chosen = np.random.choice(len(free), size=min(p["max_count"], len(free)), replace=False)
    for i in chosen:
        world._add_food(*free[i])
    return {"count": len(chosen)}


def _spawn(world, skill, cell, species):
    p = skill["params"]
    cells = _land_cells_within(world, cell, p["radius"])
    if not cells or species not in ("herbivore", "carnivore"):
        return None
    count = p["herbivore_count"] if species == "herbivore" else p["carnivore_count"]
    for _ in range(count):
        x, y = cells[np.random.randint(len(cells))]
        world.organisms.append(Organism(x, y, org_type=species))      # 遺伝子はステージの範囲、脳はランダム、年齢0
    return {"count": count, "species": species}


def _adapt(world, skill):
    fraction = skill["params"]["fraction"]
    target = min(1.0, max(0.0, config.TEMPERATURE / 40.0))
    mean = lambda: float(np.mean([o.genes["cold_resistance"] for o in world.organisms])) if world.organisms else 0.0
    before = mean()
    for o in world.organisms:
        c = o.genes["cold_resistance"]
        o.genes["cold_resistance"] = min(1.0, max(0.0, c + (target - c) * fraction))
    return {"count": len(world.organisms), "before": before, "after": mean()}


def apply_skill(world, skill, cell=None, species=None):
    """スキルを使う。効果の辞書 (count など) を返す。場所に出せるマスがないなど、使えなかったときは None。"""
    if skill["id"] == "food":
        return _food(world, skill, cell)
    if skill["id"] == "spawn":
        return _spawn(world, skill, cell, species)
    if skill["id"] == "adapt":
        return _adapt(world, skill)
    return None
