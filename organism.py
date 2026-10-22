# =============================================
# organism.py — 個体クラス
# =============================================

import numpy as np
import config


# ゾーンをNN入力用の数値に変換する
ZONE_INPUT = {"grassland": 0.0, "river": 0.33, "desert": 0.67, "mountain": 1.0}

# NNの出力(6つ)と対応する行動。0〜3は移動方向(dx, dy)。x=行方向、y=列方向
NN_MOVES = [(-1, 0), (1, 0), (0, -1), (0, 1)]   # 上 / 下 / 左 / 右
NN_IDLE, NN_REPRODUCE = 4, 5
CARN_HERB_RATIO_LIMIT = 0.3   # 肉食/草食比がこれを超えると肉食は繁殖できない


# =============================================
# ニューラルネットワーク (入力8 → 隠れ8(ReLU) → 出力6(softmax))
# 重みは-1〜1の一様乱数で初期化し、クリップはしない
# =============================================
class NeuralNetwork:
    N_IN, N_HIDDEN, N_OUT = 8, 8, 6

    def __init__(self, params=None):
        if params is None:
            self.w1 = np.random.uniform(-1, 1, (self.N_IN, self.N_HIDDEN))
            self.b1 = np.random.uniform(-1, 1, self.N_HIDDEN)
            self.w2 = np.random.uniform(-1, 1, (self.N_HIDDEN, self.N_OUT))
            self.b2 = np.random.uniform(-1, 1, self.N_OUT)
        else:
            self.w1, self.b1, self.w2, self.b2 = (p.copy() for p in params)

    def params(self):
        return (self.w1, self.b1, self.w2, self.b2)

    def forward(self, inputs):
        h = np.maximum(0.0, inputs @ self.w1 + self.b1)
        z = h @ self.w2 + self.b2
        e = np.exp(z - z.max())
        return e / e.sum()

    # 交叉: 重み1つ1つについて、両親のどちらかを50%の確率で選ぶ (partnerなしなら親のコピー)
    # 突然変異: 各重みがMUTATION_RATEの確率で、標準偏差MUTATION_STRENGTHの正規ノイズを加算 (クリップなし)
    @staticmethod
    def offspring(parent, partner=None):
        child = NeuralNetwork(parent.params())
        if partner is not None:
            for mine, theirs in zip(child.params(), partner.params()):
                take_partner = np.random.random(mine.shape) < 0.5
                mine[take_partner] = theirs[take_partner]
        for p in child.params():
            mutate = np.random.random(p.shape) < config.MUTATION_RATE
            p += mutate * np.random.normal(0, config.MUTATION_STRENGTH, p.shape)
        return child


