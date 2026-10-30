"""ゲームモードのステージ選択画面 (形だけ。ステージの中身はまだない)。

ステージの定義は data/stages.json (id / name / description のリスト) にある。
カードには「ステージN」(stages.json の並び順で自動) と説明とイラストを出す。ステージ名 (name) はデータに残すが、この画面には出さない。
イラスト: assets/stages/<id>.png があれば、カード上部の絵の枠 (400x100 px) に、縦横比を保って収めて出す。
  推奨サイズは 800x200 px (4:1 の PNG。枠の2倍で、縮小しても綺麗に見える。小さくても 400x100 px 以上)。背景は不透明でも透明でもよい。
  なければ、ステージごとの色の背景にステージ番号を大きく出した代わりの絵を出す。
ステージを増やすには、JSONに1件足し、中身ができたら STAGE_HANDLERS[id] に開始用の関数を登録する
(登録がないステージは「準備中」と表示して、選択画面に戻る)。
"playable": true のステージは、決定すると play_stage で遊べる (ステージ選択から結果画面まで)。
"""
import json
from pathlib import Path

import pygame

from title_screen import SIZE, _font
from theme import color as C
from help_screen import wrap_text

DATA_PATH = Path(__file__).resolve().parent / "data" / "stages.json"
GAME_HELP_PATH = Path(__file__).resolve().parent / "data" / "game_help_text.json"
STAGE_IMAGE_DIR = Path(__file__).resolve().parent / "assets" / "stages"
NOTICE_MS = 1500
# 横スクロール(カルーセル)の見た目: 中央のカードを大きく、左右の隣のカードを小さく少しだけ見せる
SLIDE_MS = 260                       # 切り替えのスライドにかける時間
CARD_SIZE = (420, 240)               # 中央のカードの大きさ
CARD_CENTER = (500, 290)
CARD_SPACING = 340                   # カードの中心どうしの間隔 (px。ステージが増えても同じ間隔で横に並ぶ)
SIDE_SCALE = 0.62                    # 隣のカードの縮小率
ART_BOX = pygame.Rect(10, 10, 400, 100)      # カード上部のイラストの枠 (カード内の位置)
DESC_TOP, DESC_HEIGHT = 150, 80              # 説明文を入れる範囲 (カード内のy、高さ)。収まる一番大きい文字サイズを使う
DESC_SIZES = (18, 16, 14)

# ステージの中身ができたら、ここに {ステージのid: 開始用の関数} を登録する。
# 関数は引数なしで呼ばれ、"back" か "quit" を返す (戻ったらステージ選択画面に戻る)。
STAGE_HANDLERS = {}


def play_stage(stage):
    """ステージを遊ぶ (世界を作る → シミュレーション画面 → 結果画面。「もう一度」なら作り直して繰り返す)。
    ウィンドウが閉じられたら "quit"、ステージ選択に戻るときは None を返す。抜けるときは必ず config を元に戻す。"""
    import stage_setup
    from main import run_with_visualization
    from result_screen import show_result_screen
    try:
        while True:
            world = stage_setup.build_world(stage)
            result = run_with_visualization(world, stage=stage)
            if result == "quit":
                return "quit"
            if result == "menu":
                return None
            choice = show_result_screen(result)
            if choice == "quit":
                return "quit"
            if choice == "back":
                return None
            stage_setup.restore()                # 「もう一度」: 設定を戻してから、世界を作り直す
    finally:
        stage_setup.restore()
        pygame.display.set_mode(SIZE)            # 遊ぶ画面は大きさが違うので、ステージ選択の大きさに戻す
        pygame.display.set_caption("ECOSYSTEM — 生態系シミュレーションゲーム")


