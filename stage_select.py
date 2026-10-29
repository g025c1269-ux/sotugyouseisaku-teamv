"""ゲームモードのステージ選択画面 (形だけ。ステージの中身はまだない)。

ステージの定義は data/stages.json (id / name / description のリスト) にある。
ステージを増やすには、JSONに1件足し、中身ができたら STAGE_HANDLERS[id] に開始用の関数を登録する
(登録がないステージは「準備中」と表示して、選択画面に戻る)。
"""
import json
from pathlib import Path

import pygame

from title_screen import SIZE, BACKGROUND, TEXT, MUTED, _font
from help_screen import wrap_text

DATA_PATH = Path(__file__).resolve().parent / "data" / "stages.json"
GAME_HELP_PATH = Path(__file__).resolve().parent / "data" / "game_help_text.json"
ACCENT = (152, 197, 123)
NOTICE_MS = 1500
# 横スクロール(カルーセル)の見た目: 中央のカードを大きく、左右の隣のカードを小さく少しだけ見せる
SLIDE_MS = 260                       # 切り替えのスライドにかける時間
CARD_SIZE = (420, 240)               # 中央のカードの大きさ
CARD_CENTER = (500, 290)
CARD_SPACING = 340                   # カードの中心どうしの間隔 (px。ステージが増えても同じ間隔で横に並ぶ)
SIDE_SCALE = 0.62                    # 隣のカードの縮小率

# ステージの中身ができたら、ここに {ステージのid: 開始用の関数} を登録する。
# 関数は引数なしで呼ばれ、"back" か "quit" を返す (戻ったらステージ選択画面に戻る)。
STAGE_HANDLERS = {}


