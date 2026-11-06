"""ゲームモードのステージイベント (隕石)。ゲームモードの main.py から呼ぶだけで、生態系のコードは変更しない。

data/stages.json のステージに、次のように書く:
  "events": [{"type": "meteor", "generation": 8, "radius": 12}, ...], "event_seed": 301
- 予告: イベントの1世代前の始まりに、そのとき生きている個体 (草食・肉食とも) の中から、event_seed と世代から決まる乱数で
  1匹選び、その個体のいるマスを落下の中心にする。盤面に赤い円 (半径 radius マス) と「隕石まであと1世代」を出す。
- 落下: そのイベントの世代の始まりに、円の中の生き物と食料を消す。円の距離の測り方は、スキルと同じ (中心からのマス距離 ≤ radius)。
  食料を消すときは、食料の数 (_food_count) と食料の索引 (_food_buckets) も合わせて更新する。地形は変えない。
- 穴: "crater_generations": N を書くと、落下のあと N 世代 (1世代=200ステップ) のあいだ、円の中で「そのステップで新しく湧いた食料」を
  確率で消す。確率は落下直後 100% から、N 世代かけて直線で 0% に下がる (穴が重なったところは、確率の大きい方)。
  各ステップの直前の食料の盤面 (snapshot) と比べて、新しく増えたものだけを消すので、スキルで撒いた食料は消えない。
  書いていない・0 なら、穴はできない。
- 衝突の冬: ステージに "impact_winter": {"scale": 0.4, "recovery_generations": 4} を書くと、隕石が落ちた瞬間から、
  食料の季節倍率 (config.SEASON_FOOD_MULT) に掛ける倍率が scale になり、recovery_generations 世代かけて直線で 1.0 に戻る
  (隕石が重なったときは、低い方の倍率)。毎ステップ、ステージ開始時の季節倍率にこの倍率を掛けた値を config に入れる。
  ステージを抜けるときは stage_setup.restore() が config を元に戻す。書いていないステージでは、config に触れない。
events がないステージ (飢饉など) と観察モードでは、何も起きない。
"""
import copy

import numpy as np
import pygame

import config

WARNING_COLOR = (255, 70, 70)
CRATER_COLOR = (120, 70, 30)         # 穴の色: 焼け跡らしい茶色 (確率が下がるにつれて薄くなる)
CRATER_EDGE = (70, 38, 14)           # 穴の縁 (少しだけ濃い茶色)
CRATER_ALPHA = 130
HAZE_COLOR = (150, 150, 160)         # 世界全体の食料が抑えられているしるし: 盤面全体の灰色の靄
HAZE_MAX_ALPHA = 64                  # 靄の濃さの上限 (約25%)。倍率が scale (最も低いとき) のときにこの濃さになる


def _inside(x, y, cx, cy, radius):
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