class Organism:
    def __init__(self, x, y, org_type="herbivore", genes=None, brain=None):
        self.x = x
        self.y = y
        self.org_type = org_type
        self.alive = True
        self.age = 0

        if genes is None:
            self.genes = {
                "cold_resistance":    np.random.uniform(*config.GENE_COLD_RESISTANCE_RANGE),
                "speed":              np.random.uniform(*config.GENE_SPEED_RANGE),
                "hunger_threshold":   np.random.uniform(*config.GENE_HUNGER_THRESHOLD_RANGE),
                "metabolism":         np.random.uniform(*config.GENE_METABOLISM_RANGE),
                "river_tolerance":    np.random.uniform(*config.GENE_RIVER_TOLERANCE_RANGE),
                "mountain_tolerance": np.random.uniform(*config.GENE_MOUNTAIN_TOLERANCE_RANGE),
            }
        else:
            self.genes = genes.copy()

        # metabolismが高いほどエネルギー容量(max_energy)が大きくなる
        # (省エネだが容量が小さい ⇔ 燃費は悪いが容量が大きく繁殖しやすい、というトレードオフ)
        capacity_factor = 0.5 + self.genes["metabolism"]
        if org_type == "herbivore":
            self.max_energy = config.HERBIVORE_MAX_ENERGY * capacity_factor
            self.energy     = min(config.HERBIVORE_INITIAL_ENERGY, self.max_energy)
        else:
            self.max_energy = config.CARNIVORE_MAX_ENERGY * capacity_factor
            self.energy     = min(config.CARNIVORE_INITIAL_ENERGY, self.max_energy)

        # ニューロエボリューション用のNN (既存のgenesとは別に管理する)
        self.brain = None
        if config.USE_NEUROEVOLUTION:
            self.brain = brain if brain is not None else NeuralNetwork()

    # --------------------------------------------------
    # 行動メインループ
    # --------------------------------------------------
    def step(self, world):
        if not self.alive:
            return
        self.age += 1
        if self.age > config.MAX_AGE:
            self.alive = False
            return

        temp_penalty = self._calc_temp_penalty(world)
        # 基本コスト (じっとしていても消費する分) にはmetabolismのみが影響する。
        # 移動コストはspeedのみが影響する (_move_energy_cost / _movement_steps側で計算)
        base_metabolism = 0.5 + self.genes["metabolism"]
        if self.org_type == "herbivore":
            base_cost = config.HERBIVORE_BASE_ENERGY_COST * base_metabolism
        else:
            base_cost = config.CARNIVORE_BASE_ENERGY_COST * base_metabolism
        self.energy -= (base_cost + temp_penalty)

        if self.energy <= 0:
            self.alive = False
            return

        # 肉食動物は川にいると魚を捕れる (river_toleranceが0.8以上の個体だけ)
        if (self.org_type == "carnivore" and world.get_zone(self.x, self.y) == "river"
                and self.genes["river_tolerance"] >= 0.8):
            fish_catch_prob = (self.genes["river_tolerance"] - 0.8) * 5 * 0.5
            if np.random.random() < fish_catch_prob:
                self.energy = min(
                    self.energy + config.CARNIVORE_ENERGY_FROM_FISH,
                    self.max_energy
                )

        action, target = self._decide_action(world)
        self._execute_action(action, target, world)

    # --------------------------------------------------
    # 気温ペナルティ (砂漠にいると係数が1.3倍になる)
    # --------------------------------------------------
    def _calc_temp_penalty(self, world):
        temp_normalized = config.TEMPERATURE / 40.0
        diff = abs(temp_normalized - self.genes["cold_resistance"])
        coef = (config.HERBIVORE_TEMP_PENALTY_COEF if self.org_type == "herbivore"
                else config.CARNIVORE_TEMP_PENALTY_COEF)
        penalty = diff * coef
        if world.get_zone(self.x, self.y) == "desert":
            penalty *= config.DESERT_TEMP_PENALTY_MULTIPLIER
        return penalty

    # --------------------------------------------------
    # 行動選択
    # --------------------------------------------------
    def _decide_action(self, world):
        if config.USE_NEUROEVOLUTION:
            return self._decide_action_nn(world)
        energy_ratio = self.energy / self.max_energy
        scores = {}
        targets = {}

        if self.org_type == "herbivore":
            # 天敵が近くにいるか確認 (逃げ行動の判断)
            predator = world.get_nearest_carnivore(self.x, self.y, radius=5)
            if predator:
                # 天敵が近い → 逃げることを最優先
                scores["flee"] = 3.0
                targets["flee"] = predator

            food_nearby = world.get_nearest_food(self.x, self.y, radius=4)
            if food_nearby:
                scores["move_to_food"] = (1.0 - energy_ratio) * 2.0
                targets["move_to_food"] = food_nearby
            reproduction_threshold = self.max_energy * 0.8
            if self.energy >= reproduction_threshold:
                scores["reproduce"] = energy_ratio * self.genes["hunger_threshold"]
            scores["move_random"] = 0.4
            scores["idle"]        = 0.3

        else:
            prey = world.get_nearest_herbivore(self.x, self.y, radius=5)
            if prey:
                scores["hunt"] = (1.0 - energy_ratio) * 2.5
                targets["hunt"] = prey
            reproduction_threshold = self.max_energy * 0.8
            if self.energy >= reproduction_threshold:
                nearby_herb_count = world.count_nearby_herbivores(self.x, self.y, radius=5)
                prey_ratio = 0.3 + 0.7 * min(nearby_herb_count / 8.0, 1.0)
                scores["reproduce"] = energy_ratio * self.genes["hunger_threshold"] * prey_ratio
            scores["move_random"] = 0.4
            scores["idle"]        = 0.3

        best = max(scores, key=scores.get)
        return best, targets.get(best)

    # --------------------------------------------------
    # NNによる行動選択 (ルールベースの_decide_actionの代わり)
    # 入力: 最近の食物の相対位置(2) / 最近の天敵(草食)または獲物(肉食)の相対位置(2) /
    #       エネルギー比率 / ゾーン / 気温 / 年齢  (相対位置は視野半径で割った値。いなければ0)
    # 出力softmaxの確率に従って 上/下/左/右/待機/繁殖 を選ぶ
    # --------------------------------------------------
    def _decide_action_nn(self, world):
        if self.org_type == "herbivore":
            food = world.get_nearest_food(self.x, self.y, radius=4)
            other = world.get_nearest_carnivore(self.x, self.y, radius=5)
            food_r, other_r = 4.0, 5.0
        else:
            food = None   # 肉食動物は食物を食べないので入力は常に0
            other = world.get_nearest_herbivore(self.x, self.y, radius=5)
            food_r, other_r = 4.0, 5.0

        inputs = np.zeros(NeuralNetwork.N_IN)
        if food:
            inputs[0] = (food[0] - self.x) / food_r
            inputs[1] = (food[1] - self.y) / food_r
        if other:
            inputs[2] = (other.x - self.x) / other_r
            inputs[3] = (other.y - self.y) / other_r
        inputs[4] = self.energy / self.max_energy
        inputs[5] = ZONE_INPUT[world.get_zone(self.x, self.y)]
        inputs[6] = config.TEMPERATURE / 40.0
        inputs[7] = min(self.age / 100.0, 1.0)

        probs = self.brain.forward(inputs)
        # 繁殖はエネルギーが閾値以上のときだけ可能 (足りないときは選べない)
        if self.energy < self.max_energy * 0.8:
            probs = probs.copy()
            probs[NN_REPRODUCE] = 0.0
            probs /= probs.sum()
        choice = int(np.random.choice(NeuralNetwork.N_OUT, p=probs))

        if choice < 4:
            return "move", NN_MOVES[choice]
        if choice == NN_REPRODUCE:
            if self.age < config.MIN_REPRODUCE_AGE:
                return "idle", None
            if self.org_type == "carnivore":
                # 密度抑制: グリッド全体の肉食/草食比が0.3を超えたら繁殖スコアは0 (繁殖しない)
                if world.get_carn_herb_ratio() > CARN_HERB_RATIO_LIMIT:
                    return "idle", None
                # ルールベースと同じ、近くの草食が少ないほど肉食が繁殖しにくくなる抑制
                nearby = world.count_nearby_herbivores(self.x, self.y, radius=5)
                prey_ratio = 0.3 + 0.7 * min(nearby / 8.0, 1.0)
                if np.random.random() >= prey_ratio:
                    return "idle", None
            return "reproduce", None
        return "idle", None

    # --------------------------------------------------
    # 行動の実行
    # --------------------------------------------------
    def _execute_action(self, action, target, world):

        if action == "flee":
            # 天敵と反対方向に逃げる
            if target:
                steps = self._movement_steps()
                blocked = 0
                cost  = self._move_energy_cost(world)
                for _ in range(steps):
                    dx = int(np.sign(self.x - target.x))
                    dy = int(np.sign(self.y - target.y))
                    # ランダム要素を加えて逃げ方に変化をつける
                    if dx == 0:
                        dx = np.random.randint(0, 2) * 2 - 1
                    if dy == 0:
                        dy = np.random.randint(0, 2) * 2 - 1
                    if not self._step(world, dx, dy):   # 移動先が海ならその移動はキャンセル
                        blocked += 1
                self.energy -= cost * (steps - blocked)

        elif action == "move_to_food":
            if target:
                self._move_toward(target[0], target[1], world)
                if world.consume_food(self.x, self.y):
                    self.energy = min(
                        self.energy + config.HERBIVORE_ENERGY_FROM_FOOD,
                        self.max_energy
                    )

        elif action == "hunt":
            if target and target.alive:
                self._move_toward(target.x, target.y, world)
                # 隣接マス(距離1以内)に入ったら捕食
                if abs(self.x - target.x) + abs(self.y - target.y) <= 1:
                    target.alive = False
                    self.energy = min(
                        self.energy + config.CARNIVORE_ENERGY_FROM_PREY,
                        self.max_energy
                    )

        elif action == "move_random":
            steps = self._movement_steps()
            blocked = 0
            cost  = self._move_energy_cost(world)
            for _ in range(steps):
                dx = np.random.randint(-1, 2)
                dy = np.random.randint(-1, 2)
                if not self._step(world, dx, dy):   # 移動先が海ならその移動はキャンセル
                    blocked += 1
            self.energy -= cost * (steps - blocked)

        elif action == "move":
            # NN用の方向移動: 動いた先で、草食は食物を食べ、肉食は隣接する草食を捕食する
            dx, dy = target
            steps = self._movement_steps()
            blocked = 0
            cost  = self._move_energy_cost(world)
            for _ in range(steps):
                if not self._step(world, dx, dy):   # 移動先が海ならその移動はキャンセル
                    blocked += 1
            self.energy -= cost * (steps - blocked)
            if self.org_type == "herbivore":
                if world.consume_food(self.x, self.y):
                    self.energy = min(self.energy + config.HERBIVORE_ENERGY_FROM_FOOD, self.max_energy)
            else:
                prey = world.get_nearest_herbivore(self.x, self.y, radius=1)
                if prey and prey.alive:
                    prey.alive = False
                    self.energy = min(self.energy + config.CARNIVORE_ENERGY_FROM_PREY, self.max_energy)

        elif action == "reproduce":
            world.spawn_offspring(self)
            cost = (config.HERBIVORE_REPRODUCTION_COST if self.org_type == "herbivore"
                    else config.CARNIVORE_REPRODUCTION_COST)
            self.energy -= cost

    # --------------------------------------------------
    # 1マス移動する。移動先が海(sea)なら移動をキャンセルしてFalseを返す (エネルギーコストなし)
    # --------------------------------------------------
    def _step(self, world, dx, dy):
        nx = max(0, min(config.GRID_SIZE - 1, self.x + dx))
        ny = max(0, min(config.GRID_SIZE - 1, self.y + dy))
        if world.get_zone(nx, ny) == "sea":
            return False
        self.x, self.y = nx, ny
        return True

    # --------------------------------------------------
    # 目標座標に近づく (speedが速い個体は1ターンに2マス進む)
    # --------------------------------------------------
    def _move_toward(self, target_x, target_y, world):
        steps = self._movement_steps()
        blocked = 0
        cost  = self._move_energy_cost(world)
        for _ in range(steps):
            dx = int(np.sign(target_x - self.x))
            dy = int(np.sign(target_y - self.y))
            if dx == 0 and dy == 0:
                break
            if not self._step(world, dx, dy):   # 移動先が海ならその移動はキャンセル
                blocked += 1
        self.energy -= cost * (steps - blocked)

    # --------------------------------------------------
    # speed遺伝子に応じた1ターンの移動マス数
    # (speedの値がそのまま2マス移動できる確率になる。2マス移動時のみエネルギー消費も2倍)
    # --------------------------------------------------
    def _movement_steps(self):
        if np.random.random() < self.genes["speed"]:
            return 2
        return 1

    # --------------------------------------------------
    # 移動コスト (現在地の地形により倍率がかかる)
    # 山: mountain_toleranceが低いほど倍率が上がる (1.0倍〜2.0倍)
    # 川: river_toleranceが低いほど倍率が上がる (1.0倍〜3.0倍)
    # --------------------------------------------------
    def _move_energy_cost(self, world):
        base = (config.HERBIVORE_MOVE_ENERGY_COST if self.org_type == "herbivore"
                else config.CARNIVORE_MOVE_ENERGY_COST)
        zone = world.get_zone(self.x, self.y)
        if zone == "mountain":
            multiplier = 2.0 - self.genes["mountain_tolerance"]
        elif zone == "river":
            multiplier = 3.0 - 2.0 * self.genes["river_tolerance"]
        else:
            multiplier = 1.0
        return base * multiplier

    # --------------------------------------------------
    # 子個体の遺伝子生成 (partnerがいれば交叉、いなければ自分の遺伝子をそのまま継承)
    # --------------------------------------------------
    def create_offspring_genes(self, partner=None):
        if partner is None:
            child_genes = self.genes.copy()
        else:
            child_genes = {
                key: (self.genes[key] if np.random.random() < 0.5 else partner.genes[key])
                for key in self.genes
            }

        for key in child_genes:
            if np.random.random() < config.MUTATION_RATE:
                child_genes[key] += np.random.normal(0, config.MUTATION_STRENGTH)
                child_genes[key] = float(np.clip(child_genes[key], 0.0, 1.0))
        return child_genes

    # --------------------------------------------------
    # 子個体のNN生成 (交叉+突然変異。create_offspring_genesと同様の仕組み)
    # --------------------------------------------------
    def create_offspring_brain(self, partner=None):
        return NeuralNetwork.offspring(self.brain, partner.brain if partner is not None else None)