def load_stages(path=DATA_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            stages = [{"id": str(s["id"]), "name": str(s["name"]), "description": str(s["description"])}
                      for s in json.load(f)["stages"]]
        if stages:
            return stages
    except Exception:
        pass
    return []


class StageSelect:
    def __init__(self):
        self.screen = pygame.display.get_surface() or pygame.display.set_mode(SIZE)
        self.fonts = {size: _font(size) for size in (14, 18, 22, 28)}
        self.stages = load_stages(DATA_PATH)
        self.index = 0                       # 選択中(中央)のステージ
        self._from = 0.0                     # スライドの出発位置
        self._slide_start = None             # スライドを始めた時刻ms (Noneなら止まっている)
        self.focus = "stages"                # "stages"(カルーセル) / "back"(戻るボタン)
        self.mouse = pygame.mouse.get_pos()
        self.keyboard = False
        self.notice = None                   # (メッセージ, 表示を終える時刻ms)
        self.help_center, self.help_radius = (948, 52), 22
        self.back_rect = pygame.Rect(40, 520, 180, 48)
        self.arrow_rects = self._arrow_rects()
        self._card_cache = {}

    def _arrow_rects(self):
        n = len(self.stages)
        half = 11 * max(0, n - 1) + 52               # 点の並びの左右に置く
        return {"left": pygame.Rect(CARD_CENTER[0] - half - 22, 534 - 22, 44, 44),
                "right": pygame.Rect(CARD_CENTER[0] + half - 22, 534 - 22, 44, 44)}

    # ---------- 位置とアニメーション ----------
    def position(self, now=None):
        """いま画面に出ている位置 (ステージ番号の小数。スライド中は出発位置から index へ近づく)"""
        if self._slide_start is None:
            return float(self.index)
        now = pygame.time.get_ticks() if now is None else now
        t = (now - self._slide_start) / SLIDE_MS
        if t >= 1.0:
            self._slide_start = None
            return float(self.index)
        t = 1 - (1 - t) ** 3                         # ゆっくり止まる動き
        return self._from + (self.index - self._from) * t

    def _go(self, index):
        index = max(0, min(len(self.stages) - 1, index))   # 端より先には進まない
        if index == self.index:
            return
        self._from = self.position()
        self.index = index
        self._slide_start = pygame.time.get_ticks()

    def _can_go(self, direction):
        return 0 <= self.index + direction < len(self.stages)

    # ---------- カードの位置 ----------
    def _card_rect(self, i, pos):
        """ステージiのカードの、いまの画面上の位置と大きさ。(rect, 縮小率)"""
        d = i - pos
        scale = 1.0 - (1.0 - SIDE_SCALE) * min(abs(d), 1.0)
        w, h = int(CARD_SIZE[0] * scale), int(CARD_SIZE[1] * scale)
        rect = pygame.Rect(0, 0, w, h)
        rect.center = (int(CARD_CENTER[0] + d * CARD_SPACING), CARD_CENTER[1])
        return rect, scale

    def _visible_cards(self, pos):
        """画面に見えるカードを、奥(遠い)から手前(中央)の順に返す"""
        cards = [(i, *self._card_rect(i, pos)) for i in range(len(self.stages)) if abs(i - pos) < 2.2]
        return sorted(cards, key=lambda c: -abs(c[0] - pos))

    # ---------- 入力 ----------
    def _help_hit(self, pos):
        dx, dy = pos[0] - self.help_center[0], pos[1] - self.help_center[1]
        return dx * dx + dy * dy <= self.help_radius ** 2

    def _choose(self, index):
        """選んだステージを開始する。中身がなければ「準備中」を出して、選択画面に戻る。"""
        stage = self.stages[index]
        handler = STAGE_HANDLERS.get(stage["id"])
        if handler is not None:
            return handler()
        self.notice = (f"「{stage['name']}」は準備中です", pygame.time.get_ticks() + NOTICE_MS)
        return None

    def handle_event(self, event):
        """"back" / "quit" / "help" / None を返す"""
        if event.type == pygame.QUIT:
            return "quit"
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            self.keyboard = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.keyboard = False
            self.notice = None
            if self._help_hit(event.pos):
                return "help"
            if self.back_rect.collidepoint(event.pos):
                return "back"
            for name, direction in (("left", -1), ("right", 1)):
                if self.arrow_rects[name].collidepoint(event.pos):
                    self._go(self.index + direction) if self._can_go(direction) else None
                    return None
            if not self.stages:
                return None
            pos = self.position()
            for i, rect, _ in reversed(self._visible_cards(pos)):      # 手前(中央)のカードから判定
                if rect.collidepoint(event.pos):
                    if i == self.index:
                        return self._choose(i)                        # 中央のカード → 決定
                    self._go(i)                                       # 左右のカード → そこへ切り替え
                    return None
            for i in range(len(self.stages)):                         # 下の点 → そのステージへ
                if pygame.Rect(0, 0, 24, 24).move(self._dot_center(i)[0] - 12, self._dot_center(i)[1] - 12).collidepoint(event.pos):
                    self._go(i)
                    return None
        elif event.type == pygame.KEYDOWN:
            self.keyboard = True
            if event.key == pygame.K_ESCAPE:
                return "back"
            if event.key == pygame.K_F1 or getattr(event, "unicode", "") in ("?", "？"):
                return "help"
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT) and self.focus == "stages":
                self._go(self.index + (1 if event.key == pygame.K_RIGHT else -1))
            elif event.key == pygame.K_DOWN:
                self.focus = "back"
            elif event.key == pygame.K_UP:
                self.focus = "stages"
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.notice = None
                if self.focus == "back":
                    return "back"
                if self.stages:
                    return self._choose(self.index)
        return None

    # ---------- 描画 ----------
    def _text(self, text, size, center=None, topleft=None, color=TEXT):
        surface = self.fonts[size].render(text, True, color)
        rect = surface.get_rect(center=center) if center is not None else surface.get_rect(topleft=topleft)
        self.screen.blit(surface, rect)

    def _background(self):
        self.screen.fill(BACKGROUND)
        for x in range(25, 1000, 55):
            for y in range(25, 600, 55):
                pygame.draw.circle(self.screen, (19, 38, 29), (x, y), 1)
        for side in (0, 1):
            for i in range(7):
                x = 50 + i * 24 if side == 0 else 950 - i * 24
                y = 595 - i * 33
                pygame.draw.line(self.screen, (34, 69, 44), (x, 600), (x, y - 32), 2)
                pygame.draw.ellipse(self.screen, (25, 57, 36), (x - 24, y - 30, 24, 12))
                pygame.draw.ellipse(self.screen, (35, 73, 44), (x, y - 48, 27, 13))

    def _card_surface(self, i):
        """カード1枚の絵 (等倍)。描くときに縮小して使う"""
        if i in self._card_cache:
            return self._card_cache[i]
        stage = self.stages[i]
        surf = pygame.Surface(CARD_SIZE, pygame.SRCALPHA)
        pygame.draw.rect(surf, (28, 62, 40), surf.get_rect(), border_radius=16)
        pygame.draw.rect(surf, ACCENT, surf.get_rect(), 2, border_radius=16)
        name = self.fonts[28].render(stage["name"], True, TEXT)
        surf.blit(name, name.get_rect(center=(CARD_SIZE[0] // 2, 80)))
        for j, line in enumerate(wrap_text(stage["description"], self.fonts[18], CARD_SIZE[0] - 60)[:4]):
            text = self.fonts[18].render(line, True, (205, 222, 200))
            surf.blit(text, text.get_rect(center=(CARD_SIZE[0] // 2, 142 + j * 26)))
        self._card_cache[i] = surf
        return surf

    def _dot_center(self, i):
        return (CARD_CENTER[0] + int((i - (len(self.stages) - 1) / 2) * 22), 534)

    def _button(self, rect, label, enabled, active):
        if not enabled:
            fill, edge, color = (16, 30, 23), (40, 58, 46), (88, 105, 92)      # 押せない見た目
        else:
            fill, edge, color = (51, 96, 56) if active else (22, 49, 33), ACCENT if active else (56, 86, 60), TEXT
        pygame.draw.rect(self.screen, fill, rect, border_radius=10)
        pygame.draw.rect(self.screen, edge, rect, 2 if (enabled and active) else 1, border_radius=10)
        self._text(label, 22, center=rect.center, color=color)

    def draw(self):
        self._background()
        self._text("ゲームモード", 28, center=(500, 60))
        self._text("ステージを選んでください", 14, center=(500, 96), color=MUTED)
        pos = self.position()
        for i, rect, scale in self._visible_cards(pos):
            card = pygame.transform.smoothscale(self._card_surface(i), rect.size)
            alpha = int(255 - 125 * min(abs(i - pos), 1.0))          # 中央が一番はっきり、隣は少し暗く
            card.set_alpha(alpha)
            self.screen.blit(card, rect)
        # 中央のカードの選択の強調 (キーボード操作中、カルーセルにフォーカスがあるとき)
        if self.stages and self.keyboard and self.focus == "stages":
            rect, _ = self._card_rect(self.index, pos)
            pygame.draw.rect(self.screen, (255, 255, 255), rect.inflate(8, 8), 1, border_radius=18)
        # 左右の矢印と、いまの位置を示す点 (●○○○)
        for name, label, direction in (("left", "◀", -1), ("right", "▶", 1)):
            rect = self.arrow_rects[name]
            enabled = self._can_go(direction)
            self._button(rect, label, enabled, enabled and (not self.keyboard) and rect.collidepoint(self.mouse))
        for i in range(len(self.stages)):
            cx, cy = self._dot_center(i)
            if i == self.index:
                pygame.draw.circle(self.screen, ACCENT, (cx, cy), 7)
            else:
                pygame.draw.circle(self.screen, (120, 150, 125), (cx, cy), 6, 2)
        back_active = (self.keyboard and self.focus == "back") or \
                      ((not self.keyboard) and self.back_rect.collidepoint(self.mouse))
        pygame.draw.rect(self.screen, (51, 96, 56) if back_active else (22, 49, 33), self.back_rect, border_radius=9)
        pygame.draw.rect(self.screen, ACCENT if back_active else (56, 86, 60), self.back_rect, 2 if back_active else 1, border_radius=9)
        self._text("戻る", 22, center=self.back_rect.center)
        # 右上の丸い「？」ボタン (ゲームモードのあそびかた)
        hover = (not self.keyboard) and self._help_hit(self.mouse)
        pygame.draw.circle(self.screen, (51, 96, 56) if hover else (22, 49, 33), self.help_center, self.help_radius)
        pygame.draw.circle(self.screen, ACCENT if hover else (56, 86, 60), self.help_center, self.help_radius, 2)
        self._text("？", 28, center=self.help_center)
        self._text("あそびかた", 14, center=(self.help_center[0], self.help_center[1] + 36), color=MUTED)
        self._text("←→:切り替え / Enter:決定 / Esc:戻る", 14, center=(500, 586), color=MUTED)
        if self.notice is not None:
            if pygame.time.get_ticks() < self.notice[1]:
                box = pygame.Rect(0, 0, 420, 90)
                box.center = (500, 300)
                pygame.draw.rect(self.screen, (8, 19, 16), box, border_radius=12)
                pygame.draw.rect(self.screen, (163, 204, 131), box, 2, border_radius=12)
                self._text(self.notice[0], 28, center=box.center, color=(163, 204, 131))
            else:
                self.notice = None


def show_stage_select():
    """ステージ選択画面を開く。"back"(タイトル画面へ) または "quit" を返す。
    pygameの初期化と画面は、呼び出し元(タイトル画面)のものをそのまま使う。"""
    screen = StageSelect()
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            result = screen.handle_event(event)
            if result == "help":                         # 「？」→ ゲームモードのあそびかた → 戻ったらこの画面のまま
                from help_screen import show_help_screen
                if show_help_screen(GAME_HELP_PATH, "ゲームモードのあそびかた") == "quit":
                    return "quit"
                screen.mouse = pygame.mouse.get_pos()
                break
            if result:
                return result
        screen.draw()
        pygame.display.flip()
        clock.tick(60)