class StageEvents:
    def __init__(self, stage):
        events = stage.get("events") or []
        self.events = [dict(e) for e in events
                       if isinstance(e, dict) and e.get("type") == "meteor"
                       and isinstance(e.get("generation"), int) and isinstance(e.get("radius"), (int, float))]
        self.seed = int(stage.get("event_seed") or 0)
        self.pending = {}          # イベントの番号 → 予告した落下の中心 (x, y)
        self.log = []              # 落下の記録 (確認用)
        self.craters = []          # 穴: {"center", "radius", "steps" (続くステップ数), "elapsed" (落下からのステップ数)}
        self.crater_removed = 0    # 穴で消した新規食料の数 (確認用)
        self._crater_rng = np.random.RandomState((self.seed * 1000003 + 7) % (2 ** 32))   # シミュレーションの乱数とは別
        winter = stage.get("impact_winter")
        self.winter = None         # 衝突の冬の設定 {"scale", "steps"}
        if isinstance(winter, dict) and isinstance(winter.get("scale"), (int, float)) \
                and isinstance(winter.get("recovery_generations"), (int, float)) and winter["recovery_generations"] > 0:
            self.winter = {"scale": float(winter["scale"]),
                           "steps": int(winter["recovery_generations"] * config.MAX_STEPS_PER_GEN)}
        self.winters = []          # 落下からのステップ数 (衝突の冬が続いている隕石ごと)
        # ステージ開始時の季節倍率 (毎ステップ、これに衝突の冬の倍率を掛けて config に入れる)
        self._base_food_mult = copy.deepcopy(config.SEASON_FOOD_MULT) if self.winter else None

    def __bool__(self):
        return bool(self.events)

    def on_generation_start(self, world, generation):
        """世代の始まりに呼ぶ。表示するメッセージ (落下の結果) のリストを返す。"""
        messages = []
        for i, event in enumerate(self.events):
            if event["generation"] == generation:
                if i not in self.pending:               # 予告できなかった (最初の世代など) ときは、ここで決める
                    self._aim(world, i, generation)
                center = self.pending.pop(i, None)
                if center is not None:
                    messages.append(self._fall(world, center, event["radius"], generation))
                    crater = event.get("crater_generations")
                    if isinstance(crater, (int, float)) and crater > 0:
                        self.craters.append({"center": center, "radius": event["radius"],
                                             "steps": int(crater * config.MAX_STEPS_PER_GEN), "elapsed": 0})
                    if self.winter:
                        self.winters.append(0)          # 衝突の冬: この瞬間から、食料の倍率が scale になる
            elif event["generation"] == generation + 1:
                self._aim(world, i, generation)         # 1世代前の始まりに、落ちる場所を決めて予告する
        return messages

    def crater_chance(self, crater):
        """いまの、新規食料を消す確率 (落下直後 1.0 → 続く期間の終わりに 0.0)"""
        return max(0.0, 1.0 - crater["elapsed"] / crater["steps"])

    def food_multiplier(self):
        """衝突の冬の、いまの食料の倍率 (落下直後 scale → recovery_generations 世代かけて 1.0。重なったときは低い方)"""
        if not self.winters:
            return 1.0
        scale, steps = self.winter["scale"], self.winter["steps"]
        return min(scale + (1.0 - scale) * min(1.0, elapsed / steps) for elapsed in self.winters)

    def is_incoming(self):
        """予告が出ていて、まだ落下していない"""
        return bool(self.pending)

    def has_crater(self):
        """確率が0より大きい穴が、1つでもある"""
        return any(self.crater_chance(c) > 0 for c in self.craters)

    def hint_state(self):
        """リーフのヒントを選ぶための状態: 予告中か・穴があるか・いまの食料の倍率 (衝突の冬。なければ 1.0)"""
        return {"incoming": self.is_incoming(), "crater": self.has_crater(), "food_mult": self.food_multiplier()}

    def snapshot(self, world):
        """穴があるときだけ、食料の盤面のコピーを返す。"""
        return world.food_grid.copy() if self.craters else None

    def before_step(self, world):
        """ステップの直前に呼ぶ。衝突の冬の倍率を config に入れ、穴の処理のための食料の盤面のコピーを返す。"""
        if self.winter:
            m = self.food_multiplier()
            config.SEASON_FOOD_MULT = {k: v * m for k, v in self._base_food_mult.items()}
        return self.snapshot(world)

    def after_step(self, world, before):
        """ステップの直後に呼ぶ。そのステップで新しく湧いた食料のうち、穴の中のものを確率で消す。衝突の冬を1ステップ進める。"""
        if before is not None and self.craters:
            for x, y in np.argwhere(world.food_grid & ~before):
                chance = max((self.crater_chance(c) for c in self.craters
                              if _inside(x, y, c["center"][0], c["center"][1], c["radius"])), default=0.0)
                if chance > 0 and self._crater_rng.random_sample() < chance:
                    if world.consume_food(int(x), int(y)):       # _food_count と _food_buckets も合わせて更新される
                        self.crater_removed += 1
            for c in self.craters:
                c["elapsed"] += 1
            self.craters = [c for c in self.craters if c["elapsed"] < c["steps"]]
        if self.winters:
            self.winters = [e + 1 for e in self.winters if e + 1 < self.winter["steps"]]

    def _aim(self, world, index, generation):
        organisms = sorted(world.organisms, key=lambda o: (o.x, o.y, o.org_type))     # 並び順に左右されないようにする
        if not organisms:
            return
        rng = np.random.RandomState((self.seed * 1000003 + generation) % (2 ** 32))
        target = organisms[rng.randint(len(organisms))]
        self.pending[index] = (target.x, target.y)

    def _fall(self, world, center, radius, generation):
        cx, cy = center
        survivors, gone = [], 0
        for o in world.organisms:
            if _inside(o.x, o.y, cx, cy, radius):
                o.alive = False
                gone += 1
            else:
                survivors.append(o)
        world.organisms = survivors
        food = 0
        n = world.food_grid.shape[0]
        for x in range(max(0, int(cx - radius)), min(n, int(cx + radius) + 1)):
            for y in range(max(0, int(cy - radius)), min(n, int(cy + radius) + 1)):
                if _inside(x, y, cx, cy, radius) and world.food_grid[x, y]:
                    world.food_grid[x, y] = False
                    bucket = world._food_buckets.get((x // world.BLOCK_SIZE, y // world.BLOCK_SIZE))
                    if bucket is not None:
                        bucket.discard((x, y))
                    food += 1
        world._food_count -= food
        self.log.append({"generation": generation, "center": center, "organisms": gone, "food": food})
        return f"隕石が落ちた！ 生き物{gone}匹、食料{food}個が消えた"

    def draw(self, screen, renderer, font, board_size, small_font=None):
        """衝突の冬の靄と「世界全体の食料 ×0.59」 (倍率が 1.0 のときは、どちらも出さない)、穴 (茶色の半透明の円。確率が
        下がるにつれて薄くなる)、予告の赤い円と「隕石まであと1世代」を、盤面の上に描く。"""
        multiplier = self.food_multiplier() if self.winter else 1.0
        if multiplier < 0.995:                       # 表示が「×1.00」になるときは出さない
            strength = min(1.0, (1.0 - multiplier) / max(1e-6, 1.0 - self.winter["scale"]))
            haze = pygame.Surface((board_size, board_size), pygame.SRCALPHA)
            haze.fill(HAZE_COLOR + (int(HAZE_MAX_ALPHA * strength),))
            screen.blit(haze, (0, 0))                # 倍率が低いほど濃い (最も低いときで約25%)
            label = (small_font or font).render(f"世界全体の食料 ×{multiplier:.2f}", True, (255, 230, 200))
            box = label.get_rect(topright=(board_size - 8, 8)).inflate(14, 6)       # 盤面の右上の隅 (FPSなどの表示は左上)
            pygame.draw.rect(screen, (60, 35, 20), box, border_radius=5)
            pygame.draw.rect(screen, (190, 120, 70), box, 1, border_radius=5)
            screen.blit(label, label.get_rect(center=box.center))
        if not self.pending and not self.craters:
            return
        zoom = renderer.zoom
        clip = screen.get_clip()
        screen.set_clip(pygame.Rect(0, 0, board_size, board_size))
        for c in self.craters:
            (x, y), r = c["center"], int(c["radius"] * zoom)
            alpha = int(CRATER_ALPHA * self.crater_chance(c))
            if alpha <= 0:
                continue
            layer = pygame.Surface((2 * r + 2, 2 * r + 2), pygame.SRCALPHA)
            pygame.draw.circle(layer, CRATER_COLOR + (alpha,), (r + 1, r + 1), r)
            pygame.draw.circle(layer, CRATER_EDGE + (min(255, alpha + 70),), (r + 1, r + 1), r, 2)     # 縁を少しだけ濃く
            screen.blit(layer, (int(y * zoom + zoom / 2 - renderer.off_x) - r - 1, int(x * zoom + zoom / 2 - renderer.off_y) - r - 1))
        if not self.pending:
            screen.set_clip(clip)
            return
        for i, (x, y) in self.pending.items():
            radius = self.events[i]["radius"]
            px = int(y * zoom + zoom / 2 - renderer.off_x)
            py = int(x * zoom + zoom / 2 - renderer.off_y)
            r = int(radius * zoom)
            layer = pygame.Surface((2 * r + 4, 2 * r + 4), pygame.SRCALPHA)
            pygame.draw.circle(layer, WARNING_COLOR + (70,), (r + 2, r + 2), r)
            pygame.draw.circle(layer, WARNING_COLOR + (255,), (r + 2, r + 2), r, 3)
            screen.blit(layer, (px - r - 2, py - r - 2))
        text = font.render("隕石まであと1世代", True, (255, 255, 255))
        box = text.get_rect(midtop=(board_size // 2, 72)).inflate(24, 12)
        pygame.draw.rect(screen, (150, 20, 20), box, border_radius=6)
        pygame.draw.rect(screen, WARNING_COLOR, box, 2, border_radius=6)
        screen.blit(text, text.get_rect(center=box.center))
        screen.set_clip(clip)
