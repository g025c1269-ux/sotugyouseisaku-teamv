"""画面の構造にあたる色 (背景・面・枠線・文字・アクセントなど) をまとめた配色。

各画面は color("名前") で色を読む (描画のたびに読むので、set_theme で切り替えると全画面に反映される)。
意味を持つ色 (草食の青・肉食の赤・警告の紫・気温の黄色・MPの金色・クリア/失敗/エラーの色・コストの色・「使える」の緑) も、
テーマごとの値を持つ (明るいテーマでは、同じ色相のまま濃くして、面の上で読めるようにしてある)。
配色を足すには THEMES に辞書を足す ("dark" と同じキーをすべて持たせる)。既定は "meadow"。
選んだ配色は saves/ui_settings.json に保存し、起動時に load_settings で読む。

キーの意味:
  bg / dot / deco_*/logo_*   背景、背景の点と木の飾り、ロゴ
  text / muted               通常の文字、薄い文字
  accent / accent_bright     アクセント (選択中の枠など)、見出しなどの明るいアクセント
  surface / surface_edge     パネルや枠の面と枠線
  button / button_hover / button_edge   ボタンの面 (通常・選択中)、枠線
  disabled_*                 押せないものの面・枠線・文字
  card / card_text / card_idle / card_hover / image_*   カード類
  popup / input / focus_ring / dot_idle    ポップアップ、入力欄、キーボードの選択枠、選ばれていない点
  gp_*                       ゲーム画面の右パネル (game_panel.py) の面・枠・文字
  leaf_title / bubble_*      リーフのヒントの見出しの文字、吹き出しの面・枠・文字
  art_*                      ステージ選択やスキルカードで、絵がないときの代わりの絵の背景色と文字色
  tag_*                      解説のスキルカードの札 (場所を選ぶ / すぐ使う) の面と文字
  herb carn warn temp mp_text clear fail error cost_* ok_green ng_text など   意味のある色 (草食・肉食・警告・気温・MP・結果・コスト・状態)
"""
import json
import os
from pathlib import Path

