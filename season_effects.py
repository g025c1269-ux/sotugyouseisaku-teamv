# =============================================
# season_effects.py — 季節の演出 (見た目だけ。シミュレーションには一切影響しない)
#
#   春: 桜の花びらが舞う        アイコン: 桜の花
#   夏: 右上の角から光の筋3本   アイコン: 太陽
#   秋: モミジが舞い落ちる      アイコン: 紅葉
#   冬: 雪が降る                アイコン: 雪ダルマ
#
# 季節は「世代」から決まる。気温(world.update_temperature)と同じ
# sin波の1周期 = config.SEASON_CYCLE 世代 を4等分している (1世代目が春の始まり)ので、
# 気温の上がり始め=春 / 最高=夏 / 下がり始め=秋 / 最低=冬 に一致する。
# 季節が影響するのは気温だけ(気温の計算は world.py のまま変更なし)。
#
# 乱数は専用の random.Random を使うので、np.random や random の
# グローバル状態(=シミュレーションの再現性)には触れない。
# =============================================

import math
import random

import config

SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_NAMES_JA = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
SEASON_COLORS = {
    "spring": (255, 183, 197),
    "summer": (255, 213, 79),
    "autumn": (240, 130, 50),
    "winter": (190, 225, 255),
}


def season_of(generation):
    """世代番号から季節名を返す。1世代目が春の始まり。

    SEASON_CYCLE=12(1世代=1ヶ月)なら 1〜3世代=春 / 4〜6=夏 / 7〜9=秋 / 10〜12=冬 (13世代目から2年目の春)。
    気温(world.update_temperature)は夏の中央(5世代目)で最高、冬の中央(11世代目)で最低になる。
    """
    cycle = max(1, config.SEASON_CYCLE)
    phase = ((generation - 1) % cycle) / cycle
    return SEASONS[int(phase * 4) % 4]


def year_of(generation):
    """世代番号から「何年目か」を返す (1世代目 = 1年目)。表示用。"""
    return (generation - 1) // max(1, config.SEASON_CYCLE) + 1


def season_label(generation):
    """表示用の「N年目 春」の文字列"""
    return f"{year_of(generation)}年目 {SEASON_NAMES_JA[season_of(generation)]}"


# ---------------------------------------------
# ドット絵スプライト
# ---------------------------------------------
# 桜の花びら (5x4)
PETAL = [
    ".pp..",
    "pwppp",
    "ppppd",
    ".pdd.",
]
PETAL_PALETTE = {"p": (255, 176, 196), "w": (255, 226, 233), "d": (234, 132, 164)}

# モミジ (9x9)
MAPLE = [
    "....r....",
    "..r.rr.r.",
    ".rrrvrrrr",
    "..rrvrrr.",
    ".rrrvrrrr",
    "...rvrr..",
    "....rr...",
    "....b....",
    "....b....",
]
MAPLE_PALETTES = [   # 赤 / 橙 の2色
    {"r": (205, 58, 34), "v": (140, 32, 24), "b": (100, 56, 30)},
    {"r": (238, 136, 40), "v": (170, 80, 28), "b": (100, 56, 30)},
]

# イチョウの葉 (9x9, 扇形)
GINKGO = [
    ".yyy.yyy.",
    "yyyyyyyyy",
    "yyyyvyyyy",
    ".yyyvyyy.",
    "..yyvyy..",
    "...yvy...",
    "....y....",
    "....b....",
    "....b....",
]
GINKGO_PALETTE = {"y": (242, 202, 56), "v": (205, 152, 30), "b": (110, 80, 30)}
LEAF_VARIANTS = len(MAPLE_PALETTES) + 1   # モミジ2色 + イチョウ

ROTATIONS = 24   # 回転スプライトの段階数 (15度刻み)


