# =============================================
# world.py — ワールドクラス
# 草食・肉食それぞれの個体群と食物を管理する
# =============================================

import math
import numpy as np
import config
from organism import Organism, NeuralNetwork
from season_effects import season_of


# =============================================
# ランダム島形状の地形生成 (numpyのみ。scipy/noiseは使わない)
# 生成順: 海 → 山 → 川 → 砂漠 → 草原(残りの陸地)
# =============================================
_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _fractal_noise(n):
    """バリューノイズを4オクターブ重ねた0〜1のノイズ (n x n)"""
    total = np.zeros((n, n))
    amp, norm = 1.0, 0.0
    for size in (4, 8, 16, 32):
        lattice = np.random.random((size + 1, size + 1))
        coord = np.linspace(0, size, n, endpoint=False)
        i0 = coord.astype(int)
        t = coord - i0
        t = t * t * (3 - 2 * t)                       # smoothstep
        a = lattice[i0][:, i0] * (1 - t)[None, :] + lattice[i0][:, i0 + 1] * t[None, :]
        b = lattice[i0 + 1][:, i0] * (1 - t)[None, :] + lattice[i0 + 1][:, i0 + 1] * t[None, :]
        total += amp * (a * (1 - t)[:, None] + b * t[:, None])
        norm += amp
        amp *= 0.5
    return total / norm


def _components(mask):
    """4近傍の連結成分ごとのセル数リストと、ラベル配列を返す"""
    n = mask.shape[0]
    label = -np.ones((n, n), dtype=int)
    sizes = []
    for sx in range(n):
        for sy in range(n):
            if mask[sx, sy] and label[sx, sy] < 0:
                k = len(sizes)
                label[sx, sy] = k
                stack, count = [(sx, sy)], 0
                while stack:
                    x, y = stack.pop()
                    count += 1
                    for dx, dy in _N4:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < n and 0 <= ny < n and mask[nx, ny] and label[nx, ny] < 0:
                            label[nx, ny] = k
                            stack.append((nx, ny))
                sizes.append(count)
    return sizes, label


def _distance_to(mask):
    """maskのセルからの4近傍距離 (マルチソースBFS)。maskが空なら全セル大きな値"""
    n = mask.shape[0]
    dist = np.full((n, n), 10 ** 6, dtype=int)
    queue = [(int(x), int(y)) for x, y in np.argwhere(mask)]
    for x, y in queue:
        dist[x, y] = 0
    head = 0
    while head < len(queue):
        x, y = queue[head]
        head += 1
        d = dist[x, y] + 1
        for dx, dy in _N4:
            nx, ny = x + dx, y + dy
            if 0 <= nx < n and 0 <= ny < n and dist[nx, ny] > d:
                dist[nx, ny] = d
                queue.append((nx, ny))
    return dist


def _grow_region(allowed, size, start=None):
    """allowed(bool配列)の内側で、ランダムに広がる塊をsize個分だけ作る。セルの集合を返す"""
    cells = np.argwhere(allowed)
    if len(cells) == 0:
        return set()
    if start is None:
        c = cells[np.random.randint(len(cells))]
        start = (int(c[0]), int(c[1]))
    n = allowed.shape[0]
    region = {start}
    frontier = [start]
    while frontier and len(region) < size:
        i = np.random.randint(len(frontier))
        x, y = frontier[i]
        free = [(x + dx, y + dy) for dx, dy in _N4
                if 0 <= x + dx < n and 0 <= y + dy < n
                and allowed[x + dx, y + dy] and (x + dx, y + dy) not in region]
        if not free:
            frontier[i] = frontier[-1]
            frontier.pop()
            continue
        c = free[np.random.randint(len(free))]
        region.add(c)
        frontier.append(c)
    return region