THEMES = {
    # いまの配色 (変更前と同じ)
    "dark": {
        # 背景・飾り
        "bg": (8, 19, 16), "dot": (19, 38, 29), "deco_stem": (34, 69, 44), "deco_a": (25, 57, 36), "deco_b": (35, 73, 44),
        "logo_ring": (38, 73, 48), "logo_leaf": (123, 178, 99),
        # 文字・アクセント
        "text": (234, 244, 226), "muted": (153, 177, 155), "accent": (152, 197, 123), "accent_bright": (163, 204, 131),
        # 面・ボタン・カード
        "surface": (16, 36, 27), "surface_edge": (44, 76, 52), "button": (22, 49, 33), "button_hover": (51, 96, 56),
        "button_edge": (56, 86, 60), "disabled_fill": (16, 30, 23), "disabled_edge": (40, 58, 46),
        "disabled_text": (88, 105, 92), "card": (28, 62, 40), "card_text": (205, 222, 200), "card_idle": (24, 52, 36),
        "card_hover": (38, 78, 48), "image_bg": (14, 30, 22), "image_edge": (10, 24, 17), "popup": (8, 19, 16),
        "input": (9, 22, 17), "focus_ring": (255, 255, 255), "dot_idle": (120, 150, 125),
        # ゲーム右パネル
        "gp_bg": (22, 27, 34), "gp_button": (50, 55, 62), "gp_button_edge": (90, 95, 100), "gp_text_strong": (255, 255, 255),
        "gp_text": (225, 225, 225), "gp_card_text": (235, 235, 235), "gp_label": (200, 200, 200), "gp_soft": (190, 190, 190),
        "gp_dim": (170, 170, 170), "gp_faint": (150, 150, 150), "gp_info": (140, 140, 140), "gp_bar_bg": (45, 50, 58),
        "gp_card": (36, 52, 68), "gp_card_off": (18, 21, 25), "gp_card_edge": (100, 181, 246),
        "gp_card_edge_off": (50, 55, 60), "gp_card_text_off": (95, 100, 105), "gp_speed_on": (33, 150, 243),
        "gp_speed_on_edge": (100, 181, 246), "gp_speed_on_text": (255, 255, 255), "leaf_title": (173, 209, 138),
        "bubble_fill": (29, 57, 44), "bubble_edge": (53, 87, 66), "bubble_text": (231, 240, 226),
        # 意味のある色
        "herb": (100, 181, 246), "carn": (239, 83, 80), "warn": (225, 100, 255), "warn_pill_bg": (35, 20, 45),
        "warn_ink": (25, 15, 30), "temp": (255, 213, 79), "badge_ink": (20, 20, 20), "mp_text": (255, 235, 130),
        "mp_bar": (240, 190, 60), "clear": (163, 204, 131), "fail": (239, 83, 80), "error": (240, 140, 130),
        "cost_1": (140, 210, 130), "cost_2": (240, 205, 90), "cost_3": (238, 120, 105), "ok_green": (130, 220, 150),
        "ng_text": (110, 80, 80),
        # ステージ選択の、絵がないときの代わりの絵
        "art_1": (86, 140, 110), "art_2": (120, 110, 170), "art_3": (176, 120, 84), "art_4": (84, 130, 176), "art_5": (160, 100, 130),
        "art_6": (110, 150, 80), "art_text": (250, 250, 240),
        # 解説のスキルカードの札 (場所を選ぶ / すぐ使う)
        "tag_target": (52, 86, 128), "tag_instant": (108, 88, 48), "tag_text": (234, 244, 226),
    },
    # A 草原: 明るい黄緑〜淡い緑の背景、濃い緑の文字
    "meadow": {
        # 背景・飾り
        "bg": (222, 238, 184), "dot": (204, 224, 160), "deco_stem": (166, 198, 122), "deco_a": (186, 212, 144),
        "deco_b": (176, 206, 134), "logo_ring": (140, 184, 100), "logo_leaf": (76, 146, 52),
        # 文字・アクセント
        "text": (28, 66, 34), "muted": (78, 108, 68), "accent": (58, 130, 44), "accent_bright": (40, 108, 36),
        # 面・ボタン・カード
        "surface": (242, 250, 222), "surface_edge": (150, 188, 110), "button": (236, 246, 208),
        "button_hover": (186, 220, 140), "button_edge": (112, 156, 76), "disabled_fill": (226, 234, 206),
        "disabled_edge": (200, 212, 176), "disabled_text": (140, 156, 124), "card": (244, 251, 226), "card_text": (44, 82, 44),
        "card_idle": (224, 238, 192), "card_hover": (204, 228, 164), "image_bg": (236, 245, 214),
        "image_edge": (140, 176, 108), "popup": (250, 254, 238), "input": (252, 255, 244), "focus_ring": (28, 66, 34),
        "dot_idle": (130, 164, 100),
        # ゲーム右パネル
        "gp_bg": (236, 246, 212), "gp_button": (210, 228, 172), "gp_button_edge": (122, 158, 90),
        "gp_text_strong": (20, 52, 28), "gp_text": (34, 70, 38), "gp_card_text": (28, 62, 34), "gp_label": (52, 88, 52),
        "gp_soft": (72, 100, 64), "gp_dim": (78, 103, 69), "gp_faint": (94, 115, 85), "gp_info": (109, 109, 109),
        "gp_bar_bg": (200, 216, 168), "gp_card": (250, 254, 238), "gp_card_off": (220, 230, 200),
        "gp_card_edge": (66, 140, 60), "gp_card_edge_off": (186, 198, 164), "gp_card_text_off": (140, 154, 122),
        "gp_speed_on": (21, 101, 192), "gp_speed_on_edge": (13, 71, 161), "gp_speed_on_text": (255, 255, 255),
        "leaf_title": (52, 112, 44), "bubble_fill": (242, 250, 222), "bubble_edge": (150, 188, 110),
        "bubble_text": (28, 62, 34),
        # 意味のある色
        "herb": (51, 93, 126), "carn": (155, 54, 52), "warn": (160, 71, 181), "warn_pill_bg": (251, 236, 255),
        "warn_ink": (255, 255, 255), "temp": (127, 106, 39), "badge_ink": (255, 255, 255), "mp_text": (120, 110, 61),
        "mp_bar": (240, 190, 60), "clear": (88, 110, 70), "fail": (180, 63, 60), "error": (148, 86, 80),
        "cost_1": (63, 95, 59), "cost_2": (102, 87, 38), "cost_3": (136, 69, 60), "ok_green": (74, 126, 86),
        "ng_text": (110, 80, 80),
        # ステージ選択の、絵がないときの代わりの絵
        "art_1": (86, 140, 110), "art_2": (120, 110, 170), "art_3": (176, 120, 84), "art_4": (84, 130, 176), "art_5": (160, 100, 130),
        "art_6": (110, 150, 80), "art_text": (250, 250, 240),
        # 解説のスキルカードの札 (場所を選ぶ / すぐ使う)
        "tag_target": (52, 86, 128), "tag_instant": (108, 88, 48), "tag_text": (255, 255, 255),
    },
    # B 青空: 淡い空色の背景、白いカード、濃い青緑の文字
    "sky": {
        # 背景・飾り
        "bg": (210, 234, 250), "dot": (194, 220, 240), "deco_stem": (156, 194, 222), "deco_a": (178, 208, 232),
        "deco_b": (166, 200, 228), "logo_ring": (130, 178, 210), "logo_leaf": (52, 146, 168),
        # 文字・アクセント
        "text": (14, 62, 74), "muted": (66, 106, 120), "accent": (24, 126, 158), "accent_bright": (8, 98, 128),
        # 面・ボタン・カード
        "surface": (255, 255, 255), "surface_edge": (146, 188, 214), "button": (240, 248, 255),
        "button_hover": (184, 220, 242), "button_edge": (110, 166, 198), "disabled_fill": (232, 240, 246),
        "disabled_edge": (204, 218, 228), "disabled_text": (148, 166, 178), "card": (255, 255, 255), "card_text": (22, 68, 82),
        "card_idle": (232, 244, 252), "card_hover": (204, 230, 246), "image_bg": (242, 249, 254),
        "image_edge": (146, 188, 214), "popup": (255, 255, 255), "input": (255, 255, 255), "focus_ring": (14, 62, 74),
        "dot_idle": (122, 164, 190),
        # ゲーム右パネル
        "gp_bg": (228, 242, 252), "gp_button": (206, 228, 244), "gp_button_edge": (112, 164, 196),
        "gp_text_strong": (8, 50, 62), "gp_text": (20, 66, 80), "gp_card_text": (14, 58, 72), "gp_label": (40, 86, 102),
        "gp_soft": (64, 104, 118), "gp_dim": (71, 104, 116), "gp_faint": (84, 113, 123), "gp_info": (107, 107, 107),
        "gp_bar_bg": (196, 218, 234), "gp_card": (255, 255, 255), "gp_card_off": (222, 232, 240),
        "gp_card_edge": (30, 132, 164), "gp_card_edge_off": (184, 200, 212), "gp_card_text_off": (140, 156, 168),
        "gp_speed_on": (21, 101, 192), "gp_speed_on_edge": (13, 71, 161), "gp_speed_on_text": (255, 255, 255),
        "leaf_title": (20, 104, 130), "bubble_fill": (255, 255, 255), "bubble_edge": (146, 188, 214),
        "bubble_text": (14, 58, 72),
        # 意味のある色
        "herb": (53, 97, 131), "carn": (162, 56, 54), "warn": (157, 70, 178), "warn_pill_bg": (251, 236, 255),
        "warn_ink": (255, 255, 255), "temp": (127, 106, 39), "badge_ink": (255, 255, 255), "mp_text": (117, 108, 60),
        "mp_bar": (240, 190, 60), "clear": (86, 107, 69), "fail": (178, 62, 60), "error": (148, 86, 80),
        "cost_1": (67, 100, 62), "cost_2": (107, 92, 40), "cost_3": (144, 72, 63), "ok_green": (76, 128, 87),
        "ng_text": (110, 80, 80),
        # ステージ選択の、絵がないときの代わりの絵
        "art_1": (86, 140, 110), "art_2": (120, 110, 170), "art_3": (176, 120, 84), "art_4": (84, 130, 176), "art_5": (160, 100, 130),
        "art_6": (110, 150, 80), "art_text": (250, 250, 240),
        # 解説のスキルカードの札 (場所を選ぶ / すぐ使う)
        "tag_target": (52, 86, 128), "tag_instant": (108, 88, 48), "tag_text": (255, 255, 255),
    },
    # C 夕方: 暖かいクリーム色の背景、茶〜濃い緑の文字
    "dusk": {
        # 背景・飾り
        "bg": (250, 237, 214), "dot": (238, 220, 192), "deco_stem": (224, 198, 158), "deco_a": (234, 210, 174),
        "deco_b": (228, 204, 166), "logo_ring": (210, 180, 136), "logo_leaf": (110, 146, 66),
        # 文字・アクセント
        "text": (68, 46, 26), "muted": (118, 94, 68), "accent": (186, 104, 38), "accent_bright": (148, 80, 24),
        # 面・ボタン・カード
        "surface": (255, 248, 232), "surface_edge": (212, 186, 148), "button": (250, 236, 208),
        "button_hover": (238, 204, 156), "button_edge": (196, 158, 108), "disabled_fill": (240, 232, 218),
        "disabled_edge": (222, 210, 190), "disabled_text": (170, 154, 132), "card": (255, 247, 228), "card_text": (88, 60, 34),
        "card_idle": (246, 228, 198), "card_hover": (238, 210, 166), "image_bg": (250, 241, 224),
        "image_edge": (198, 170, 128), "popup": (255, 251, 240), "input": (255, 252, 244), "focus_ring": (68, 46, 26),
        "dot_idle": (186, 156, 118),
        # ゲーム右パネル
        "gp_bg": (248, 238, 218), "gp_button": (240, 222, 190), "gp_button_edge": (192, 156, 108),
        "gp_text_strong": (56, 38, 20), "gp_text": (74, 50, 28), "gp_card_text": (62, 42, 22), "gp_label": (96, 68, 40),
        "gp_soft": (112, 88, 62), "gp_dim": (118, 94, 70), "gp_faint": (126, 103, 79), "gp_info": (107, 107, 107),
        "gp_bar_bg": (230, 214, 184), "gp_card": (255, 250, 236), "gp_card_off": (236, 228, 212),
        "gp_card_edge": (170, 98, 36), "gp_card_edge_off": (210, 196, 172), "gp_card_text_off": (164, 148, 124),
        "gp_speed_on": (21, 101, 192), "gp_speed_on_edge": (13, 71, 161), "gp_speed_on_text": (255, 255, 255),
        "leaf_title": (96, 100, 44), "bubble_fill": (255, 248, 232), "bubble_edge": (212, 186, 148),
        "bubble_text": (62, 42, 22),
        # 意味のある色
        "herb": (51, 93, 126), "carn": (155, 54, 52), "warn": (157, 70, 178), "warn_pill_bg": (251, 236, 255),
        "warn_ink": (255, 255, 255), "temp": (127, 106, 39), "badge_ink": (255, 255, 255), "mp_text": (117, 108, 60),
        "mp_bar": (240, 190, 60), "clear": (90, 112, 72), "fail": (188, 65, 63), "error": (153, 89, 83),
        "cost_1": (63, 95, 59), "cost_2": (102, 87, 38), "cost_3": (136, 69, 60), "ok_green": (74, 126, 86),
        "ng_text": (110, 80, 80),
        # ステージ選択の、絵がないときの代わりの絵
        "art_1": (86, 140, 110), "art_2": (120, 110, 170), "art_3": (176, 120, 84), "art_4": (84, 130, 176), "art_5": (160, 100, 130),
        "art_6": (110, 150, 80), "art_text": (250, 250, 240),
        # 解説のスキルカードの札 (場所を選ぶ / すぐ使う)
        "tag_target": (52, 86, 128), "tag_instant": (108, 88, 48), "tag_text": (255, 255, 255),
    },
}