def load_stages(path=DATA_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            # 名前・説明のほか、初期設定(initial_* / food_mult など)もそのまま持たせる (stage_setup.build_world が読む)
            stages = [{**s, "id": str(s["id"]), "name": str(s["name"]), "description": str(s["description"])}
                      for s in json.load(f)["stages"]]
        if stages:
            return stages
    except Exception:
        pass
    return []


class StageSelect:
    def __init__(self):
        self.screen = pygame.display.get_surface() or pygame.display.set_mode(SIZE)
        self.fonts = {size: _font(size) for size in (14, 16, 18, 22, 28, 64)}
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
        self._images = {}                    # ステージのid → イラスト (なければ None)

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
        if stage.get("playable"):                # 遊べるステージ: 終わったらこの画面に戻る
            if play_stage(stage) == "quit":
                return "quit"
            self.screen = pygame.display.get_surface()
            self.mouse = pygame.mouse.get_pos()
            return None
        handler = STAGE_HANDLERS.get(stage["id"])
        if handler is not None:
            return handler()
        self.notice = (f"ステージ{index + 1}は準備中です", pygame.time.get_ticks() + NOTICE_MS)
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
    def _text(self, text, size, center=None, topleft=None, color=None):
        surface = self.fonts[size].render(text, True, C("text") if color is None else color)
        rect = surface.get_rect(center=center) if center is not None else surface.get_rect(topleft=topleft)
        self.screen.blit(surface, rect)

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

    def _stage_image(self, stage_id):
        if stage_id not in self._images:
            try:
                self._images[stage_id] = pygame.image.load(str(STAGE_IMAGE_DIR / f"{stage_id}.png")).convert_alpha()
            except Exception:
                self._images[stage_id] = None            # ファイルがない・読めないときは、代わりの絵にする
        return self._images[stage_id]

    def _card_surface(self, i):
        """カード1枚の絵 (等倍)。描くときに縮小して使う。上: イラスト / 見出し「ステージN」 / 説明"""
        if i in self._card_cache:
            return self._card_cache[i]
        stage = self.stages[i]
        surf = pygame.Surface(CARD_SIZE, pygame.SRCALPHA)
        pygame.draw.rect(surf, C("card"), surf.get_rect(), border_radius=16)
        pygame.draw.rect(surf, C("accent"), surf.get_rect(), 2, border_radius=16)
        # イラスト (assets/stages/<id>.png) か、ステージごとの色の背景にステージ番号 (色はidから決めるので、ステージが増えても変わらない)
        image = self._stage_image(stage["id"])
        if image is not None:
            pygame.draw.rect(surf, C("image_bg"), ART_BOX, border_radius=10)
            scale = min(ART_BOX.width / image.get_width(), ART_BOX.height / image.get_height())
            picture = pygame.transform.smoothscale(image, (max(1, int(image.get_width() * scale)), max(1, int(image.get_height() * scale))))
            surf.blit(picture, picture.get_rect(center=ART_BOX.center))
        else:
            pygame.draw.rect(surf, C(f"art_{sum(ord(c) for c in stage['id']) % 6 + 1}"), ART_BOX, border_radius=10)
            number = self.fonts[64].render(str(i + 1), True, C("art_text"))
            surf.blit(number, number.get_rect(center=ART_BOX.center))
        pygame.draw.rect(surf, C("image_edge"), ART_BOX, 1, border_radius=10)
        heading = self.fonts[22].render(f"ステージ{i + 1}", True, C("text"))
        surf.blit(heading, heading.get_rect(center=(CARD_SIZE[0] // 2, 128)))
        for size in DESC_SIZES:                          # 収まる一番大きい文字サイズ (最後まで収まらなければ、最小サイズで4行まで)
            lines = wrap_text(stage["description"], self.fonts[size], CARD_SIZE[0] - 40)
            if len(lines) * (size + 4) <= DESC_HEIGHT:
                break
        for j, line in enumerate(lines[:DESC_HEIGHT // (size + 4)]):
            text = self.fonts[size].render(line, True, C("card_text"))
            surf.blit(text, text.get_rect(center=(CARD_SIZE[0] // 2, DESC_TOP + (size + 4) // 2 + j * (size + 4))))
        self._card_cache[i] = surf
        return surf

    def _dot_center(self, i):
        return (CARD_CENTER[0] + int((i - (len(self.stages) - 1) / 2) * 22), 534)

    def _button(self, rect, label, enabled, active):
        if not enabled:
            fill, edge, color = C("disabled_fill"), C("disabled_edge"), C("disabled_text")      # 押せない見た目
        else:
            fill, edge, color = C("button_hover") if active else C("button"), C("accent") if active else C("button_edge"), C("text")
        pygame.draw.rect(self.screen, fill, rect, border_radius=10)
        pygame.draw.rect(self.screen, edge, rect, 2 if (enabled and active) else 1, border_radius=10)
        self._text(label, 22, center=rect.center, color=color)

    def draw(self):
        self._background()
        self._text("ゲームモード", 28, center=(500, 60))
        self._text("ステージを選んでください", 14, center=(500, 96), color=C("muted"))
        pos = self.position()
        for i, rect, scale in self._visible_cards(pos):
            card = pygame.transform.smoothscale(self._card_surface(i), rect.size)
            alpha = int(255 - 125 * min(abs(i - pos), 1.0))          # 中央が一番はっきり、隣は少し暗く
            card.set_alpha(alpha)
            self.screen.blit(card, rect)
        # 中央のカードの選択の強調 (キーボード操作中、カルーセルにフォーカスがあるとき)
        if self.stages and self.keyboard and self.focus == "stages":
            rect, _ = self._card_rect(self.index, pos)
            pygame.draw.rect(self.screen, C("focus_ring"), rect.inflate(8, 8), 1, border_radius=18)
        # 左右の矢印と、いまの位置を示す点 (●○○○)
        for name, label, direction in (("left", "◀", -1), ("right", "▶", 1)):
            rect = self.arrow_rects[name]
            enabled = self._can_go(direction)
            self._button(rect, label, enabled, enabled and (not self.keyboard) and rect.collidepoint(self.mouse))
        for i in range(len(self.stages)):
            cx, cy = self._dot_center(i)
            if i == self.index:
                pygame.draw.circle(self.screen, C("accent"), (cx, cy), 7)
            else:
                pygame.draw.circle(self.screen, C("dot_idle"), (cx, cy), 6, 2)
        back_active = (self.keyboard and self.focus == "back") or \
                      ((not self.keyboard) and self.back_rect.collidepoint(self.mouse))
        pygame.draw.rect(self.screen, C("button_hover") if back_active else C("button"), self.back_rect, border_radius=9)
        pygame.draw.rect(self.screen, C("accent") if back_active else C("button_edge"), self.back_rect, 2 if back_active else 1, border_radius=9)
        self._text("戻る", 22, center=self.back_rect.center)
        # 右上の丸い「？」ボタン (ゲームモードのあそびかた)
        hover = (not self.keyboard) and self._help_hit(self.mouse)
        pygame.draw.circle(self.screen, C("button_hover") if hover else C("button"), self.help_center, self.help_radius)
        pygame.draw.circle(self.screen, C("accent") if hover else C("button_edge"), self.help_center, self.help_radius, 2)
        self._text("？", 28, center=self.help_center)
        self._text("あそびかた", 14, center=(self.help_center[0], self.help_center[1] + 36), color=C("muted"))
        self._text("←→:切り替え / Enter:決定 / Esc:戻る", 14, center=(500, 586), color=C("muted"))
        if self.notice is not None:
            if pygame.time.get_ticks() < self.notice[1]:
                box = pygame.Rect(0, 0, 420, 90)
                box.center = (500, 300)
                pygame.draw.rect(self.screen, C("popup"), box, border_radius=12)
                pygame.draw.rect(self.screen, C("accent_bright"), box, 2, border_radius=12)
                self._text(self.notice[0], 28, center=box.center, color=C("accent_bright"))
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
