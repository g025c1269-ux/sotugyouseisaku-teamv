# =============================================
# pixel_art.py — ドット絵スタイルの描画モジュール (ズーム・ミニマップ対応)
#
#   renderer = PixelRenderer(pygame, world, label_font)
#   renderer.draw(screen, world, selected_org)
#
# 表示は3段階のズーム (1マスのpx数):
#     8px  俯瞰 : 盤面全体。個体は種類別の色の点 (群れの分布を見る)
#    16px  標準 : 盤面の1/4。16x16のスプライトで遺伝子が見た目に出る
#    32px  接近 : 盤面の1/16。スプライトを2倍で表示
#
# 遺伝子の見た目 (すべて3段階):
#   山耐性 → 角 (なし/小/大) + 太い足とひづめ
#   川耐性 → 水色の水かき足 → 背びれ・尾びれ
#   耐寒性 → 体色 + 毛のもこもこ (なし/少/多)
#   代謝   → 体の大きさ
#   速度   → 足の長さ
# =============================================

import random

import numpy as np
import config
from season_effects import SeasonEffects, SeasonTerrain, season_of, season_stage, year_of

CELL = 4                    # 地形タイルの基本ピクセル数 (俯瞰の1マス)。160マス x 4px = 640px
ZOOM_LEVELS = (4, 16, 32)   # 1マスのピクセル数 (4=俯瞰, 16=標準, 32=接近)
SPRITE = 16                 # スプライトの基本サイズ

# ---------------------------------------------
# 配色
# ---------------------------------------------
TERRAIN_PALETTE = {
    "grassland": {"base": (106, 190, 48), "dark": (79, 160, 40),  "light": (140, 215, 70)},
    "desert":    {"base": (232, 201, 122), "dark": (210, 176, 98), "light": (245, 226, 160)},
    "mountain":  {"base": (140, 110, 90),  "dark": (100, 76, 60),  "light": (176, 150, 128)},
    "river":     {"base": (60, 140, 230),  "dark": (40, 100, 190), "light": (130, 200, 255)},
    "sea":       {"base": (20, 60, 140),   "dark": (12, 40, 105),  "light": (60, 110, 190)},   # 川より濃い青
}
ZONE_NAMES_JA = {"grassland": "草原", "desert": "砂漠", "mountain": "山", "river": "川", "sea": "海"}

BERRY = [
    "....g...",
    "...g....",
    "..ooo...",
    ".orrro..",
    ".orwro..",
    ".orrro..",
    "..ooo...",
    "........",
]
BERRY_PALETTE = {"o": (90, 20, 40), "r": (230, 60, 80), "w": (255, 200, 210), "g": (40, 120, 40)}

OUTLINE = (30, 24, 32)
BONE    = (238, 228, 200)
WEBBING = (80, 170, 255)
HOOF    = (60, 46, 44)
WHITE   = (248, 248, 255)

DOT_HERB = (255, 255, 255)    # 俯瞰の草食動物の点の色 (白)
DOT_CARN = (255, 75, 65)
DOT_EDGE = (20, 20, 30)

COLD_BUCKETS = 6             # 体色の段階数 (スプライトキャッシュ抑制)


def _lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _lvl(v, lo=0.34, hi=0.67):
    """遺伝子値(0〜1) → 3段階 (0/1/2)"""
    return 0 if v < lo else (1 if v < hi else 2)