# ---------------------------------------------
# 季節アイコン (16x16。図形データで持つので描画ライブラリに依存しない)
#   ("circle", 色, (cx, cy), 半径) / ("polygon", 色, [点...])
#   ("line", 色, 始点, 終点, 太さ)
# ---------------------------------------------
def _icon_primitives(season):
    prims = []
    if season == "spring":                      # 桜の花
        dark, pink = (226, 122, 158), (255, 187, 204)
        centers = []
        for k in range(5):
            a = math.radians(-90 + 72 * k)
            centers.append((round(8 + 4.2 * math.cos(a)), round(8 + 4.2 * math.sin(a))))
        for c in centers:
            prims.append(("circle", dark, c, 4))
        for c in centers:
            prims.append(("circle", pink, c, 3))
        prims.append(("circle", (255, 214, 90), (8, 8), 2))
        for k in range(5):                      # おしべ
            a = math.radians(-90 + 72 * k + 36)
            prims.append(("circle", (200, 70, 110), (round(8 + 3.2 * math.cos(a)), round(8 + 3.2 * math.sin(a))), 0))
    elif season == "summer":                    # 太陽
        for k in range(8):
            a = math.radians(45 * k)
            p0 = (round(8 + 6.0 * math.cos(a)), round(8 + 6.0 * math.sin(a)))
            p1 = (round(8 + 7.6 * math.cos(a)), round(8 + 7.6 * math.sin(a)))
            prims.append(("line", (255, 160, 30), p0, p1, 2 if k % 2 == 0 else 1))
        prims.append(("circle", (240, 140, 20), (8, 8), 5))
        prims.append(("circle", (255, 213, 79), (8, 8), 4))
        prims.append(("circle", (255, 244, 170), (7, 7), 1))
    elif season == "autumn":                    # 紅葉
        right = [(8, 1), (10, 4), (12, 3), (11, 7), (15, 6), (13, 9), (14, 12), (9, 11), (9, 13)]
        left = [(16 - x, y) for x, y in reversed(right[1:])]
        outline = right + left
        prims.append(("polygon", (205, 58, 34), outline))
        prims.append(("line", (140, 32, 24), (8, 13), (8, 5), 1))
        prims.append(("line", (140, 32, 24), (8, 9), (11, 7), 1))
        prims.append(("line", (140, 32, 24), (8, 9), (5, 7), 1))
        prims.append(("line", (100, 56, 30), (8, 12), (8, 15), 1))
    else:                                       # 雪ダルマ
        edge, snow = (130, 160, 195), (246, 249, 255)
        prims.append(("line", (110, 70, 40), (4, 10), (1, 7), 1))     # 腕
        prims.append(("line", (110, 70, 40), (12, 10), (15, 7), 1))
        prims.append(("circle", edge, (8, 11), 5))
        prims.append(("circle", snow, (8, 11), 4))
        prims.append(("circle", edge, (8, 4), 4))
        prims.append(("circle", snow, (8, 4), 3))
        prims.append(("line", (210, 60, 60), (5, 7), (11, 7), 2))     # マフラー
        prims.append(("line", (30, 30, 40), (7, 3), (7, 3), 1))       # 目
        prims.append(("line", (30, 30, 40), (9, 3), (9, 3), 1))
        prims.append(("line", (255, 140, 30), (8, 5), (10, 5), 1))    # にんじん鼻
        prims.append(("line", (30, 30, 40), (8, 10), (8, 10), 1))     # ボタン
        prims.append(("line", (30, 30, 40), (8, 13), (8, 13), 1))
    return prims


class _Particle:
    __slots__ = ("x", "y", "vx", "vy", "phase", "pspeed", "amp", "angle", "spin", "variant", "size", "kind")