def generate_zone_map(n):
    """n x nのzone_map(文字列の2次元リスト)と、地形の概要(dict)を返す"""
    # --- 1. 海: ノイズ + 中心からの距離で島の輪郭を決める。陸地が全体の50〜70%になるよう閾値を調整 ---
    for _ in range(30):
        target = np.random.uniform(0.55, 0.72)
        idx = (np.arange(n) + 0.5) / n * 2 - 1
        d = np.sqrt(idx[:, None] ** 2 + idx[None, :] ** 2)
        score = 0.65 * _fractal_noise(n) + 0.55 * (1.0 - np.minimum(d, 1.3) / 1.3)
        score[:3, :] = score[-3:, :] = -1.0           # 外周は必ず海
        score[:, :3] = score[:, -3:] = -1.0
        land = score >= np.quantile(score, 1.0 - target)
        sizes, label = _components(land)               # 最大の島だけ残す
        land = label == int(np.argmax(sizes))
        sizes_s, label_s = _components(~land)          # 内陸の湖(外海とつながらない海)は陸地に埋める
        land = ~(label_s == label_s[0, 0])
        if 0.50 <= land.mean() <= 0.70:
            break
    land_area = int(land.sum())
    dist_sea = _distance_to(~land)

    kind = np.full((n, n), "sea", dtype=object)
    kind[land] = "grassland"

    # --- 2. 山: 1〜3塊、島面積の10〜20%、海岸から離れた内陸のみ ---
    max_d = int(dist_sea[land].max())
    inland = land & (dist_sea >= max(4, int(max_d * 0.4)))     # 海岸から十分離れた内陸 (川が長く流れる余地を残す)
    if inland.sum() < 30:
        inland = land & (dist_sea >= max(2, int(dist_sea[land].max()) // 2))
    n_mount = int(np.random.randint(1, 4))
    total = int(land_area * np.random.uniform(0.10, 0.20))
    total = max(n_mount * 8, min(total, int(inland.sum() * 0.7)))
    mountain = set()
    for _ in range(n_mount):
        mountain |= _grow_region(inland, total // n_mount)
    if not mountain:                                   # 保険: 最も内陸のセルを山にする
        a = np.unravel_index(np.argmax(np.where(land, dist_sea, -1)), (n, n))
        mountain = {(int(a[0]), int(a[1]))}
    for x, y in mountain:
        kind[x, y] = "mountain"

    # --- 3. 川: 山から海まで蛇行しながら流れる。1〜3本 ---
    # 山のふち(山でない陸地と接する山マス)を川の源流にする
    mlist = sorted(c for c in mountain
                   if any(0 <= c[0] + dx < n and 0 <= c[1] + dy < n and land[c[0] + dx, c[1] + dy]
                          and (c[0] + dx, c[1] + dy) not in mountain for dx, dy in _N4)) or sorted(mountain)
    n_river = int(np.random.randint(1, 4))
    river = set()
    river_legacy = set()    # 砂漠の位置を決めるための川の距離計算は、これまでと同じ川(山の中の右隣も含む)で行う
    for _ in range(n_river):
        cx, cy = mlist[np.random.randint(len(mlist))]
        visited = {(cx, cy)}
        path = [(cx, cy)]
        for _s in range(4000):
            if any(not (0 <= cx + dx < n and 0 <= cy + dy < n) or not land[cx + dx, cy + dy] for dx, dy in _N4):
                break                                  # 海に到達
            cur = dist_sea[cx, cy]
            cand, weights = [], []
            for dx, dy in _N4:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in visited:
                    continue
                if dist_sea[nx, ny] < cur:
                    cand.append((nx, ny))
                    weights.append(1.0)
                elif dist_sea[nx, ny] == cur:
                    cand.append((nx, ny))
                    weights.append(0.8)                # 横に逸れて蛇行する
            if not cand:
                break
            w = np.array(weights)
            cx, cy = cand[np.random.choice(len(cand), p=w / w.sum())]
            visited.add((cx, cy))
            path.append((cx, cy))
        for x, y in path:
            river.add((x, y))
            river_legacy.add((x, y))
            if y + 1 < n and land[x, y + 1]:
                river_legacy.add((x, y + 1))
                if (x, y) not in mountain:             # 道筋が山のマスのときは右隣を川にしない (1マスだけ孤立するため)
                    river.add((x, y + 1))              # 川幅は2マス
    river_mask = np.zeros((n, n), dtype=bool)
    for x, y in river_legacy:
        river_mask[x, y] = True
    for x, y in river:
        if kind[x, y] != "mountain":
            kind[x, y] = "river"

    # --- 4. 砂漠: 50%の確率で出現。川から遠い内陸に1〜2塊 ---
    n_desert = 0
    if np.random.random() < 0.5:
        dist_river = _distance_to(river_mask)
        ok = (kind == "grassland") & (dist_sea >= 4) & (dist_river >= 6)
        if ok.sum() > 0:
            n_desert = int(np.random.randint(1, 3))
            for _ in range(n_desert):
                size = max(10, int(land_area * np.random.uniform(0.04, 0.08)))
                for x, y in _grow_region(ok, size):
                    kind[x, y] = "desert"
    # --- 5. 草原: 残りの陸地はそのままgrassland ---

    # --- 後処理: 海に届いておらず5マス以下の孤立した川の成分は、元の地形(草原)に戻す (6マス以上は残す) ---
    sizes_r, label_r = _components(kind == "river")
    for k, size in enumerate(sizes_r):
        if size > 5:
            continue
        cells = np.argwhere(label_r == k)
        reaches_sea = any(0 <= x + dx < n and 0 <= y + dy < n and kind[x + dx, y + dy] == "sea"
                          for x, y in cells for dx, dy in _N4)
        if not reaches_sea:
            for x, y in cells:
                kind[x, y] = "grassland"

    counts = {z: int((kind == z).sum()) for z in ("sea", "mountain", "river", "desert", "grassland")}
    info = {
        "land_pct": round(100.0 * land_area / (n * n), 1),
        "mountain_blobs": n_mount,
        "mountain_pct_of_land": round(100.0 * counts["mountain"] / land_area, 1),
        "rivers": n_river,
        "desert_blobs": n_desert if counts["desert"] else 0,
        "desert_pct_of_land": round(100.0 * counts["desert"] / land_area, 1),
        "counts": counts,
    }
    return kind.tolist(), info


class World:

    # 近傍探索用の空間分割(グリッド索引)のブロックサイズ
    BLOCK_SIZE = 5

    def __init__(self):
        # ランダム島形状の地形 (zone_map[x][y]: sea / mountain / river / desert / grassland)
        self.zone_map, self.map_info = generate_zone_map(config.GRID_SIZE)
        self._land_cells = [(x, y) for x in range(config.GRID_SIZE) for y in range(config.GRID_SIZE)
                            if self.zone_map[x][y] != "sea"]
        # 食料は陸地比率に応じて自動スケールする (config.pyの値は陸地100%のときの基準値)
        land_ratio = len(self._land_cells) / (config.GRID_SIZE * config.GRID_SIZE)
        self.land_ratio = land_ratio
        self.effective_food_spawn = int(config.FOOD_SPAWN_COUNT / land_ratio)
        self.effective_initial_food = int(config.INITIAL_FOOD / land_ratio)
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
    # 座標からゾーン名を返す ("sea"/"grassland"/"desert"/"mountain"/"river")
    # --------------------------------------------------
    def get_zone(self, x, y):
        return self.zone_map[x][y]

    # --------------------------------------------------
    # ゾーンごとの食物出現率
    # --------------------------------------------------
    def _zone_food_rate(self, zone):
        return {
            "grassland": config.GRASSLAND_FOOD_RATE,
            "desert":    config.DESERT_FOOD_RATE,
            "mountain":  config.MOUNTAIN_FOOD_RATE,
            "river":     config.RIVER_FOOD_RATE,
            "sea":       0.0,
        }[zone]

    # --------------------------------------------------
    # 陸地(海以外)のマスをランダムに1つ選ぶ
    # --------------------------------------------------
    def _random_land_cell(self):
        return self._land_cells[np.random.randint(len(self._land_cells))]

    # --------------------------------------------------
    # 初期化
    # --------------------------------------------------
    def _initialize(self):
        for _ in range(self.effective_initial_food):
            x, y = self._random_land_cell()
            self._add_food(x, y)

        for _ in range(config.INITIAL_HERBIVORES):
            x, y = self._random_land_cell()
            org = Organism(x, y, org_type="herbivore")
            org.age = np.random.randint(0, config.MAX_AGE // 2)   # 初期個体の年齢をばらつかせる
            self.organisms.append(org)

        for _ in range(config.INITIAL_CARNIVORES):
            x, y = self._random_land_cell()
            org = Organism(x, y, org_type="carnivore")
            org.age = np.random.randint(0, config.MAX_AGE // 2)   # 初期個体の年齢をばらつかせる
            self.organisms.append(org)

    # --------------------------------------------------
    # 1ステップ進める
    # --------------------------------------------------
    def step(self):
        self.step_count += 1

        if (np.random.random() < config.FOOD_SPAWN_RATE
                and self._food_count < config.MAX_FOOD):
            season_mult = config.SEASON_FOOD_MULT[season_of(self.generation)]
            for _ in range(int(round(self.effective_food_spawn * season_mult))):
                x = np.random.randint(0, config.GRID_SIZE)
                y = np.random.randint(0, config.GRID_SIZE)
                zone_rate = self._zone_food_rate(self.get_zone(x, y))
                if np.random.random() < zone_rate:
                    self._add_food(x, y)

        # ランダム順で行動させる (草食が先に逃げないようにシャッフル)
        self._new_offspring = []
        np.random.shuffle(self.organisms)
        self._build_spatial_index()
        if config.USE_NEUROEVOLUTION:
            self._step_organisms_batched()
        else:
            for org in self.organisms:
                org.step(self)

        self.organisms = [o for o in self.organisms if o.alive]
        self.organisms.extend(self._new_offspring)

    # --------------------------------------------------
    # 1世代分のステップを実行してデータを記録する
    # --------------------------------------------------
    # --------------------------------------------------
    # NNモードの個体行動 (行動決定フェーズをバッチ処理)
    #  1) 全個体の加齢・基本コスト・魚捕りを済ませ、生き残った個体を集める
    #  2) 生き残り全員のNN入力をステップ開始時点の盤面でまとめて作り、batch_forwardで一括推論
    #  3) 各個体に行動確率を配り、順番に行動を選んで実行する (他の個体に先に食べられた/殺された個体は行動しない)
    # --------------------------------------------------
    def _step_organisms_batched(self):
        active = [o for o in self.organisms if o._pre_decision(self)]
        if not active:
            return
        all_inputs = np.array([o.build_nn_inputs(self) for o in active])
        all_probs, all_hidden = NeuralNetwork.batch_forward(active, all_inputs)
        for i, org in enumerate(active):
            if not org.alive:
                continue
            # 強化学習用に、このステップの入力・隠れ層・確率・選んだ行動を保存する
            choice = org.sample_choice(all_probs[i])
            org._rl_inp, org._rl_hidden, org._rl_probs, org._rl_action = (
                all_inputs[i], all_hidden[i], all_probs[i], choice)
            org._ate_food = org._ate_prey = org._reproduced = False

            action, target = org.action_from_choice(self, choice)
            org._execute_action(action, target, self)

            # 行動の結果から報酬を計算し、ポリシーグラジェントで重みを更新する (学習した重みは子に遺伝する)
            reward = self._compute_reward(org)
            org.brain.rl_update(org._rl_inp, org._rl_hidden, org._rl_probs, org._rl_action,
                                reward, config.RL_LEARNING_RATE)

    # --------------------------------------------------
    # 強化学習の報酬 (行動後の状態から計算する)
    #  食物/捕食/繁殖の報酬 + 捕食者が隣接しているペナルティ(草食のみ) + 低エネルギーペナルティ
    # --------------------------------------------------
    def _compute_reward(self, o):
        r = 0.0
        if o._ate_food:
            r += config.RL_REWARD_FOOD
        if o._ate_prey:
            r += config.RL_REWARD_HUNT
        if o._reproduced:
            r += config.RL_REWARD_REPRODUCE
        if o.org_type == "herbivore" and self.get_nearest_carnivore(o.x, o.y, radius=1) is not None:
            r += config.RL_PENALTY_PREDATOR
        if o.energy < o.max_energy * config.RL_LOW_ENERGY_THRESH:
            r += config.RL_PENALTY_LOW_ENERGY
        return r

    # --------------------------------------------------
    def update_temperature(self):
        """現在の世代から気温を計算してconfig.TEMPERATUREに反映する (TEMP_SUMMER==TEMP_WINTERなら固定気温)"""
        # 季節の区切り(1世代目=春の始まり)に合わせ、夏の中央で最高、冬の中央で最低になる位相。
        # 季節kの中央は 0.5 + (k + 0.5) * SEASON_CYCLE / 4 世代目 (SEASON_CYCLE=12なら夏=5・冬=11、20なら夏=8・冬=18)
        phase = (self.generation - 0.5) / config.SEASON_CYCLE - 0.125
        config.TEMPERATURE = (config.TEMP_SUMMER + config.TEMP_WINTER) / 2 + \
            (config.TEMP_SUMMER - config.TEMP_WINTER) / 2 * math.sin(2 * math.pi * phase)

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
    # グリッド全体の 肉食数/草食数 の比 (ステップごとに1回だけ数える。NNの肉食繁殖の密度抑制に使う)
    # --------------------------------------------------
    def get_carn_herb_ratio(self):
        if getattr(self, "_ratio_step", None) != self.step_count:
            herbs = sum(len(b) for b in self._herb_grid.values())
            carns = sum(len(b) for b in self._carn_grid.values())
            self._ratio_cache = carns / herbs if herbs else float("inf")
            self._ratio_step = self.step_count
        return self._ratio_cache

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
        if self.get_zone(cx, cy) == "sea":
            cx, cy = parent.x, parent.y
        child_brain = parent.create_offspring_brain(partner) if config.USE_NEUROEVOLUTION else None
        child = Organism(cx, cy, org_type=parent.org_type, genes=child_genes, brain=child_brain)
        # 子の初期エネルギー (子自身のmax_energyを超えないようにする)
        if parent.org_type == "herbivore":
            child.energy = min(config.HERBIVORE_REPRODUCTION_COST, child.max_energy)
        else:
            child.energy = min(config.CARNIVORE_REPRODUCTION_COST, child.max_energy)
        self._new_offspring.append(child)
