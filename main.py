# =============================================
# main.py — 可視化・メイン実行ファイル
# python main.py で実行する
#
# リアルタイム可視化はpygameで描画する (headlessモードはmatplotlibのまま)
# =============================================

import copy
import random

import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib
import config
from world import World
from pixel_art import PixelRenderer, CELL, ZOOM_LEVELS
from season_effects import season_label
import os


# =============================================
# pygame表示まわりの定数
# =============================================
GRID_PANEL_SIZE  = config.GRID_SIZE * CELL   # 左側 グリッド描画パネルの一辺(px) 8px x 80マス = 640
INFO_PANEL_WIDTH = 400   # 右側 情報パネルの幅(px)
WINDOW_HEIGHT    = GRID_PANEL_SIZE
WINDOW_WIDTH     = GRID_PANEL_SIZE + INFO_PANEL_WIDTH

BG_COLOR   = (13, 17, 23)
PANEL_BG   = (22, 27, 34)
TEXT_COLOR = (224, 224, 224)

TERRAIN_COLORS = {
    "grassland": (0x7e, 0xc8, 0x50),
    "desert":    (0xe8, 0xc9, 0x7a),
    "mountain":  (0x8b, 0x5e, 0x3c),
    "river":     (0x4a, 0x9e, 0xff),
    "sea":       (0x14, 0x3c, 0x8c),
}

# 地形のノイズ・波紋テクスチャに使う色
NOISE_COLORS = {
    "grassland": (0x5a, 0xa8, 0x38),
    "desert":    (0xf5, 0xe0, 0xa8),
    "mountain":  (0x5c, 0x3c, 0x24),
    "river":     (0x8c, 0xc8, 0xff),
}

HERB_LIGHT, HERB_DARK = (144, 202, 249), (13, 71, 161)
CARN_LIGHT, CARN_DARK = (239, 154, 154), (183, 28, 28)

TRAIT_FIELDS = [
    ("耐寒性", "cold_resistance"),
    ("速度",   "speed"),
    ("代謝",   "metabolism"),
    ("山耐性", "mountain_tolerance"),
    ("川耐性", "river_tolerance"),
]

ZONE_NAMES_JA = {"grassland": "草原", "desert": "砂漠", "mountain": "山", "river": "川", "sea": "海"}

# 速度ボタン (低速/中速/高速): (内部名, 表示名, 1秒あたりのステップ数)
SPEED_LEVELS = [("low", "低速", 5.0), ("medium", "中速", 10.0), ("high", "高速", 15.0)]
SPEED_SPS = {key: sps for key, _, sps in SPEED_LEVELS}
DEFAULT_SPEED_LEVEL = "medium"
MAX_STEPS_PER_FRAME = 25   # 1フレームで進めるステップ数の上限 (処理落ち後にまとめて進みすぎないため)


def _lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


# --------------------------------------------------
# ゾーン境界を数マス分グラデーションでなじませた色を求める
# --------------------------------------------------
def _blended_zone_color(world, x, y, blend_radius=3):
    zone_here = world.get_zone(x, y)
    result = list(TERRAIN_COLORS[zone_here])
    grid = config.GRID_SIZE
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        for d in range(1, blend_radius + 1):
            nx, ny = x + dx * d, y + dy * d
            if not (0 <= nx < grid and 0 <= ny < grid):
                break
            nz = world.get_zone(nx, ny)
            if nz != zone_here:
                weight = (blend_radius - d + 1) / (blend_radius + 1) * 0.5
                ncolor = TERRAIN_COLORS[nz]
                result = [result[i] + (ncolor[i] - result[i]) * weight for i in range(3)]
                break
    return tuple(int(round(c)) for c in result)