# =============================================
# 遺伝子 → 16x16 ピクセル配列 (pygameに依存しない)
# 右向きで描き、左向きは反転する。戻り値は [行][列] = (r,g,b) または None
# =============================================
def compose_pixels(org_type, frame, genes):
    W = H = SPRITE
    grid = [[None] * W for _ in range(H)]

    def put(x, y, c):
        if 0 <= x < W and 0 <= y < H:
            grid[y][x] = c

    def rect(x0, y0, x1, y1, c):
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                put(xx, yy, c)

    herb = (org_type == "herbivore")
    cold = genes["cold_resistance"]
    cb = min(COLD_BUCKETS - 1, int(cold * COLD_BUCKETS))
    t = cb / (COLD_BUCKETS - 1)
    if herb:
        body = _lerp((214, 170, 120), (236, 236, 246), t)
        eye = (20, 20, 30)
    else:
        body = _lerp((224, 96, 52), (118, 128, 152), t)
        eye = (255, 235, 90)
    dark = _lerp(body, (0, 0, 0), 0.35)
    belly = _lerp(body, (255, 255, 255), 0.45)

    fur = _lvl(cold)
    meta = _lvl(genes["metabolism"])
    mt = _lvl(genes["mountain_tolerance"])
    rv = _lvl(genes["river_tolerance"])
    sp = _lvl(genes["speed"], 0.4, 0.6)   # speedの初期範囲は0.2〜0.8

    # --- 寸法 (代謝=体の大きさ / 速度=足の長さ) ---
    w = 8 + 2 * meta           # 体の幅 8/10/12
    h = 4 + meta               # 体の高さ 4/5/6
    leg_len = 2 + sp           # 足の長さ 2/3/4
    xr = 12                    # 体の右端
    bx0 = xr - w + 1           # 体の左端
    gy = 14                    # 接地するy
    bb = gy - leg_len          # 体の下端
    top = bb - h + 1           # 体の上端
    hy = top - 2               # 頭の上端 (頭は11〜14列, 4x4)

    # --- しっぽ ---
    if herb:
        put(bx0 - 1, top + 1, WHITE)
        put(bx0 - 1, top + 2, WHITE)
    else:
        put(bx0 - 1, top + 1, dark)
        put(bx0 - 2, top, dark)
        put(bx0 - 3, top - 1, dark)
    if rv == 2:                # 尾びれ
        put(bx0 - 1, top + 1, WEBBING)
        put(bx0 - 1, top + 2, WEBBING)
        put(bx0 - 2, top + 1, WEBBING)

    # --- 胴体 ---
    rect(bx0, top, xr, bb, body)
    rect(bx0 + 1, bb, xr - 2, bb, belly)

    # --- 毛 (耐寒性): 背中のもこもこ ---
    #   少: 2ドット幅のふくらみが並ぶ / 多: 1段目がつながり、その上にもふくらみ
    if fur == 1:
        for x in range(bx0, 11):
            if (x - bx0) % 3 != 2:
                put(x, top - 1, belly)
    if fur == 2:
        for x in range(bx0, 11):
            put(x, top - 1, WHITE)
            if (x - bx0) % 3 != 2:
                put(x, top - 2, WHITE)

    # --- 足 (速度=長さ / 山耐性=太さとひづめ / 川耐性=水かき) ---
    back, front = bx0 + 1, xr - 1
    if frame == 1:
        back, front = back - 1, front + 1
    leg_w = 2 if mt == 2 else 1
    for lx in (back, front):
        rect(lx, bb + 1, lx + leg_w - 1, gy, dark)
        foot = HOOF if mt >= 1 else dark
        rect(lx, gy, lx + leg_w - 1, gy, foot)
        if rv >= 1:            # 水かき: 足先が水色に広がる
            rect(lx - 1, gy, lx + leg_w, gy, WEBBING)

    # --- 毛 (最大): おなかのふさふさ ---
    if fur == 2:
        for x in range(bx0, xr - 1, 2):
            put(x, bb + 1, WHITE)

    # --- 頭 ---
    rect(11, hy, 14, hy + 3, body)
    if not herb:               # 肉食: とがった耳
        put(11, hy - 1, dark)
        put(11, hy - 2, dark)
        put(14, hy - 1, dark)
        put(14, hy - 2, dark)
    put(14, hy + 2, dark)      # 鼻

    # --- 角 (山耐性) ---
    horn_x = (12, 14) if herb else (12, 13)
    if mt >= 1:
        for hx in horn_x:
            put(hx, hy - 1, BONE)
    if mt == 2:
        for hx in horn_x:
            put(hx, hy - 2, BONE)
        put(horn_x[0] - 1, hy - 2, BONE)   # 枝分かれ

    # --- 背びれ (川耐性・最大) ---
    if rv == 2:
        mid = (bx0 + 10) // 2
        rect(mid - 1, top - 1, mid + 1, top - 1, WEBBING)
        put(mid, top - 2, WEBBING)

    # --- 自動で輪郭線をつける ---
    out = [row[:] for row in grid]
    for y in range(H):
        for x in range(W):
            if grid[y][x] is None:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] is not None:
                        out[y][x] = OUTLINE
                        break
    out[hy + 1][13] = eye      # 目
    return out


