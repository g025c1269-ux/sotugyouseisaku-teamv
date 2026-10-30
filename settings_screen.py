"""観察モードの開始前設定画面 (タイトル画面のスタイルに合わせたpygame画面)。

show_settings_screen() は ("start", 設定dict) / ("load", {"explanation_mode": ...}) / ("back", None) / ("quit", None) を返す。
確定した設定は apply_settings() で、World() を作る前に config へ反映する。
"""
import copy

import pygame

import config
import save_load
from explanation_settings import ExplanationSettings
from title_screen import SIZE, _font
from theme import color as C

# 季節ONのときの基準値 (設定画面を開く前のconfigの値を控えておく)
_DEFAULT_TEMP_SUMMER = config.TEMP_SUMMER
_DEFAULT_TEMP_WINTER = config.TEMP_WINTER
_DEFAULT_SEASON_FOOD_MULT = copy.deepcopy(config.SEASON_FOOD_MULT)
_DEFAULT_RL_LEARNING_RATE = config.RL_LEARNING_RATE
_DEFAULT_TEMPERATURE = config.TEMPERATURE


# 数値項目: (キー, ラベル, 最小, 最大, 1回の増減)
RANGES = {"fixed_temp": (0, 40, 1), "herb": (10, 3000, 50), "carn": (0, 1000, 10)}
# 初期個体数は−/＋ボタンや←→キーでは増減せず、数値欄に直接入力して確定する
INPUT_ONLY = {"herb", "carn"}


def default_settings():
    return {
        "neuro": bool(config.USE_NEUROEVOLUTION),
        "rl": True,
        "seasons": True,
        "fixed_temp": 20,
        "herb": int(config.INITIAL_HERBIVORES),
        "carn": int(config.INITIAL_CARNIVORES),
        "explanation_mode": "rule",
    }


def clamp_value(key, value):
    lo, hi, _ = RANGES[key]
    return max(lo, min(hi, int(round(value))))


def apply_settings(s):
    """設定をconfigに反映する。World()を作る前に呼ぶこと (食料の出現数などはWorld生成時に計算されるため)。"""
    config.USE_NEUROEVOLUTION = bool(s["neuro"])
    rl_on = bool(s["neuro"]) and bool(s["rl"])          # NNがOFFなら強化学習も使わない
    config.RL_LEARNING_RATE = _DEFAULT_RL_LEARNING_RATE if rl_on else 0.0
    config.SEASONS_ENABLED = bool(s["seasons"])
    if s["seasons"]:
        config.TEMP_SUMMER = _DEFAULT_TEMP_SUMMER
        config.TEMP_WINTER = _DEFAULT_TEMP_WINTER
        config.SEASON_FOOD_MULT = copy.deepcopy(_DEFAULT_SEASON_FOOD_MULT)
        config.TEMPERATURE = _DEFAULT_TEMPERATURE
    else:
        t = float(clamp_value("fixed_temp", s["fixed_temp"]))
        config.TEMP_SUMMER = config.TEMP_WINTER = t     # 両者が同じなら update_temperature は固定気温になる
        config.TEMPERATURE = t
        config.SEASON_FOOD_MULT = {k: 1.0 for k in _DEFAULT_SEASON_FOOD_MULT}
    config.INITIAL_HERBIVORES = clamp_value("herb", s["herb"])
    config.INITIAL_CARNIVORES = clamp_value("carn", s["carn"])


