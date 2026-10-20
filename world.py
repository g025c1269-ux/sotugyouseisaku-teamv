# =============================================
# world.py — ワールドクラス
# 草食・肉食それぞれの個体群と食物を管理する
# =============================================

import math
import numpy as np
import config
from organism import Organism


class World:

    # 近傍探索用の空間分割(グリッド索引)のブロックサイズ
    BLOCK_SIZE = 5

    # 地形ゾーンマップ (行=x方向, 列=y方向。それぞれ5分割)
    # 川は中央列(列インデックス2)だが、行0(最上部)だけは山とする
    ZONE_GRID = [
        ["mountain", "mountain", "mountain",  "grassland", "grassland"],
        ["mountain", "mountain", "river",     "grassland", "grassland"],
        ["mountain", "desert",   "river",     "grassland", "grassland"],
        ["desert",   "desert",   "river",     "grassland", "grassland"],
        ["desert",   "desert",   "river",     "grassland", "grassland"],
    ]

    def __init__(self):
        self.food_grid  = np.zeros((config.GRID_SIZE, config.GRID_SIZE), dtype=bool)
        self.organisms  = []
        self.generation = 0
        self.step_count = 0
        self._new_offspring = []
        self._herb_grid = {}
        self._carn_grid = {}
        self._food_buckets = {}   # ブロックごとの食物座標 (集合)
        self._food_count = 0

        # 草食・肉食それぞれを別々に記録
        self.history = {
            "generation":             [],
            "temperature":            [],
            "herbivore_count":        [],
            "carnivore_count":        [],
            "herb_cold_resistance":   [],
            "herb_speed":             [],
            "herb_metabolism":        [],
            "herb_river_tolerance":   [],
            "herb_mountain_tolerance": [],
            "herb_mountain_tolerance_in_zone": [],
            "herb_river_tolerance_in_zone":    [],
            "carn_cold_resistance":   [],
            "carn_speed":             [],
            "carn_metabolism":        [],
            "carn_river_tolerance":   [],
            "carn_mountain_tolerance": [],
            "carn_mountain_tolerance_in_zone": [],
            "carn_river_tolerance_in_zone":    [],
        }
        self._initialize()

    # --------------------------------------------------
    # 座標からゾーン名を返す ("grassland"/"desert"/"mountain"/"river")
    # --------------------------------------------------
    def get_zone(self, x, y):
        band = config.GRID_SIZE // 5
        row_band = min(x // band, 4)
        col_band = min(y // band, 4)
        return self.ZONE_GRID[row_band][col_band]

    # --------------------------------------------------
    # ゾーンごとの食物出現率
    # --------------------------------------------------
    def _zone_food_rate(self, zone):
        return {
            "grassland": config.GRASSLAND_FOOD_RATE,
            "desert":    config.DESERT_FOOD_RATE,
            "mountain":  config.MOUNTAIN_FOOD_RATE,
            "river":     config.RIVER_FOOD_RATE,
        }[zone]

    # --------------------------------------------------
    # 初期化
    # --------------------------------------------------
    def _initialize(self):
        for _ in range(config.INITIAL_FOOD):
            x = np.random.randint(0, config.GRID_SIZE)
            y = np.random.randint(0, config.GRID_SIZE)
            self._add_food(x, y)

        for _ in range(config.INITIAL_HERBIVORES):
            x = np.random.randint(0, config.GRID_SIZE)
            y = np.random.randint(0, config.GRID_SIZE)
            self.organisms.append(Organism(x, y, org_type="herbivore"))

        for _ in range(config.INITIAL_CARNIVORES):
            x = np.random.randint(0, config.GRID_SIZE)
            y = np.random.randint(0, config.GRID_SIZE)
            self.organisms.append(Organism(x, y, org_type="carnivore"))

    # --------------------------------------------------
    # 1ステップ進める
    # --------------------------------------------------
    def step(self):
        self.step_count += 1

        if (np.random.random() < config.FOOD_SPAWN_RATE
                and self._food_count < config.MAX_FOOD):
            for _ in range(config.FOOD_SPAWN_COUNT):
                x = np.random.randint(0, config.GRID_SIZE)
                y = np.random.randint(0, config.GRID_SIZE)
                zone_rate = self._zone_food_rate(self.get_zone(x, y))
                if np.random.random() < zone_rate:
                    self._add_food(x, y)

        # ランダム順で行動させる (草食が先に逃げないようにシャッフル)
        self._new_offspring = []
        np.random.shuffle(self.organisms)
        self._build_spatial_index()
        for org in self.organisms:
            org.step(self)

        self.organisms = [o for o in self.organisms if o.alive]
        self.organisms.extend(self._new_offspring)

    # --------------------------------------------------
    # 1世代分のステップを実行してデータを記録する
    # --------------------------------------------------
    def update_temperature(self):
        """現在の世代から気温を計算してconfig.TEMPERATUREに反映する (TEMP_SUMMER==TEMP_WINTERなら固定気温)"""
        config.TEMPERATURE = (config.TEMP_SUMMER + config.TEMP_WINTER) / 2 + \
            (config.TEMP_SUMMER - config.TEMP_WINTER) / 2 * \
            math.sin(2 * math.pi * self.generation / config.SEASON_CYCLE)

    def run_generation(self):
        self.generation += 1
        self.update_temperature()
        for _ in range(config.MAX_STEPS_PER_GEN):
            self.step()
            if len(self.organisms) == 0:
                break
        self._record_data()
        return len(self.organisms) > 0

    # --------------------------------------------------
    # データ記録
    # --------------------------------------------------
    def _record_data(self):
        herbs  = [o for o in self.organisms if o.org_type == "herbivore"]
        carns  = [o for o in self.organisms if o.org_type == "carnivore"]

        herb_in_mountain = [o for o in herbs if self.get_zone(o.x, o.y) == "mountain"]
        carn_in_mountain = [o for o in carns if self.get_zone(o.x, o.y) == "mountain"]
        herb_in_river    = [o for o in herbs if self.get_zone(o.x, o.y) == "river"]
        carn_in_river    = [o for o in carns if self.get_zone(o.x, o.y) == "river"]

        self.history["generation"].append(self.generation)
        self.history["temperature"].append(config.TEMPERATURE)
        self.history["herbivore_count"].append(len(herbs))
        self.history["carnivore_count"].append(len(carns))

        self.history["herb_cold_resistance"].append(
            np.mean([o.genes["cold_resistance"] for o in herbs]) if herbs else np.nan)
        self.history["herb_speed"].append(
            np.mean([o.genes["speed"] for o in herbs]) if herbs else np.nan)
        self.history["herb_metabolism"].append(
            np.mean([o.genes["metabolism"] for o in herbs]) if herbs else np.nan)
        self.history["herb_river_tolerance"].append(
            np.mean([o.genes["river_tolerance"] for o in herbs]) if herbs else np.nan)
        self.history["herb_mountain_tolerance"].append(
            np.mean([o.genes["mountain_tolerance"] for o in herbs]) if herbs else np.nan)
        self.history["herb_mountain_tolerance_in_zone"].append(
            np.mean([o.genes["mountain_tolerance"] for o in herb_in_mountain]) if herb_in_mountain else np.nan)
        self.history["herb_river_tolerance_in_zone"].append(
            np.mean([o.genes["river_tolerance"] for o in herb_in_river]) if herb_in_river else np.nan)
        self.history["carn_cold_resistance"].append(
            np.mean([o.genes["cold_resistance"] for o in carns]) if carns else np.nan)
        self.history["carn_speed"].append(
            np.mean([o.genes["speed"] for o in carns]) if carns else np.nan)
        self.history["carn_metabolism"].append(
            np.mean([o.genes["metabolism"] for o in carns]) if carns else np.nan)
        self.history["carn_river_tolerance"].append(
            np.mean([o.genes["river_tolerance"] for o in carns]) if carns else np.nan)
        self.history["carn_mountain_tolerance"].append(
            np.mean([o.genes["mountain_tolerance"] for o in carns]) if carns else np.nan)
        self.history["carn_mountain_tolerance_in_zone"].append(
            np.mean([o.genes["mountain_tolerance"] for o in carn_in_mountain]) if carn_in_mountain else np.nan)
        self.history["carn_river_tolerance_in_zone"].append(
            np.mean([o.genes["river_tolerance"] for o in carn_in_river]) if carn_in_river else np.nan)

    # --------------------------------------------------
    # 食物をブロック索引に追加する
    # --------------------------------------------------
    def _add_food(self, x, y):
        if not self.food_grid[x, y]:
            self.food_grid[x, y] = True
            self._food_count += 1
            key = (x // self.BLOCK_SIZE, y // self.BLOCK_SIZE)
            self._food_buckets.setdefault(key, set()).add((x, y))

    # --------------------------------------------------
    # 近くの食物を探す (食物はブロックごとの索引から探す)
    # --------------------------------------------------
    def get_nearest_food(self, x, y, radius=4):
        bs = self.BLOCK_SIZE
        block_radius = radius // bs + 1
        bx, by = x // bs, y // bs
        best_dist = float("inf")
        best_pos  = None
        for dbx in range(-block_radius, block_radius + 1):
            for dby in range(-block_radius, block_radius + 1):
                bucket = self._food_buckets.get((bx + dbx, by + dby))
                if not bucket:
                    continue
                for (fx, fy) in bucket:
                    dist = abs(fx - x) + abs(fy - y)
                    if dist <= radius and dist < best_dist:
                        best_dist = dist
                        best_pos  = (fx, fy)
                        if best_dist == 0:
                            return best_pos
        return best_pos

    # --------------------------------------------------
    # 空間分割 (グリッド索引) の構築
    # 1ステップの最初に1回だけ作り直し、各個体をブロックごとのリストに振り分ける。
    # これにより近傍探索が全個体を舐めるO(n)ではなく、近隣ブロックだけを見る
    # O(1)相当(局所密度に比例)で済むようになる。
    # --------------------------------------------------
    def _build_spatial_index(self):
        self._herb_grid = {}
        self._carn_grid = {}
        bs = self.BLOCK_SIZE
        for org in self.organisms:
            if not org.alive:
                continue
            key = (org.x // bs, org.y // bs)
            grid = self._herb_grid if org.org_type == "herbivore" else self._carn_grid
            grid.setdefault(key, []).append(org)

    # --------------------------------------------------
    # 指定座標から半径radius以内が入りうる近隣ブロックの個体を集める
    # --------------------------------------------------
    def _nearby_candidates(self, grid, x, y, radius):
        bs = self.BLOCK_SIZE
        block_radius = radius // bs + 1
        bx, by = x // bs, y // bs
        candidates = []
        for dbx in range(-block_radius, block_radius + 1):
            for dby in range(-block_radius, block_radius + 1):
                bucket = grid.get((bx + dbx, by + dby))
                if bucket:
                    candidates.extend(bucket)
        return candidates

    # --------------------------------------------------
    # 近くの草食動物を探す (肉食動物が使う)
    # --------------------------------------------------
    def get_nearest_herbivore(self, x, y, radius=5):
        best_dist = float("inf")
        best_org  = None
        for org in self._nearby_candidates(self._herb_grid, x, y, radius):
            if org.alive:
                dist = abs(org.x - x) + abs(org.y - y)
                if dist <= radius and dist < best_dist:
                    best_dist = dist
                    best_org  = org
        return best_org

    # --------------------------------------------------
    # 視野範囲内の草食動物の数を数える (肉食動物の繁殖判断に使う)
    # --------------------------------------------------
    def count_nearby_herbivores(self, x, y, radius=5):
        count = 0
        for org in self._nearby_candidates(self._herb_grid, x, y, radius):
            if org.alive:
                dist = abs(org.x - x) + abs(org.y - y)
                if dist <= radius:
                    count += 1
        return count

    # --------------------------------------------------
    # マップ全体の草食動物の割合 (肉食動物の繁殖判断に使う)
    # グリッド全体の3%以上の草食がいれば1.0(通常通り繁殖可能)、
    # それ未満なら比例して繁殖が抑制される
    # --------------------------------------------------
    def get_global_herb_ratio(self):
        total_herb = len([o for o in self.organisms if o.org_type == "herbivore"])
        return min(total_herb / (config.GRID_SIZE * config.GRID_SIZE * 0.03), 1.0)

    # --------------------------------------------------
    # 近くの肉食動物を探す (草食動物が使う)
    # --------------------------------------------------
    def get_nearest_carnivore(self, x, y, radius=3):
        best_dist = float("inf")
        best_org  = None
        for org in self._nearby_candidates(self._carn_grid, x, y, radius):
            if org.alive:
                dist = abs(org.x - x) + abs(org.y - y)
                if dist <= radius and dist < best_dist:
                    best_dist = dist
                    best_org  = org
        return best_org

    # --------------------------------------------------
    # 近くの同種個体をパートナーとして探す (繁殖の交叉に使う)
    # --------------------------------------------------
    def get_nearby_partner(self, organism, radius=3):
        grid = self._herb_grid if organism.org_type == "herbivore" else self._carn_grid
        best_dist = float("inf")
        best_org  = None
        for org in self._nearby_candidates(grid, organism.x, organism.y, radius):
            if org is organism:
                continue
            if org.alive:
                dist = abs(org.x - organism.x) + abs(org.y - organism.y)
                if dist <= radius and dist < best_dist:
                    best_dist = dist
                    best_org  = org
        return best_org

    # --------------------------------------------------
    # 食物を消費する
    # --------------------------------------------------
    def consume_food(self, x, y):
        key = (x // self.BLOCK_SIZE, y // self.BLOCK_SIZE)
        bucket = self._food_buckets.get(key)
        if bucket and (x, y) in bucket:
            bucket.discard((x, y))
            self.food_grid[x, y] = False
            self._food_count -= 1
            return True
        return False

    # --------------------------------------------------
    # 子個体を生成してバッファに追加
    # --------------------------------------------------
    def spawn_offspring(self, parent):
        partner = self.get_nearby_partner(parent, radius=3)
        child_genes = parent.create_offspring_genes(partner)
        cx = max(0, min(config.GRID_SIZE - 1, parent.x + np.random.randint(-2, 3)))
        cy = max(0, min(config.GRID_SIZE - 1, parent.y + np.random.randint(-2, 3)))
        child = Organism(cx, cy, org_type=parent.org_type, genes=child_genes)
        # 子の初期エネルギー (子自身のmax_energyを超えないようにする)
        if parent.org_type == "herbivore":
            child.energy = min(config.HERBIVORE_REPRODUCTION_COST, child.max_energy)
        else:
            child.energy = min(config.CARNIVORE_REPRODUCTION_COST, child.max_energy)
        self._new_offspring.append(child)