class SeasonEffects:
    MAX_PARTICLES = {"petal": 80, "leaf": 55, "snow": 140}
    SPAWN_RATE = {"petal": 0.7, "leaf": 0.5, "snow": 1.2}   # 1フレームあたりの発生数

    def __init__(self, pygame, view, label_font=None):
        self.pg = pygame
        self.view = view
        self.font = label_font
        self.rng = random.Random(20240901)   # シミュレーションの乱数とは独立
        self.season = None
        self.particles = []
        self._acc = 0.0
        self.sun_level = 0.0                 # 0=消えている 1=最大 (ふわっと出入りさせる)
        self._build_sprites()
        self._build_sun()
        self._icons = {s: self._build_icon(s) for s in SEASONS}

    # =================================================
    # 素材づくり
    # =================================================
    def _make_surface(self, rows, palette, scale):
        pg = self.pg
        h, w = len(rows), len(rows[0])
        base = pg.Surface((w, h), pg.SRCALPHA)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in palette:
                    base.set_at((x, y), palette[ch] + (255,))
        return pg.transform.scale(base, (w * scale, h * scale))

    def _rotations(self, surface):
        pg = self.pg
        return [pg.transform.rotate(surface, 360.0 / ROTATIONS * i) for i in range(ROTATIONS)]

    def _build_sprites(self):
        # sprites[kind][variant][size] -> 回転済みスプライトのリスト
        self.sprites = {
            "petal": [[self._rotations(self._make_surface(PETAL, PETAL_PALETTE, s)) for s in (2, 3)]],
            "leaf": [[self._rotations(self._make_surface(MAPLE, pal, s)) for s in (1, 2)]
                     for pal in MAPLE_PALETTES]
                    + [[self._rotations(self._make_surface(GINKGO, GINKGO_PALETTE, s)) for s in (1, 2)]],
        }

    def _build_sun(self):
        """右上の角から左下へ伸びる光の筋3本 + 角のほのかな光。あらかじめ1回だけ描く。"""
        pg, v = self.pg, self.view
        self.sun_layers = []   # (surface, 描画位置, 位相, 明滅の速さ)
        for deg, phase, speed in ((24, 0.0, 0.9), (44, 2.1, 0.7), (64, 4.2, 1.1)):
            surf = pg.Surface((v, v), pg.SRCALPHA)
            a = math.radians(deg)
            dx, dy = -math.cos(a), math.sin(a)      # 左下向き
            px, py = dy, -dx                        # それに直交する向き
            length, n = v * 1.05, 28
            for half_deg, alpha in ((7.0, 24), (3.2, 50)):   # 広くて淡い層 + 細くて濃い芯
                half = math.tan(math.radians(half_deg))
                for s in range(n):
                    d0, d1 = length * s / n, length * (s + 1) / n
                    fade = (1.0 - (s + 0.5) / n) ** 1.4
                    color = (255, 238, 160, int(alpha * fade))
                    pts = [(v + dx * d0 + px * half * d0, dy * d0 + py * half * d0),
                           (v + dx * d1 + px * half * d1, dy * d1 + py * half * d1),
                           (v + dx * d1 - px * half * d1, dy * d1 - py * half * d1),
                           (v + dx * d0 - px * half * d0, dy * d0 - py * half * d0)]
                    pg.draw.polygon(surf, color, pts)
            self.sun_layers.append((surf, (0, 0), phase, speed))
        glow_r = 120
        glow = pg.Surface((glow_r, glow_r), pg.SRCALPHA)
        for r in range(glow_r, 6, -6):
            pg.draw.circle(glow, (255, 232, 140, int(6 + (glow_r - r) * 0.45)), (glow_r, 0), r)
        self.sun_layers.append((glow, (v - glow_r, 0), 1.0, 0.5))

    def _build_icon(self, season):
        pg = self.pg
        surf = pg.Surface((16, 16), pg.SRCALPHA)
        for prim in _icon_primitives(season):
            kind = prim[0]
            if kind == "circle":
                _, color, center, radius = prim
                if radius <= 0:
                    surf.set_at(center, color + (255,))
                else:
                    pg.draw.circle(surf, color, center, radius)
            elif kind == "polygon":
                pg.draw.polygon(surf, prim[1], prim[2])
            else:
                _, color, p0, p1, width = prim
                if p0 == p1:
                    surf.set_at(p0, color + (255,))
                else:
                    pg.draw.line(surf, color, p0, p1, width)
        return pg.transform.scale(surf, (48, 48))   # ドットのまま3倍

    # =================================================
    # 粒子 (花びら・モミジ・雪)
    # =================================================
    def _kind_of(self, season):
        return {"spring": "petal", "autumn": "leaf", "winter": "snow"}.get(season)

    def _spawn(self, kind, anywhere=False):
        r, v = self.rng, self.view
        p = _Particle()
        p.kind = kind
        p.x = r.uniform(-v * 0.25, v)
        p.y = r.uniform(-20, v) if anywhere else -r.uniform(4, 20)
        p.phase = r.uniform(0, math.tau)
        p.angle = r.uniform(0, 360)
        p.variant = 0
        if kind == "petal":
            p.vx, p.vy = r.uniform(0.4, 0.9), r.uniform(0.5, 1.1)
            p.pspeed, p.amp = r.uniform(0.03, 0.07), 0.35
            p.spin = r.uniform(-2.5, 2.5)
            p.size = 0 if r.random() < 0.6 else 1
        elif kind == "leaf":
            p.vx, p.vy = r.uniform(0.1, 0.5), r.uniform(0.6, 1.3)
            p.pspeed, p.amp = r.uniform(0.04, 0.08), r.uniform(0.8, 1.6)
            p.spin = 0.0
            p.variant = r.randrange(LEAF_VARIANTS)
            p.size = 0 if r.random() < 0.65 else 1
        else:
            p.vx, p.vy = r.uniform(-0.1, 0.3), r.uniform(0.7, 1.7)
            p.pspeed, p.amp = r.uniform(0.02, 0.06), 0.25
            p.spin = 0.0
            p.size = r.choice((0, 0, 1, 2))
        self.particles.append(p)

    def update(self, season):
        kind = self._kind_of(season)
        if season != self.season:
            # 季節が変わった瞬間: 前の季節の粒子は自然に落ちきるまで残し、新しい季節を散らして始める
            first = self.season is None
            self.season = season
            if kind is not None:
                count = self.MAX_PARTICLES[kind] // (2 if first else 3)
                for _ in range(count):
                    self._spawn(kind, anywhere=True)
        if kind is not None:
            self._acc += self.SPAWN_RATE[kind]
            alive = sum(1 for p in self.particles if p.kind == kind)
            while self._acc >= 1.0:
                self._acc -= 1.0
                if alive < self.MAX_PARTICLES[kind]:
                    self._spawn(kind)
                    alive += 1
        else:
            self._acc = 0.0

        v = self.view
        kept = []
        for p in self.particles:
            p.phase += p.pspeed
            if p.kind == "petal":
                p.x += p.vx + math.sin(p.phase) * p.amp
                p.y += p.vy
                p.angle += p.spin
            elif p.kind == "leaf":
                p.x += p.vx + math.sin(p.phase) * p.amp
                p.y += p.vy * (0.85 + 0.15 * math.cos(p.phase * 2))
            else:
                p.x += p.vx + math.sin(p.phase) * p.amp
                p.y += p.vy
            if p.y < v + 24 and -v * 0.6 < p.x < v + 24:
                kept.append(p)
        self.particles = kept

        target = 1.0 if season == "summer" else 0.0
        self.sun_level += max(-0.015, min(0.015, target - self.sun_level))

    # =================================================
    # 描画
    # =================================================
    def draw(self, screen, season):
        """盤面の上に季節の演出を重ねる。"""
        pg, v = self.pg, self.view
        self.update(season)
        old_clip = screen.get_clip()
        screen.set_clip(pg.Rect(0, 0, v, v))

        if self.sun_level > 0.001:
            t = pg.time.get_ticks() / 1000.0
            for surf, pos, phase, speed in self.sun_layers:
                pulse = 0.65 + 0.35 * math.sin(t * speed + phase)
                surf.set_alpha(int(255 * self.sun_level * pulse))
                screen.blit(surf, pos)

        for p in self.particles:
            if p.kind == "snow":
                x, y = int(p.x), int(p.y)
                if p.size == 0:
                    screen.fill((255, 255, 255), (x, y, 2, 2))
                elif p.size == 1:
                    screen.fill((226, 238, 255), (x, y, 3, 3))
                else:                                  # 十字の結晶
                    screen.fill((255, 255, 255), (x - 2, y, 5, 1))
                    screen.fill((255, 255, 255), (x, y - 2, 1, 5))
                    screen.fill((200, 224, 255), (x - 1, y - 1, 3, 3))
                continue
            deg = p.angle
            if p.kind == "leaf":
                deg = p.angle + 50 * math.sin(p.phase)   # ひらひら揺れながら落ちる
            sprite = self.sprites[p.kind][p.variant][p.size][int((deg % 360) / (360 / ROTATIONS)) % ROTATIONS]
            screen.blit(sprite, sprite.get_rect(center=(int(p.x), int(p.y))))

        screen.set_clip(old_clip)

    def draw_badge(self, screen, season, temperature, year=None, generation=None):
        """右下に、いまの季節のアイコン・名前・(何年目か)・気温を表示する。generationを渡すと年間ゲージも出す。"""
        pg, v = self.pg, self.view
        w, h = (136 if year is not None else 112), 58
        rect = pg.Rect(v - w - 8, v - h - 8, w, h)
        shade = pg.Surface((w, h), pg.SRCALPHA)
        pg.draw.rect(shade, (0, 0, 0, 150), shade.get_rect(), border_radius=8)
        pg.draw.rect(shade, SEASON_COLORS[season] + (200,), shade.get_rect(), 1, border_radius=8)
        screen.blit(shade, rect.topleft)
        screen.blit(self._icons[season], (rect.x + 5, rect.y + 5))
        if self.font is not None:
            name = self.font.render(SEASON_NAMES_JA[season], True, SEASON_COLORS[season])
            name = pg.transform.scale(name, (name.get_width() * 2, name.get_height() * 2))
            screen.blit(name, (rect.x + 62, rect.y + 6))
            if year is not None:
                yt = self.font.render(f"{year}年目", True, (255, 255, 255))
                screen.blit(yt, (rect.x + 62 + name.get_width() + 6, rect.y + 6 + name.get_height() - yt.get_height() - 4))
            temp = self.font.render(f"{temperature:.1f}°C", True, (255, 255, 255))
            screen.blit(temp, (rect.x + 62, rect.bottom - temp.get_height() - 6))
        if generation is not None:
            self.draw_year_gauge(screen, generation, rect)

    def draw_year_gauge(self, screen, generation, badge_rect):
        """バッジの上に、1年(SEASON_CYCLE世代)の進み具合を示すゲージを描く。
        1世代=1マス。季節の色で塗り分け、いまの世代のマスだけ明るく白い枠で強調する。"""
        pg = self.pg
        n = max(1, config.SEASON_CYCLE)
        cur = (generation - 1) % n + 1
        gap, cell_h = 2, 9
        cell_w = max(2, (badge_rect.width - gap * (n - 1)) // n)
        total_w = cell_w * n + gap * (n - 1)
        x0, y0 = badge_rect.x, badge_rect.y - cell_h - 8
        back = pg.Surface((total_w + 8, cell_h + 8), pg.SRCALPHA)
        pg.draw.rect(back, (0, 0, 0, 150), back.get_rect(), border_radius=5)
        screen.blit(back, (x0 - 4, y0 - 4))
        for i in range(1, n + 1):
            color = SEASON_COLORS[season_of(i)]
            cell = pg.Rect(x0 + (i - 1) * (cell_w + gap), y0, cell_w, cell_h)
            if i == cur:
                pg.draw.rect(screen, color, cell.inflate(2, 4))
                pg.draw.rect(screen, (255, 255, 255), cell.inflate(2, 4), 2)
            else:
                pg.draw.rect(screen, tuple(int(c * 0.4) for c in color), cell)