class SettingsScreen:
    ROWS = [("neuro", "ニューロエボリューション", "toggle"),
            ("rl", "強化学習", "toggle"),
            ("seasons", "季節", "toggle"),
            ("fixed_temp", "固定気温 (℃)", "number"),
            ("herb", "初期の草食数", "number"),
            ("carn", "初期の肉食数", "number")]
    BUTTONS = [("back", "戻る"), ("load", "ロード"), ("start", "開始")]

    def __init__(self, message=None):
        self.screen = pygame.display.set_mode(SIZE)
        pygame.display.set_caption("ECOSYSTEM — 観察モードの設定")
        self.fonts = {size: _font(size) for size in (14, 18, 22, 28)}
        self.s = default_settings()
        self.explanation = ExplanationSettings(_font)
        self.message = message
        self.focus_id = ("row", "neuro")   # 今フォーカスしている項目 ("row"/"button", キー)
        self.editing = None             # 数値入力中の文字列 (入力中でなければNone)
        self.mouse = pygame.mouse.get_pos()
        self.keyboard = False
        self.can_load = save_load.save_exists()
        self._layout()

    # ---------- レイアウト ----------
    def _layout(self):
        self.row_rects, self.toggle_rects, self.minus_rects, self.plus_rects, self.value_rects = {}, {}, {}, {}, {}
        y = 104
        for key, _, kind in self.ROWS:
            self.row_rects[key] = pygame.Rect(190, y, 620, 52)
            if kind == "toggle":
                self.toggle_rects[key] = pygame.Rect(640, y + 8, 130, 36)
            else:
                if key in INPUT_ONLY:
                    self.value_rects[key] = pygame.Rect(600, y + 8, 184, 36)
                else:
                    self.minus_rects[key] = pygame.Rect(600, y + 8, 36, 36)
                    self.value_rects[key] = pygame.Rect(642, y + 8, 100, 36)
                    self.plus_rects[key] = pygame.Rect(748, y + 8, 36, 36)
            y += 58
        self.button_rects = {key: pygame.Rect(210 + i * 200 + i * 10, 500, 190, 52)
                             for i, (key, _) in enumerate(self.BUTTONS)}

    # ---------- 状態 ----------
    def _enabled(self, key):
        if key == "rl":
            return self.s["neuro"]
        if key == "fixed_temp":
            return not self.s["seasons"]
        return True

    def _button_enabled(self, key):
        return key != "load" or self.can_load

    def _focus_items(self):
        items = [("row", k) for k, _, _ in self.ROWS if self._enabled(k)]
        items += [("explanation", k) for k in ("rule", "ai")]
        items += [("button", k) for k, _ in self.BUTTONS if self._button_enabled(k)]
        return items

    def _focused(self):
        items = self._focus_items()
        return self.focus_id if self.focus_id in items else items[0]

    def _move_focus(self, delta):
        items = self._focus_items()
        i = items.index(self._focused())
        self.focus_id = items[(i + delta) % len(items)]

    def _toggle(self, key):
        if not self._enabled(key):
            return
        self.s[key] = not self.s[key]
        if key == "neuro" and not self.s["neuro"]:
            self.s["rl"] = False        # NNがOFFなら強化学習はOFF固定
        elif key == "neuro" and self.s["neuro"]:
            self.s["rl"] = True

    def _step(self, key, direction):
        if not self._enabled(key):
            return
        self._commit()
        self.s[key] = clamp_value(key, self.s[key] + direction * RANGES[key][2])

    def _commit(self):
        if self.editing is not None:
            key = self._editing_key
            if self.editing != "":
                self.s[key] = clamp_value(key, int(self.editing))     # 範囲外は丸める
            self.editing = None

    def _start_edit(self, key, initial=""):
        if self._enabled(key):
            self._commit()
            self._editing_key = key
            self.editing = initial

    def _activate_button(self, key):
        self._commit()
        if key in ("start", "load") and not self.explanation.can_start():
            return None
        if key == "start":
            return ("start", dict(self.s, explanation_mode=self.explanation.mode))
        if key == "load":
            return ("load", {"explanation_mode": self.explanation.mode})
        return ("back", None)

    # ---------- 入力 ----------
    def handle_event(self, event):
        self.explanation.poll()
        if self.explanation.handle_event(event):
            self.keyboard = False
            self._commit()
            self.focus_id = ("explanation", self.explanation.mode)
            self.s["explanation_mode"] = self.explanation.mode
            return None
        if event.type == pygame.QUIT:
            return ("quit", None)
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            self.keyboard = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._click(event.pos)
        elif event.type == pygame.KEYDOWN:
            return self._key(event)
        return None

    def _click(self, pos):
        self.keyboard = False
        for key, rect in self.button_rects.items():
            if rect.collidepoint(pos) and self._button_enabled(key):
                return self._activate_button(key)
        for key, _, kind in self.ROWS:
            if not self._enabled(key):
                continue
            if kind == "toggle" and self.toggle_rects[key].collidepoint(pos):
                self._commit()
                self.focus_id = ("row", key)
                self._toggle(key)
                return None
            if kind == "number":
                if any(r.get(key) is not None and r[key].collidepoint(pos)
                       for r in (self.minus_rects, self.plus_rects, self.value_rects)):
                    self._commit()
                    self.focus_id = ("row", key)
                if key in self.minus_rects and self.minus_rects[key].collidepoint(pos):
                    self._step(key, -1)
                    return None
                if key in self.plus_rects and self.plus_rects[key].collidepoint(pos):
                    self._step(key, +1)
                    return None
                if self.value_rects[key].collidepoint(pos):
                    self._start_edit(key, "")
                    return None
        self._commit()
        return None

    def _key(self, event):
        self.keyboard = True
        kind, key = self._focused()
        if self.editing is not None:
            kind, key = "row", self._editing_key
        digit = None
        if pygame.K_0 <= event.key <= pygame.K_9:
            digit = str(event.key - pygame.K_0)
        elif pygame.K_KP0 <= event.key <= pygame.K_KP9:
            digit = str(event.key - pygame.K_KP0)

        if event.key == pygame.K_ESCAPE:
            if self.editing is not None:
                self.editing = None
                return None
            return ("back", None)
        if event.key in (pygame.K_UP, pygame.K_DOWN):
            self._commit()
            self._move_focus(1 if event.key == pygame.K_DOWN else -1)
            return None
        if kind == "row" and dict((k, t) for k, _, t in self.ROWS)[key] == "number":
            if digit is not None:
                if self.editing is None:
                    self._start_edit(key, "")
                if len(self.editing) < 5:
                    self.editing += digit
                return None
            if event.key == pygame.K_BACKSPACE and self.editing is not None:
                self.editing = self.editing[:-1]
                return None
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                if key not in INPUT_ONLY:
                    self._step(key, 1 if event.key == pygame.K_RIGHT else -1)
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                if self.editing is not None:
                    self._commit()
                else:
                    self._start_edit(key, "")
                return None
        elif kind == "row":
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_LEFT, pygame.K_RIGHT):
                self._toggle(key)
                return None
        elif kind == "explanation":
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_LEFT, pygame.K_RIGHT):
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    key = "ai" if key == "rule" else "rule"
                    self.focus_id = ("explanation", key)
                self.explanation.select(key)
                self.s["explanation_mode"] = self.explanation.mode
            return None
        elif kind == "button":
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                return self._activate_button(key)
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                items = self._focus_items()
                i = items.index(self._focused()) + (1 if event.key == pygame.K_RIGHT else -1)
                if 0 <= i < len(items) and items[i][0] == "button":
                    self.focus_id = items[i]
                return None
        return None

    # ---------- 描画 ----------
    def _text(self, text, size, center=None, topleft=None, color=None):
        surface = self.fonts[size].render(text, True, C("text") if color is None else color)
        rect = surface.get_rect(center=center) if center is not None else surface.get_rect(topleft=topleft)
        self.screen.blit(surface, rect)
        return rect

    def _background(self):
        self.screen.fill(C("bg"))
        for x in range(25, 1000, 55):
            for y in range(25, 600, 55):
                pygame.draw.circle(self.screen, C("dot"), (x, y), 1)
        for side in (0, 1):
            for i in range(7):
                x = 50 + i * 24 if side == 0 else 950 - i * 24
                y = 595 - i * 33
                pygame.draw.line(self.screen, C("deco_stem"), (x, 600), (x, y - 32), 2)
                pygame.draw.ellipse(self.screen, C("deco_a"), (x - 24, y - 30, 24, 12))
                pygame.draw.ellipse(self.screen, C("deco_b"), (x, y - 48, 27, 13))

    def _button(self, rect, label, enabled=True, active=False, selected=False):
        if not enabled:
            fill, edge, color = C("disabled_fill"), C("disabled_edge"), C("disabled_text")
        else:
            fill = C("button_hover") if active else C("button")
            edge, color = (C("accent") if active or selected else C("button_edge")), C("text")
        pygame.draw.rect(self.screen, fill, rect, border_radius=9)
        pygame.draw.rect(self.screen, edge, rect, 1, border_radius=9)
        self._text(label, 22, center=rect.center, color=color)

    def draw(self):
        self._background()
        self.explanation.draw(self.screen, self._focused() if self.keyboard else None)
        self._text("観察モードの設定", 28, center=(500, 56))
        self._text("開始する前に条件を選べます", 14, center=(500, 86), color=C("muted"))
        focus_kind, focus_key = self._focused()
        for key, label, kind in self.ROWS:
            rect = self.row_rects[key]
            enabled = self._enabled(key)
            focused = self.keyboard and focus_kind == "row" and focus_key == key
            pygame.draw.rect(self.screen, C("surface"), rect, border_radius=10)
            pygame.draw.rect(self.screen, C("accent") if focused else C("surface_edge"), rect, 2 if focused else 1, border_radius=10)
            self._text(label, 18, topleft=(rect.x + 20, rect.y + 9), color=C("text") if enabled else C("disabled_text"))
            hint = {"herb": "数値欄をクリックして入力し、Enterで確定 (10〜3000)",
                    "carn": "数値欄をクリックして入力し、Enterで確定 (0〜1000)",
                    "rl": "ニューロエボリューションがOFFのときは選べません",
                    "fixed_temp": "季節がOFFのときだけ入力できます (0〜40)",
                    "seasons": "OFFにすると気温は固定で、季節の演出は出ません"}.get(key)
            if hint:
                self._text(hint, 14, topleft=(rect.x + 20, rect.y + 31), color=C("muted") if enabled else C("disabled_text"))
            if kind == "toggle":
                on = self.s[key] and enabled
                tr = self.toggle_rects[key]
                active = enabled and tr.collidepoint(self.mouse) and not self.keyboard
                self._button(tr, "ON" if on else "OFF", enabled, active, selected=on)
            else:
                for rects, sign in ((self.minus_rects, "−"), (self.plus_rects, "＋")):
                    if key not in rects:
                        continue
                    r = rects[key]
                    self._button(r, sign, enabled, enabled and r.collidepoint(self.mouse) and not self.keyboard)
                vr = self.value_rects[key]
                editing = enabled and self.editing is not None and self._editing_key == key
                pygame.draw.rect(self.screen, C("input") if enabled else C("disabled_fill"), vr, border_radius=7)
                pygame.draw.rect(self.screen, C("accent") if editing else C("button_edge"), vr, 2 if editing else 1, border_radius=7)
                shown = (self.editing or "") + ("|" if editing else "") if editing else str(self.s[key])
                self._text(shown, 22, center=vr.center, color=C("text") if enabled else C("disabled_text"))
        for key, label in self.BUTTONS:
            rect = self.button_rects[key]
            enabled = self._button_enabled(key)
            focused = self.keyboard and focus_kind == "button" and focus_key == key
            hovered = (not self.keyboard) and rect.collidepoint(self.mouse)
            self._button(rect, label, enabled, active=enabled and (focused or hovered), selected=focused)
        if not self.can_load:
            self._text("セーブデータがないため「ロード」は選べません", 14, center=(500, 566), color=C("disabled_text"))
        if self.message:
            self._text(self.message, 18, center=(500, 584), color=C("error"))
        self._text("↑↓:項目 / ←→:変更 / Enter:決定・数値入力 / Esc:戻る", 14, center=(500, 474), color=C("muted"))


def show_settings_screen(message=None):
    """設定画面を出し、("start", 設定) / ("load", {"explanation_mode": ...}) / ("back", None) / ("quit", None) を返す。"""
    pygame.init()
    try:
        screen = SettingsScreen(message)
        clock = pygame.time.Clock()
        while True:
            for event in pygame.event.get():
                result = screen.handle_event(event)
                if result:
                    return result
            screen.draw()
            pygame.display.flip()
            clock.tick(60)
    finally:
        pygame.quit()