DEFAULT_THEME = "meadow"
THEME_ORDER = ("meadow", "sky", "dusk", "dark")                 # 配色ボタンで切り替わる順
DISPLAY_NAMES = {"meadow": "草原", "sky": "青空", "dusk": "夕方", "dark": "夜"}
SETTINGS_PATH = Path(__file__).resolve().parent / "saves" / "ui_settings.json"      # 選んだ配色の保存先 (saves/ は .gitignore 済み)
_current = DEFAULT_THEME


def set_theme(name):
    """配色を切り替える (知らない名前は無視して、いまのままにする)。"""
    global _current
    if name in THEMES:
        _current = name


def current_theme():
    return _current


def display_name(name=None):
    return DISPLAY_NAMES.get(name or _current, name or _current)


def color(key):
    return THEMES[_current][key]


def load_settings():
    """起動時に、保存してある配色を読む。ファイルがない・壊れている・知らない名前のときは、既定の配色にする。"""
    name = DEFAULT_THEME
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)["theme"]
        if isinstance(saved, str) and saved in THEMES:
            name = saved
    except Exception:
        pass
    set_theme(name)


def save_settings():
    """いまの配色を保存する (保存できなくても、画面は止めない)。"""
    try:
        SETTINGS_PATH.parent.mkdir(exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"theme": _current}, f, ensure_ascii=False)
        os.replace(tmp, SETTINGS_PATH)
    except Exception:
        pass


def next_theme():
    """草原 → 青空 → 夕方 → 夜 → 草原… と切り替えて、保存する。"""
    set_theme(THEME_ORDER[(THEME_ORDER.index(_current) + 1) % len(THEME_ORDER)])
    save_settings()