class PixelRenderer:
    def __init__(self, pygame, world, label_font=None):
        self.pg = pygame
        self.grid = config.GRID_SIZE
        self.view = self.grid * CELL      # 画面(ビューポート)の一辺 = 俯瞰時に盤面全体が収まる大きさ
        self.label_font = label_font
        self._sprite_cache = {}
        self._berry_cache = {}
        self._prev = {}            # id(個体) -> (個体, col, row)  ※参照を保持してidの再利用を防ぐ
        self._facing = {}
        self._moved = {}
        self._effects = []
        self._world_ref = None
        self._tint_temp = None
        self._tint_surface = None
        self._rng = random.Random(12345)
        self.season_fx = SeasonEffects(pygame, self.view, label_font)   # 季節の演出 (見た目のみ)
        self.show_food = True      # 食物(木の実)を描くか (Vキーで切り替え)
        self.show_season_fx = True # 季節エフェクト(桜・紅葉・雪・日差し)を描くか (Eキーで切り替え。季節バッジは常に表示)

        # カメラ
        self.zoom = ZOOM_LEVELS[0]
        self.off_x = 0
        self.off_y = 0

        self.terrain = [self._build_terrain(world, frame) for frame in (0, 1)]
        # 季節ごとの地形の色 (春=元の地形。夏秋冬は色を置き換えて作る) と、春の川の花びら
        self.season_terrain = SeasonTerrain(pygame, self.terrain, world, self.view, TERRAIN_PALETTE)
        self._terrain_key = ("spring", 0)
        self._labels = self._build_labels(world)
        self._berry_base = self._make_surface(BERRY, BERRY_PALETTE)

        # ミニマップ (1マス1px)
        self.mm_scale = 1
        self.mm_size = self.grid * self.mm_scale
        self.mm_rect = pygame.Rect(8, self.view - self.mm_size - 8, self.mm_size, self.mm_size)
        self._mm_base = pygame.transform.scale(self.terrain[0], (self.mm_size, self.mm_size))

    # =================================================
    # カメラ操作
    # =================================================
    def _clamp(self):
        max_off = self.grid * self.zoom - self.view
        self.off_x = max(0, min(max_off, self.off_x))
        self.off_y = max(0, min(max_off, self.off_y))

    def set_zoom(self, new_zoom, anchor=None):
        """anchor=(px,py)の位置にある地点が動かないようにズームする"""
        if new_zoom == self.zoom:
            return
        ax, ay = anchor if anchor else (self.view // 2, self.view // 2)
        wx = (self.off_x + ax) / self.zoom
        wy = (self.off_y + ay) / self.zoom
        self.zoom = new_zoom
        self.off_x = int(wx * new_zoom - ax)
        self.off_y = int(wy * new_zoom - ay)
        self._clamp()

    def zoom_step(self, direction, anchor=None):
        i = ZOOM_LEVELS.index(self.zoom) + (1 if direction > 0 else -1)
        i = max(0, min(len(ZOOM_LEVELS) - 1, i))
        self.set_zoom(ZOOM_LEVELS[i], anchor)

    def pan(self, dx, dy):
        self.off_x += dx
        self.off_y += dy
        self._clamp()

    def center_on_cell(self, row, col):
        self.off_x = int((col + 0.5) * self.zoom - self.view / 2)
        self.off_y = int((row + 0.5) * self.zoom - self.view / 2)
        self._clamp()

    def center_on_org(self, org):
        self.center_on_cell(org.x, org.y)

    def minimap_hit(self, mx, my):
        """ミニマップ上のクリックなら (row, col) を返す。ズーム中だけ有効。"""
        if self.zoom == ZOOM_LEVELS[0] or not self.mm_rect.collidepoint(mx, my):
            return None
        col = (mx - self.mm_rect.left) / self.mm_scale
        row = (my - self.mm_rect.top) / self.mm_scale
        return row, col

    def find_org(self, world, mx, my):
        """画面上の座標(mx,my)に一番近い個体を返す (遠ければNone)"""
        z = self.zoom
        max_d = max(10, z * 0.7)
        best, best_d2 = None, max_d * max_d
        for o in world.organisms:
            cx = o.y * z + z / 2 - self.off_x
            cy = o.x * z + z / 2 - self.off_y
            d2 = (cx - mx) ** 2 + (cy - my) ** 2
            if d2 < best_d2:
                best, best_d2 = o, d2
        return best

    # =================================================
    # 汎用: 文字列配列 → Surface
    # =================================================
    def _make_surface(self, rows, palette):
        pg = self.pg
        surf = pg.Surface((len(rows[0]), len(rows)), pg.SRCALPHA)
        for yy, row in enumerate(rows):
            for xx, ch in enumerate(row):
                color = palette.get(ch)
                if color is not None:
                    surf.set_at((xx, yy), color + (255,))
        return surf

    # =================================================
    # 地形 (8pxタイルで盤面全体を1枚に焼き込み → ズーム時は切り出して整数倍に拡大)
    # =================================================
    def _make_tile_variants(self, zone, frame, rng, n=6):
        pg = self.pg
        pal = TERRAIN_PALETTE[zone]
        tiles = []
        for _ in range(n):
            t = pg.Surface((CELL, CELL))
            t.fill(pal["base"])
            if zone == "grassland":
                for _ in range(rng.randint(2, 4)):
                    t.set_at((rng.randrange(CELL), rng.randrange(CELL)), pal["dark"])
                if rng.random() < 0.35:
                    x, y = rng.randrange(1, 7), rng.randrange(2, 7)
                    t.set_at((x, y), pal["light"]); t.set_at((x, y - 1), pal["light"])
                    t.set_at((x - 1, y - 2), pal["light"]); t.set_at((x + 1, y - 2), pal["light"])
                if rng.random() < 0.12:
                    x, y = rng.randrange(1, 7), rng.randrange(1, 7)
                    t.set_at((x, y), rng.choice([(255, 120, 160), (255, 235, 90), (255, 255, 255)]))
            elif zone == "desert":
                for _ in range(rng.randint(2, 5)):
                    t.set_at((rng.randrange(CELL), rng.randrange(CELL)),
                             pal["dark"] if rng.random() < 0.6 else pal["light"])
                if rng.random() < 0.15:
                    x, y = rng.randrange(1, 6), rng.randrange(1, 7)
                    t.set_at((x, y), (170, 150, 120)); t.set_at((x + 1, y), (170, 150, 120))
                if rng.random() < 0.05:
                    x, y = rng.randrange(2, 6), rng.randrange(3, 6)
                    for dy in range(3):
                        t.set_at((x, y - dy), (60, 140, 70))
                    t.set_at((x - 1, y - 1), (60, 140, 70)); t.set_at((x + 1, y - 2), (60, 140, 70))
            elif zone == "mountain":
                for _ in range(rng.randint(2, 4)):
                    t.set_at((rng.randrange(CELL), rng.randrange(CELL)), pal["dark"])
                if rng.random() < 0.4:
                    x, y = rng.randrange(2, 6), rng.randrange(3, 7)
                    t.set_at((x, y - 2), pal["light"])
                    for dx in (-1, 0, 1):
                        t.set_at((x + dx, y - 1), pal["light"] if dx <= 0 else pal["dark"])
                    for dx in (-2, -1, 0, 1, 2):
                        if 0 <= x + dx < CELL:
                            t.set_at((x + dx, y), pal["dark"])
                if rng.random() < 0.08:
                    t.set_at((rng.randrange(CELL), rng.randrange(CELL)), (240, 240, 250))
            else:  # river
                offset = 0 if frame == 0 else 2
                for row in (1, 5):
                    for x in range(CELL):
                        if (x + offset + row) % 4 in (0, 1):
                            t.set_at((x, row), pal["light"])
                for row in (3, 7):
                    for x in range(CELL):
                        if (x + offset + row) % 4 == 2:
                            t.set_at((x, row), pal["dark"])
            tiles.append(t)
        return tiles

    def _build_terrain(self, world, frame):
        pg = self.pg
        rng = random.Random(20240607)
        tiles = {z: self._make_tile_variants(z, frame, random.Random(sum(ord(c) for c in z)))
                 for z in TERRAIN_PALETTE}
        n = self.grid
        surf = pg.Surface((self.view, self.view))
        for x in range(n):            # x=行 (画面のy方向)
            for y in range(n):        # y=列 (画面のx方向)
                zone = world.get_zone(x, y)
                surf.blit(tiles[zone][rng.randrange(6)], (y * CELL, x * CELL))
                for dx, dy, side in ((-1, 0, "top"), (1, 0, "bottom"), (0, -1, "left"), (0, 1, "right")):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < n and 0 <= ny < n):
                        continue
                    nz = world.get_zone(nx, ny)
                    if nz == zone:
                        continue
                    ncolor = TERRAIN_PALETTE[nz]["base"]
                    for depth in (0, 1):
                        prob = 0.55 if depth == 0 else 0.2
                        for i in range(CELL):
                            if rng.random() < prob:
                                if side == "top":
                                    pos = (y * CELL + i, x * CELL + depth)
                                elif side == "bottom":
                                    pos = (y * CELL + i, x * CELL + CELL - 1 - depth)
                                elif side == "left":
                                    pos = (y * CELL + depth, x * CELL + i)
                                else:
                                    pos = (y * CELL + CELL - 1 - depth, x * CELL + i)
                                surf.set_at(pos, ncolor)
        return surf

    def _build_labels(self, world):
        """俯瞰のときだけ重ねるゾーン名ラベル"""
        if self.label_font is None:
            return None
        pg = self.pg
        overlay = pg.Surface((self.view, self.view), pg.SRCALPHA)
        n = self.grid
        band = self.view / 5
        band_cells = n // 5
        for rb in range(5):
            for cb in range(5):
                sx = min(rb * band_cells + band_cells // 2, n - 1)
                sy = min(cb * band_cells + band_cells // 2, n - 1)
                label = self.label_font.render(ZONE_NAMES_JA[world.get_zone(sx, sy)], True, (255, 255, 255))
                label.set_alpha(90)
                overlay.blit(label, (int((cb + 0.5) * band - label.get_width() / 2),
                                     int((rb + 0.5) * band - label.get_height() / 2)))
        return overlay

    def _draw_terrain(self, screen, ticks):
        pg = self.pg
        base = self.season_terrain.surface(self._terrain_key, (ticks // 600) % 2, ticks)    # 川は0.6秒ごとに波が切り替わる
        z = self.zoom
        if z == CELL:
            screen.blit(base, (0, 0))
            if self._labels is not None:
                screen.blit(self._labels, (0, 0))
            return
        s = z // CELL
        bx, rem_x = divmod(self.off_x, s)
        by, rem_y = divmod(self.off_y, s)
        w = min(self.grid * CELL - bx, -(-(self.view + rem_x) // s))
        h = min(self.grid * CELL - by, -(-(self.view + rem_y) // s))
        sub = base.subsurface((bx, by, w, h))
        screen.blit(pg.transform.scale(sub, (w * s, h * s)), (-rem_x, -rem_y))
        if self.show_season_fx:     # 春の川の花びら (ズームしたときだけ見える)
            self.season_terrain.draw_river(screen, z, self.off_x, self.off_y, ticks, self._terrain_key[0])

    # =================================================
    # スプライト (遺伝子 → 見た目)
    # =================================================
    def _get_sprite(self, org_type, genes, frame, flip, scale):
        cb = min(COLD_BUCKETS - 1, int(genes["cold_resistance"] * COLD_BUCKETS))
        key = (org_type, frame, flip, scale, cb,
               _lvl(genes["cold_resistance"]), _lvl(genes["metabolism"]),
               _lvl(genes["mountain_tolerance"]), _lvl(genes["river_tolerance"]),
               _lvl(genes["speed"], 0.4, 0.6))
        sprite = self._sprite_cache.get(key)
        if sprite is not None:
            return sprite
        pg = self.pg
        pixels = compose_pixels(org_type, frame, genes)
        sprite = pg.Surface((SPRITE, SPRITE), pg.SRCALPHA)
        for yy, row in enumerate(pixels):
            for xx, c in enumerate(row):
                if c is not None:
                    sprite.set_at((xx, yy), c + (255,))
        if flip:
            sprite = pg.transform.flip(sprite, True, False)
        if scale != 1:
            sprite = pg.transform.scale(sprite, (SPRITE * scale, SPRITE * scale))
        self._sprite_cache[key] = sprite
        return sprite

    def portrait(self, org, px=64):
        """個体の詳細パネル用の大きな肖像"""
        return self._get_sprite(org.org_type, org.genes, 0, False, max(1, px // SPRITE))

    def icon(self, kind, px=16):
        """凡例用アイコン。kind = 'herbivore' / 'carnivore' / 'food'"""
        pg = self.pg
        if kind == "food":
            return pg.transform.scale(self._berry_base, (px, px))
        genes = {"cold_resistance": 0.5, "metabolism": 0.5, "mountain_tolerance": 0.8,
                 "river_tolerance": 0.0, "speed": 0.5}
        sprite = self._get_sprite(kind, genes, 0, False, 1)
        return pg.transform.scale(sprite, (px, px)) if px != SPRITE else sprite

    def _berry(self, s):
        b = self._berry_cache.get(s)
        if b is None:
            size = (CELL * s if s != 1 else self._berry_base.get_width()) - 1    # 木の実は従来より1px小さく描く
            b = self.pg.transform.scale(self._berry_base, (size, size))
            self._berry_cache[s] = b
        return b

    # =================================================
    # エフェクト (誕生=ハート / 死亡=けむり)  座標は俯瞰基準のpx
    # =================================================
    def _update_effects(self, world):
        if self._world_ref is not world:      # 1世代ごとモードの←→でworldが入れ替わったとき
            self._world_ref = world
            self._prev = {}
            self._effects = []
        current = {id(o): o for o in world.organisms}
        if self._prev:
            births = [o for i, o in current.items() if i not in self._prev]
            deaths = [v for i, v in self._prev.items() if i not in current]
            for o in births[:30]:
                self._effects.append({"kind": "heart", "x": o.y * CELL + 4, "y": o.x * CELL, "life": 24})
            for (_, col, row) in deaths[:30]:
                self._effects.append({"kind": "puff", "x": col * CELL + 4, "y": row * CELL, "life": 18})
        self._prev = {i: (o, o.y, o.x) for i, o in current.items()}
        self._effects = self._effects[-150:]

    def _draw_effects(self, screen):
        if self.zoom == CELL:     # 俯瞰では出さない (点が小さすぎて邪魔になる)
            self._effects = [e for e in self._effects if e["life"] > 1]
            for e in self._effects:
                e["life"] -= 1
            return
        pg = self.pg
        s = self.zoom // CELL
        alive = []
        for e in self._effects:
            e["life"] -= 1
            if e["life"] <= 0:
                continue
            alive.append(e)
            ox = e["x"] * s - self.off_x
            oy = e["y"] * s - self.off_y
            if not (-40 < ox < self.view + 40 and -40 < oy < self.view + 40):
                continue
            if e["kind"] == "heart":
                rise = (24 - e["life"]) // 3
                x, y = ox - 2 * s, oy - (4 + rise) * s
                for dx, dy in ((0, 0), (1, 0), (3, 0), (4, 0), (0, 1), (1, 1), (2, 1), (3, 1), (4, 1),
                               (1, 2), (2, 2), (3, 2), (2, 3)):
                    screen.fill((255, 80, 120), (x + dx * s, y + dy * s, s, s))
            else:
                spread = (18 - e["life"]) // 4 + 1
                gray = max(80, 200 - (18 - e["life"]) * 6)
                for dx, dy in ((-spread, -spread), (spread, -spread), (0, -spread - 1), (-spread, 0), (spread, 0)):
                    pg.draw.rect(screen, (gray, gray, gray), (ox + dx * s, oy + (4 + dy) * s, 2 * s, 2 * s))
        self._effects = alive

    # =================================================
    # 気温の演出 (色調 + 寒いときの雪)
    # =================================================
    def _build_tint(self):
        pg = self.pg
        temp = config.TEMPERATURE
        cold = max(0.0, min(1.0, (15.0 - temp) / 15.0))
        hot = max(0.0, min(1.0, (temp - 25.0) / 15.0))
        surf = None
        if cold > 0:
            surf = pg.Surface((self.view, self.view), pg.SRCALPHA)
            surf.fill((120, 160, 255, int(70 * cold)))
        elif hot > 0:
            surf = pg.Surface((self.view, self.view), pg.SRCALPHA)
            surf.fill((255, 110, 50, int(60 * hot)))
        self._tint_surface = surf
        self._tint_temp = temp

    def _draw_weather(self, screen, world):
        if self._tint_temp != config.TEMPERATURE:
            self._build_tint()
        if self._tint_surface is not None:
            screen.blit(self._tint_surface, (0, 0))
        # 季節の演出 (春:桜 / 夏:光の筋 / 秋:モミジ / 冬:雪) と、右下の季節アイコン
        season = season_of(world.generation)
        if self.show_season_fx:
            self.season_fx.draw(screen, season)
        self.season_fx.draw_badge(screen, season, config.TEMPERATURE, year_of(world.generation), world.generation)

    # =================================================
    # ミニマップ (ズーム中だけ表示)
    # =================================================
    def _draw_minimap(self, screen, world):
        pg = self.pg
        r = self.mm_rect
        screen.blit(self.season_terrain.minimap(self._terrain_key, self.mm_size), r.topleft)
        m = self.mm_scale
        carns = []
        for o in world.organisms:
            if o.org_type == "herbivore":
                screen.fill(DOT_HERB, (r.left + o.y * m, r.top + o.x * m, m, m))
            else:
                carns.append(o)
        for o in carns:        # 肉食は最後に描いて埋もれないようにする
            screen.fill(DOT_CARN, (r.left + o.y * m, r.top + o.x * m, m, m))
        vw = self.view / self.zoom * m
        pg.draw.rect(screen, (255, 255, 255),
                     (r.left + self.off_x / self.zoom * m, r.top + self.off_y / self.zoom * m, vw, vw), 1)
        pg.draw.rect(screen, (230, 230, 230), r, 2)

    # =================================================
    # メイン描画
    # =================================================
    def draw(self, screen, world, selected_org=None):
        pg = self.pg
        ticks = pg.time.get_ticks()
        z = self.zoom
        n = self.grid
        view = self.view

        season = season_of(world.generation)
        self._terrain_key = (season, season_stage(world.generation) if season in ("summer", "autumn", "winter") else 0)
        self._draw_terrain(screen, ticks)

        # 画面に映るマスの範囲
        c0 = max(0, self.off_x // z)
        c1 = min(n - 1, (self.off_x + view - 1) // z)
        r0 = max(0, self.off_y // z)
        r1 = min(n - 1, (self.off_y + view - 1) // z)

        # 食物 (画面内だけ)。最小ズーム(俯瞰)のときは描かない
        if self.show_food and z != ZOOM_LEVELS[0]:
            berry = self._berry(z // CELL)
            for (fx, fy) in np.argwhere(world.food_grid[r0:r1 + 1, c0:c1 + 1]):
                screen.blit(berry, ((c0 + int(fy)) * z - self.off_x, (r0 + int(fx)) * z - self.off_y))

        # 個体 (画面内だけ)
        visible = [o for o in world.organisms if r0 <= o.x <= r1 and c0 <= o.y <= c1]

        if z == CELL:
            # --- 俯瞰: 種類別の色の点 (肉食を後から描いて埋もれないようにする) ---
            herbs = [o for o in visible if o.org_type == "herbivore"]
            carns = [o for o in visible if o.org_type != "herbivore"]
            for o in herbs:
                sx, sy = o.y * z - self.off_x, o.x * z - self.off_y
                screen.fill(DOT_HERB, (sx, sy, 3, 3))
            for o in carns:
                sx, sy = o.y * z - self.off_x, o.x * z - self.off_y
                screen.fill(DOT_CARN, (sx, sy, 4, 4))
        else:
            # --- 標準/接近: 遺伝子つきのドット絵 (手前の行ほど後から描く) ---
            k = z // SPRITE
            walk_frame = (ticks // 220) % 2
            for o in sorted(visible, key=lambda o: o.x):
                oid = id(o)
                prev = self._prev.get(oid)
                facing = self._facing.get(oid, 1)
                moved = False
                if prev is not None:
                    if o.y > prev[1]:
                        facing, moved = 1, True
                    elif o.y < prev[1]:
                        facing, moved = -1, True
                    elif o.x != prev[2]:
                        moved = True
                self._facing[oid], self._moved[oid] = facing, moved
                frame = (walk_frame + oid // 16) % 2 if moved else 0
                sprite = self._get_sprite(o.org_type, o.genes, frame, facing < 0, k)
                screen.blit(sprite, (o.y * z - self.off_x, o.x * z - self.off_y))

        self._update_effects(world)
        self._draw_effects(screen)
        self._draw_weather(screen, world)

        # 選択中の個体: 点滅する黄色の枠
        if (selected_org is not None and selected_org.alive and selected_org in world.organisms
                and (ticks // 300) % 2 == 0):
            cx = selected_org.y * z + z // 2 - self.off_x
            cy = selected_org.x * z + z // 2 - self.off_y
            half = max(8, z // 2 + 2)
            pg.draw.rect(screen, (255, 235, 59), (cx - half, cy - half, half * 2, half * 2), max(1, z // 16))

        if z != CELL:
            self._draw_minimap(screen, world)

        pg.draw.rect(screen, (60, 60, 60), (0, 0, view, view), 1)