# --------------------------------------------------
# 地形の背景サーフェスを作る (毎フレーム作り直さず1回だけ生成する)
# ゾーンの色分け+境界のグラデーション+ノイズ/波紋テクスチャに加えて、
# ゾーン境界の薄い線と地形名ラベルも焼き込む
# --------------------------------------------------
def _build_terrain_surface(pygame, world, label_font):
    surface = pygame.Surface((GRID_PANEL_SIZE, GRID_PANEL_SIZE))
    cell = GRID_PANEL_SIZE / config.GRID_SIZE
    rng = random.Random(20240607)  # シミュレーション本体のnp.randomとは独立させる

    for x in range(config.GRID_SIZE):
        for y in range(config.GRID_SIZE):
            zone = world.get_zone(x, y)
            color = _blended_zone_color(world, x, y)
            rect = (int(y * cell), int(x * cell), int(cell) + 1, int(cell) + 1)
            surface.fill(color, rect)

            noise_color = NOISE_COLORS[zone]
            if zone == "river":
                wave_y = int(x * cell + cell * rng.uniform(0.3, 0.7))
                wave_x0 = int(y * cell + cell * 0.15)
                wave_x1 = int(y * cell + cell * 0.85)
                pygame.draw.line(surface, noise_color, (wave_x0, wave_y), (wave_x1, wave_y), 1)
            else:
                margin = 1 if cell > 2 else cell / 2
                for _ in range(rng.randint(1, 2)):
                    px = int(y * cell + rng.uniform(margin, cell - margin))
                    py = int(x * cell + rng.uniform(margin, cell - margin))
                    surface.set_at((px, py), noise_color)

    overlay = pygame.Surface((GRID_PANEL_SIZE, GRID_PANEL_SIZE), pygame.SRCALPHA)
    band = GRID_PANEL_SIZE / 5
    band_cells = config.GRID_SIZE // 5
    line_color = (255, 255, 255, 60)
    for i in range(1, 5):
        pos = int(i * band)
        pygame.draw.line(overlay, line_color, (pos, 0), (pos, GRID_PANEL_SIZE), 1)
        pygame.draw.line(overlay, line_color, (0, pos), (GRID_PANEL_SIZE, pos), 1)

    for rb in range(5):
        for cb in range(5):
            sample_x = min(rb * band_cells + band_cells // 2, config.GRID_SIZE - 1)
            sample_y = min(cb * band_cells + band_cells // 2, config.GRID_SIZE - 1)
            zone = world.get_zone(sample_x, sample_y)
            label = label_font.render(ZONE_NAMES_JA[zone], True, (255, 255, 255))
            label.set_alpha(110)
            cx = int((cb + 0.5) * band - label.get_width() / 2)
            cy = int((rb + 0.5) * band - label.get_height() / 2)
            overlay.blit(label, (cx, cy))

    surface.blit(overlay, (0, 0))
    return surface


# --------------------------------------------------
# クリック座標(px)に一番近い個体を探す (一定距離より遠ければNone)
# --------------------------------------------------
def _find_nearest_organism(world, mx, my, max_dist_px=16):
    cell = GRID_PANEL_SIZE / config.GRID_SIZE
    best = None
    best_d2 = max_dist_px * max_dist_px
    for o in world.organisms:
        px = o.y * cell + cell / 2
        py = o.x * cell + cell / 2
        d2 = (px - mx) ** 2 + (py - my) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best = o
    return best


# --------------------------------------------------
# 左側: グリッド描画 (地形 + 食物 + 個体)
# --------------------------------------------------
def _draw_grid(screen, pygame, world, terrain_surface, selected_org=None):
    screen.blit(terrain_surface, (0, 0))
    cell = GRID_PANEL_SIZE / config.GRID_SIZE

    # 食物: 小さな緑の点
    for (fx, fy) in np.argwhere(world.food_grid):
        px = int(fy * cell + cell / 2)
        py = int(fx * cell + cell / 2)
        pygame.draw.circle(screen, (46, 204, 64), (px, py), 1)

    for o in world.organisms:
        px = int(o.y * cell + cell / 2)
        py = int(o.x * cell + cell / 2)
        if o.org_type == "herbivore":
            color = _lerp_color(HERB_LIGHT, HERB_DARK, o.genes["cold_resistance"])
            pygame.draw.circle(screen, color, (px, py), 3)
        else:
            color = _lerp_color(CARN_LIGHT, CARN_DARK, o.genes["cold_resistance"])
            s = 4
            points = [(px, py - s), (px - s, py + s), (px + s, py + s)]
            pygame.draw.polygon(screen, color, points)

    if selected_org is not None and selected_org.alive and selected_org in world.organisms:
        px = int(selected_org.y * cell + cell / 2)
        py = int(selected_org.x * cell + cell / 2)
        pygame.draw.circle(screen, (255, 255, 0), (px, py), 8, 2)

    pygame.draw.rect(screen, (60, 60, 60), (0, 0, GRID_PANEL_SIZE, GRID_PANEL_SIZE), 1)


# --------------------------------------------------
# 値0〜1のバーを1本描画する
# --------------------------------------------------
def _draw_bar(screen, pygame, font, x, y, width, height, value, label, color):
    label_surf = font.render(f"{label}: {value:.3f}", True, TEXT_COLOR)
    screen.blit(label_surf, (x, y))
    bar_y = y + label_surf.get_height() + 1
    pygame.draw.rect(screen, (50, 55, 62), (x, bar_y, width, height))
    fill_w = int(width * max(0.0, min(1.0, value)))
    if fill_w > 0:
        pygame.draw.rect(screen, color, (x, bar_y, fill_w, height))
    pygame.draw.rect(screen, (90, 95, 100), (x, bar_y, width, height), 1)
    return bar_y + height


# --------------------------------------------------
# 右側: 個体アイコンの凡例 (種類の色分けと食物の説明)
# --------------------------------------------------
def _draw_legend(screen, pygame, small_font, x, y, renderer):
    rows = [
        ("herbivore", "草食動物 (俯瞰では白い点)"),
        ("carnivore", "肉食動物 (俯瞰では赤い点)"),
        ("food",      "木の実 = 食物"),
    ]
    row_h = 18
    for kind, text in rows:
        screen.blit(renderer.icon(kind, 16), (x, y))
        label = small_font.render(text, True, TEXT_COLOR)
        screen.blit(label, (x + 22, y + (16 - label.get_height()) // 2))
        y += row_h
    y += 2
    for text in ("見た目 → 遺伝子 (ズームすると見える)",
                 "角・太い足=山耐性   水色の足・ひれ=川耐性",
                 "足の長さ=速度   体の大きさ=代謝",
                 "白くてもこもこ=耐寒性"):
        label = small_font.render(text, True, (150, 155, 160))
        screen.blit(label, (x, y))
        y += label.get_height() + 1
    return y + 4


# --------------------------------------------------
# 左上: FPS・ズーム倍率・操作ヒント (重くなったときの切り分け用にFPSを常時表示)
# --------------------------------------------------
def _draw_view_hud(screen, pygame, small_font, renderer, clock, follow, explain_open=False):
    text = (f"FPS {clock.get_fps():.0f} | x{renderer.zoom // CELL} | "
            f"ホイール:ズーム ドラッグ:移動 F:追跡{'中' if follow else ''} | "
            f"V:食料{'表示' if renderer.show_food else '非表示'} | "
            f"E:エフェクト{'ON' if renderer.show_season_fx else 'OFF'} | "
            f"N:解説{'ON' if explain_open else 'OFF'}")
    surf = small_font.render(text, True, (255, 255, 255))
    shade = pygame.Surface((surf.get_width() + 8, surf.get_height() + 4), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 150))
    screen.blit(shade, (6, 6))
    screen.blit(surf, (10, 8))


# --------------------------------------------------
# 右側: 速度ボタン (低速/中速/高速の3つを横並び。選択中は青く強調)
# 戻り値: (次の描画y座標, {速度名: クリック判定用Rect})
# --------------------------------------------------
def _draw_speed_buttons(screen, pygame, small_font, x, y, width, speed_level):
    gap = 8
    btn_w = (width - gap * (len(SPEED_LEVELS) - 1)) // len(SPEED_LEVELS)
    btn_h = small_font.get_height() + 6
    rects = {}
    for i, (key, label, _) in enumerate(SPEED_LEVELS):
        rect = pygame.Rect(x + i * (btn_w + gap), y, btn_w, btn_h)
        rects[key] = rect
        selected = key == speed_level
        pygame.draw.rect(screen, (33, 150, 243) if selected else (50, 55, 62), rect, border_radius=4)
        pygame.draw.rect(screen, (100, 181, 246) if selected else (90, 95, 100), rect, 1, border_radius=4)
        text = small_font.render(label, True, (255, 255, 255) if selected else (170, 170, 170))
        screen.blit(text, text.get_rect(center=rect.center))

    y += btn_h + 3
    speed_info = small_font.render(f"({SPEED_SPS[speed_level]:.1f} ステップ/秒)", True, (140, 140, 140))
    screen.blit(speed_info, (x, y))
    y += speed_info.get_height() + 4
    return y, rects


# --------------------------------------------------
# 右側: 平均形質パネル (通常表示)
# --------------------------------------------------
def _draw_average_panel(screen, pygame, font, big_font, small_font, herbs, carns, x, y, bar_w):
    def avg(orgs, key):
        return float(np.mean([o.genes[key] for o in orgs])) if orgs else 0.0

    bar_h = 6

    section = font.render("草食動物の平均形質", True, (100, 181, 246))
    screen.blit(section, (x, y))
    y += section.get_height() + 2
    for label, key in TRAIT_FIELDS:
        y = _draw_bar(screen, pygame, small_font, x, y, bar_w, bar_h, avg(herbs, key), label, (66, 165, 245)) + 1

    y += 2
    section = font.render("肉食動物の平均形質", True, (239, 83, 80))
    screen.blit(section, (x, y))
    y += section.get_height() + 2
    for label, key in TRAIT_FIELDS:
        y = _draw_bar(screen, pygame, small_font, x, y, bar_w, bar_h, avg(carns, key), label, (239, 83, 80)) + 1


# --------------------------------------------------
# 右側: 選択した個体の詳細パネル
# --------------------------------------------------
def _draw_selected_panel(screen, pygame, font, big_font, small_font, world, x, y, bar_w, org, renderer):
    type_label = "草食動物" if org.org_type == "herbivore" else "肉食動物"
    color = (100, 181, 246) if org.org_type == "herbivore" else (239, 83, 80)

    title = big_font.render(f"個体の詳細: {type_label}", True, color)
    screen.blit(title, (x, y))
    y += title.get_height() + 6
    screen.blit(renderer.portrait(org, 64), (x + bar_w - 64, y))   # 実際の見た目の肖像

    zone = world.get_zone(org.x, org.y)
    info_lines = [
        f"エネルギー: {org.energy:.1f} / {org.max_energy:.1f}",
        f"年齢: {org.age}",
        f"現在のゾーン: {ZONE_NAMES_JA[zone]}",
        f"座標: ({org.x}, {org.y})",
    ]
    for text in info_lines:
        surf = font.render(text, True, TEXT_COLOR)
        screen.blit(surf, (x, y))
        y += surf.get_height() + 3

    y += 4
    bar_h = 8
    for label, key in TRAIT_FIELDS:
        y = _draw_bar(screen, pygame, small_font, x, y, bar_w, bar_h, org.genes[key], label, color) + 2

    y += 4
    hint = small_font.render("N:観察ナビ / Tab:個体詳細 / 空白クリック:平均表示", True, (140, 140, 140))
    screen.blit(hint, (x, y))


# --------------------------------------------------
# 右側: 世代・個体数・気温・モード・速度スライダー・凡例・形質パネル全体
# 戻り値: 速度ボタンのクリック判定用Rectの辞書 (画面座標)
# --------------------------------------------------
def _draw_info_panel(screen, pygame, font, big_font, small_font, world, paused, mode, speed_level, selected_org, renderer,
                     explain_rect=None):
    x0 = GRID_PANEL_SIZE
    pygame.draw.rect(screen, PANEL_BG, (x0, 0, INFO_PANEL_WIDTH, WINDOW_HEIGHT))

    herbs = [o for o in world.organisms if o.org_type == "herbivore"]
    carns = [o for o in world.organisms if o.org_type == "carnivore"]

    margin = 14
    x = x0 + margin
    y = 6
    bar_w = INFO_PANEL_WIDTH - margin * 2

    mode_text = f"モード: {'1世代ごと' if mode == 'per_gen' else '通常'} (Mで切替)"
    if paused:
        mode_text = "[一時停止中] " + mode_text

    if mode == "per_gen":
        controls_text = "→:次の世代   ←:前の世代   Space:一時停止   M:モード切替   Esc:終了"
    else:
        controls_text = "Space:一時停止   M:モード切替   Esc:終了"

    header_lines = [
        (season_label(world.generation), big_font, (255, 255, 255)),
        (f"草食動物: {len(herbs)} 匹", font, (100, 181, 246)),
        (f"肉食動物: {len(carns)} 匹", font, (239, 83, 80)),
        (f"気温: {config.TEMPERATURE:.1f}°C", font, (255, 213, 79)),
        (mode_text, small_font, (255, 235, 59) if paused else (180, 180, 180)),
        (controls_text, small_font, (140, 140, 140)),
    ]

    if explain_rect is not None:      # 解説パネルを開くボタン (解説パネルの「閉じる」ボタンと同じ位置・大きさ)
        pygame.draw.rect(screen, (50, 55, 62), explain_rect, border_radius=4)
        pygame.draw.rect(screen, (90, 95, 100), explain_rect, 1, border_radius=4)
        label = small_font.render("解説", True, (225, 225, 225))
        screen.blit(label, label.get_rect(center=explain_rect.center))

    for text, f, color in header_lines:
        surf = f.render(text, True, color)
        screen.blit(surf, (x, y))
        y += surf.get_height() + 2
    y += 3

    y, speed_button_rects = _draw_speed_buttons(screen, pygame, small_font, x, y, bar_w, speed_level)

    y = _draw_legend(screen, pygame, small_font, x, y, renderer)

    if selected_org is not None and selected_org.alive and selected_org in world.organisms:
        _draw_selected_panel(screen, pygame, font, big_font, small_font, world, x, y, bar_w, selected_org, renderer)
    else:
        _draw_average_panel(screen, pygame, font, big_font, small_font, herbs, carns, x, y, bar_w)

    return speed_button_rects


# --------------------------------------------------
# 日本語対応フォントを探す
# --------------------------------------------------
def _load_fonts(pygame):
    # fonts/DotGothic16-Regular.ttf を置くとドット絵フォントになる (無ければ従来のフォント)
    dot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "DotGothic16-Regular.ttf")
    if os.path.exists(dot):
        return pygame.font.Font(dot, 14), pygame.font.Font(dot, 20), pygame.font.Font(dot, 12)
    path = pygame.font.match_font("meiryo,msgothic,yugothic,notosanscjkjp,arial")
    if path is None:
        path = pygame.font.get_default_font()
    return pygame.font.Font(path, 13), pygame.font.Font(path, 18), pygame.font.Font(path, 11)


# --------------------------------------------------
# 1ステップ進め、世代境界なら記録して世代を進める
# 戻り値: (step_in_gen, extinct, done)
# --------------------------------------------------
def _step_simulation(world, step_in_gen, extinct, done):
    world.step()
    step_in_gen += 1
    if len(world.organisms) == 0:
        extinct = True

    if step_in_gen >= config.MAX_STEPS_PER_GEN or extinct:
        world._record_data()
        step_in_gen = 0
        if extinct or world.generation >= config.MAX_GENERATIONS:
            done = True
        else:
            world.generation += 1

    return step_in_gen, extinct, done


# =============================================
# リアルタイム可視化モード (pygame)
# =============================================
def run_with_visualization(world):
    import pygame
    from navigator_panel import NavigatorPanel

    pygame.init()
    pygame.display.set_caption("生態系進化シミュレーション")
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    clock = pygame.time.Clock()
    font, big_font, small_font = _load_fonts(pygame)
    renderer = PixelRenderer(pygame, world, small_font)
    status_panel = NavigatorPanel((GRID_PANEL_SIZE, 0, INFO_PANEL_WIDTH, WINDOW_HEIGHT))

    world.generation += 1  # 1世代目を開始
    step_in_gen = 0
    paused = False
    running = True
    extinct = False        # 全種絶滅したか
    done = False            # ループを止めるべきか (絶滅 または 最大世代到達)
    mode = "normal"         # "normal" または "per_gen" (1世代ごとモード)
    speed_level = DEFAULT_SPEED_LEVEL   # "low" / "medium" / "high"
    drag_start = None       # 盤面ドラッグ(移動)の開始位置
    drag_last = None
    drag_moved = False
    follow = False          # 選択中の個体を追跡するか
    accumulator = 0.0
    selected_org = None
    speed_button_rects = {}

    # 世代の境界(その世代が始まる直前)の状態を世代番号ごとに保存しておく
    # (1世代ごとモードの←→で、同じ世代には常に同じ状態で戻れるようにするため)
    gen_snapshots = {world.generation: (copy.deepcopy(world), extinct, done)}

    while running:
        for event in pygame.event.get():
            if status_panel.handle_event(event, selected_org, world):
                continue
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    renderer.set_zoom(ZOOM_LEVELS[event.key - pygame.K_1])
                elif event.key == pygame.K_v:
                    renderer.show_food = not renderer.show_food
                elif event.key == pygame.K_e:
                    renderer.show_season_fx = not renderer.show_season_fx
                elif event.key == pygame.K_f:
                    follow = not follow and selected_org is not None
                elif event.key == pygame.K_m:
                    mode = "per_gen" if mode == "normal" else "normal"
                    if mode == "per_gen":
                        paused = True
                elif event.key == pygame.K_RIGHT and mode == "per_gen":
                    if not done:
                        target = world.generation + 1
                        if target in gen_snapshots:
                            w2, ex2, dn2 = gen_snapshots[target]
                            world = copy.deepcopy(w2)
                            extinct, done = ex2, dn2
                        else:
                            while True:
                                step_in_gen, extinct, done = _step_simulation(world, step_in_gen, extinct, done)
                                if step_in_gen == 0:
                                    break
                            if world.generation not in gen_snapshots:
                                gen_snapshots[world.generation] = (copy.deepcopy(world), extinct, done)
                        step_in_gen = 0
                        paused = True
                elif event.key == pygame.K_LEFT and mode == "per_gen":
                    target = world.generation - 1
                    if target >= 1 and target in gen_snapshots:
                        w2, ex2, dn2 = gen_snapshots[target]
                        world = copy.deepcopy(w2)
                        extinct, done = ex2, dn2
                        step_in_gen = 0
                        paused = True
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if mx < GRID_PANEL_SIZE:
                    hit = renderer.minimap_hit(mx, my)
                    if hit is not None:                      # ミニマップをクリック → その場所へ移動
                        renderer.center_on_cell(hit[0], hit[1])
                        follow = False
                    else:                                    # 盤面: クリックなら選択 / 動かしたら移動
                        drag_start, drag_last, drag_moved = (mx, my), (mx, my), False
                elif not status_panel.open and status_panel.close_rect.collidepoint(mx, my):
                    status_panel.open = True                 # 右パネル右上の「解説」ボタン → 解説パネルを開く
                else:                                        # 右パネル: 速度ボタン
                    for key, rect in speed_button_rects.items():
                        if rect.collidepoint(mx, my):
                            speed_level = key
            elif event.type == pygame.MOUSEMOTION:
                if drag_start is not None:
                    mx, my = event.pos
                    if abs(mx - drag_start[0]) + abs(my - drag_start[1]) >= 5:
                        drag_moved = True
                    if drag_moved:
                        renderer.pan(drag_last[0] - mx, drag_last[1] - my)
                        follow = False
                    drag_last = (mx, my)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if drag_start is not None and not drag_moved:
                    selected_org = renderer.find_org(world, drag_start[0], drag_start[1])
                    if selected_org is None:
                        follow = False
                drag_start = None
            elif event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                if mx < GRID_PANEL_SIZE and event.y != 0:
                    renderer.zoom_step(1 if event.y > 0 else -1, (mx, my))

        world.update_temperature()  # 世代に応じた季節の気温に更新 (←→で世代を戻した場合も追従)

        # WASDでカメラ移動 / 追跡モード中は選択個体を画面中央に保つ
        keys = pygame.key.get_pressed()
        pdx = (int(keys[pygame.K_d]) - int(keys[pygame.K_a])) * 10
        pdy = (int(keys[pygame.K_s]) - int(keys[pygame.K_w])) * 10
        if pdx or pdy:
            renderer.pan(pdx, pdy)
            follow = False
        if follow and selected_org is not None and selected_org.alive and selected_org in world.organisms:
            renderer.center_on_org(selected_org)

        if running and not paused and not done:
            accumulator += clock.get_time() / 1000.0
            sps = SPEED_SPS[speed_level]
            steps_to_run = min(int(accumulator * sps), MAX_STEPS_PER_FRAME)
            if steps_to_run > 0:
                accumulator -= steps_to_run / sps
                for _ in range(steps_to_run):
                    step_in_gen, extinct, done = _step_simulation(world, step_in_gen, extinct, done)
                    if step_in_gen == 0:
                        if world.generation not in gen_snapshots:
                            gen_snapshots[world.generation] = (copy.deepcopy(world), extinct, done)
                        if mode == "per_gen":
                            paused = True
                    if done or paused:
                        break

        screen.fill(BG_COLOR)
        renderer.draw(screen, world, selected_org)
        _draw_view_hud(screen, pygame, small_font, renderer, clock, follow, status_panel.open)
        speed_button_rects = _draw_info_panel(
            screen, pygame, font, big_font, small_font, world, paused, mode, speed_level, selected_org, renderer,
            explain_rect=status_panel.close_rect
        )

        if extinct:
            msg = big_font.render(">>> 全種絶滅 <<<", True, (255, 102, 102))
            rect = msg.get_rect(center=(GRID_PANEL_SIZE // 2, GRID_PANEL_SIZE // 2))
            pygame.draw.rect(screen, (0, 0, 0), rect.inflate(20, 16))
            screen.blit(msg, rect)
        elif done:
            msg = big_font.render(">>> シミュレーション完了 <<<", True, (102, 255, 153))
            rect = msg.get_rect(center=(GRID_PANEL_SIZE // 2, GRID_PANEL_SIZE // 2))
            pygame.draw.rect(screen, (0, 0, 0), rect.inflate(20, 16))
            screen.blit(msg, rect)

        status_panel.draw(screen, selected_org, world)
        pygame.display.flip()
        clock.tick(60)

        if done and running and mode == "normal":
            pygame.time.delay(1500)
            running = False

    status_panel.close()
    pygame.quit()
    save_result_graph(world)


# =============================================
# ヘッドレスモード (高速実行)
# =============================================
def run_headless(world):
    print(f"開始: 気温={config.TEMPERATURE}°C  突然変異率={config.MUTATION_RATE*100:.0f}%")
    print(f"{'世代':>5} | {'草食':>5} | {'肉食':>5} | {'草耐寒':>7} | {'肉耐寒':>7}")
    print("-" * 42)
    for _ in range(config.MAX_GENERATIONS):
        alive = world.run_generation()
        h = world.history
        print(
            f"{h['generation'][-1]:>5} | "
            f"{h['herbivore_count'][-1]:>5} | "
            f"{h['carnivore_count'][-1]:>5} | "
            f"{h['herb_cold_resistance'][-1]:>7.3f} | "
            f"{h['carn_cold_resistance'][-1]:>7.3f}"
        )
        if not alive:
            print(">>> 絶滅")
            break
    save_result_graph(world)


# =============================================
# 結果グラフの保存 (ポスター用)
# =============================================
def save_result_graph(world):
    h = world.history
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    fig.suptitle(
        f"実験結果  |  気温: {config.TEMPERATURE}°C  "
        f"突然変異率: {config.MUTATION_RATE*100:.0f}%",
        fontsize=13
    )

    # 個体数推移
    axes[0].plot(h["generation"], h["herbivore_count"],
                 color="#1976d2", linewidth=2, label="草食動物")
    axes[0].plot(h["generation"], h["carnivore_count"],
                 color="#d32f2f", linewidth=2, label="肉食動物")
    axes[0].set_title("個体数の推移")
    axes[0].set_xlabel("世代")
    axes[0].set_ylabel("個体数")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    # 草食動物の形質変化
    axes[1].plot(h["generation"], h["herb_cold_resistance"],
                 color="#0288d1", linewidth=2, label="耐寒性")
    axes[1].plot(h["generation"], h["herb_speed"],
                 color="#388e3c", linewidth=2, label="速度")
    axes[1].plot(h["generation"], h["herb_metabolism"],
                 color="#8e24aa", linewidth=2, label="代謝")
    axes[1].plot(h["generation"], h["herb_river_tolerance"],
                 color="#0097a7", linewidth=2, label="川耐性")
    axes[1].plot(h["generation"], h["herb_mountain_tolerance"],
                 color="#6d4c41", linewidth=2, label="山耐性")
    axes[1].set_ylim(0, 1)
    axes[1].set_title("草食動物の形質変化")
    axes[1].set_xlabel("世代")
    axes[1].set_ylabel("遺伝子の値 (0〜1)")
    axes[1].legend()
    axes[1].grid(alpha=0.3)

    # 肉食動物の形質変化
    axes[2].plot(h["generation"], h["carn_cold_resistance"],
                 color="#e53935", linewidth=2, label="耐寒性")
    axes[2].plot(h["generation"], h["carn_speed"],
                 color="#f57c00", linewidth=2, label="速度")
    axes[2].plot(h["generation"], h["carn_metabolism"],
                 color="#8e24aa", linewidth=2, label="代謝")
    axes[2].plot(h["generation"], h["carn_river_tolerance"],
                 color="#0097a7", linewidth=2, label="川耐性")
    axes[2].plot(h["generation"], h["carn_mountain_tolerance"],
                 color="#6d4c41", linewidth=2, label="山耐性")
    axes[2].set_ylim(0, 1)
    axes[2].set_title("肉食動物の形質変化")
    axes[2].set_xlabel("世代")
    axes[2].set_ylabel("遺伝子の値 (0〜1)")
    axes[2].legend()
    axes[2].grid(alpha=0.3)

    plt.tight_layout()
    filename = f"result_temp{int(config.TEMPERATURE)}.png"
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    print(f"結果グラフを保存しました: {filename}")


# =============================================
# エントリーポイント
# =============================================
if __name__ == "__main__":
    if config.VISUALIZE:
        from title_screen import show_title_screen
        if show_title_screen() == "god":
            run_with_visualization(World())
    else:
        run_headless(World())
