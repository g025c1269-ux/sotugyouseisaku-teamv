"""タイトル画面の「？」から開く解説画面 (左: 項目の一覧 / 右: 選んだ項目の説明)。
説明の文章は data/help_text.json (ゲームモードは data/game_help_text.json) にあり、コードには書かない。

項目の種類(JSONの "kind"): 省略または "text" = 文章 / "skill_cards" = スキルカード(data/skills.json の定義を横に並べる)。"""
import json
from pathlib import Path

import pygame

from title_screen import SIZE, BACKGROUND, TEXT, MUTED, _font

PROJECT_DIR = Path(__file__).resolve().parent
DATA_PATH = PROJECT_DIR / "data" / "help_text.json"
ACCENT = (152, 197, 123)
BODY_SIZES = (22, 20, 18, 16, 14)          # 収まる一番大きい文字サイズを使う
NO_LINE_START = "。、，．）」』！？!?)"       # 行頭に来ないようにする文字

# ---- スキルカード ----
COST_LABELS = {1: "軽い", 2: "普通", 3: "重い"}
COST_COLORS = {1: (140, 210, 130), 2: (240, 205, 90), 3: (238, 120, 105)}
# 絵がないスキルの代わりの絵の背景色 (スキルのidから決めるので、スキルが増えても色は変わらない)
PLACEHOLDER_COLORS = [(86, 140, 110), (120, 110, 170), (176, 120, 84), (84, 130, 176), (160, 100, 130), (110, 150, 80)]
# スキルの絵(skills.json の "image"): 推奨は 4:3 の PNG、480x360 px (背景は透明か、余白を少なめに)。
# カードでは、絵の枠(最大 約152x114 px)に収まるよう、縦横比を保って縮小して出す。
IMAGE_RATIO = (4, 3)
CARD_GAP, CARD_MAX_W, CARD_MIN_W = 14, 168, 112    # カードの間隔と、1枚の幅の範囲 (枚数が多いと細くし、それでも収まらなければ横スクロール)


def load_items(path=DATA_PATH):
    """[{"title": 項目名, "body": 本文}, ...] を返す。読めないときは、その旨を1項目で返す。"""
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)["items"]
        items = [{"title": str(i["title"]), "body": str(i.get("body", "")),
                  "kind": str(i.get("kind", "text")), "source": i.get("source")} for i in items]
        if items:
            return items
    except Exception:
        pass
    return [{"title": "解説", "body": "解説のデータを読み込めませんでした。"}]


def load_skills(source=None):
    """data/skills.json (プロジェクトからの相対パス) のスキル定義を読む。読めなければ空のリスト。"""
    path = PROJECT_DIR / (source or "data/skills.json")
    try:
        with open(path, encoding="utf-8") as f:
            return [{"id": str(s["id"]), "name": str(s["name"]), "description": str(s["description"]),
                     "cost_level": max(1, min(3, int(s.get("cost_level", 2)))),
                     "needs_target": bool(s.get("needs_target", False)),
                     "image": s.get("image") or None} for s in json.load(f)["skills"]]
    except Exception:
        return []


def wrap_text(text, font, width):
    """文字単位で折り返す (単語区切りのない日本語向け)。。や、などが行頭に来ないようにする。
    本文中の改行は段落の区切りとして、必ず行を改める。"""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for ch in paragraph:
            if line and font.size(line + ch)[0] > width:
                if ch in NO_LINE_START and len(line) > 1:
                    lines.append(line[:-1])
                    line = line[-1] + ch
                else:
                    lines.append(line)
                    line = ch
            else:
                line += ch
        lines.append(line)
    return lines


class HelpScreen:
    def __init__(self, path=DATA_PATH, heading="解説"):
        self.heading = heading
        self.screen = pygame.display.get_surface() or pygame.display.set_mode(SIZE)
        self.fonts = {size: _font(size) for size in (14,) + BODY_SIZES + (28, 56)}
        self.items = load_items(path)
        self.selected = 0                 # 最初は先頭の項目を選んだ状態
        self.scroll = 0
        self.mouse = pygame.mouse.get_pos()
        self.keyboard = False
        self.item_rects = [pygame.Rect(40, 104 + i * 52, 280, 46) for i in range(len(self.items))]
        self.back_rect = pygame.Rect(40, 500, 280, 48)
        self.panel = pygame.Rect(344, 104, 616, 444)
        self.text_rect = pygame.Rect(self.panel.x + 30, self.panel.y + 84, self.panel.width - 60, self.panel.height - 84 - 24)
        self.body_rect = self.text_rect                 # 説明を出す枠 (スキルカードの項目では、カードの下の枠)
        # スキルカードの状態
        self._skills_cache, self._images = {}, {}
        self.card_index, self.card_scroll = 0, 0
        self.card_area = pygame.Rect(self.text_rect.x, self.text_rect.y, self.text_rect.width, 0)
        self.desc_rect = self.text_rect
        self.card_w, self.card_max_scroll, self.card_name_rows = CARD_MAX_W, 0, 1
        self._layout_body()

    # ---------- スキルカード ----------
    def _is_cards(self):
        return self.items[self.selected].get("kind") == "skill_cards"

    def _skills(self):
        source = self.items[self.selected].get("source")
        if source not in self._skills_cache:
            self._skills_cache[source] = load_skills(source)
        return self._skills_cache[source]

    def _layout_cards(self):
        """カードの幅・高さ・並びを決める (枚数が増えたら細くし、それでも収まらなければ横スクロールにする)"""
        skills, area = self._skills(), self.text_rect
        n = len(skills)
        self.card_w = CARD_MAX_W if n <= 1 else max(CARD_MIN_W, min(CARD_MAX_W, (area.width - CARD_GAP * (n - 1)) // n))
        total = n * self.card_w + max(0, n - 1) * CARD_GAP
        self.card_total = total
        self.card_max_scroll = max(0, total - area.width)
        self.card_name_rows = max([1] + [min(2, len(wrap_text(s["name"], self.fonts[18], self.card_w - 16))) for s in skills])
        image_h = (self.card_w - 16) * IMAGE_RATIO[1] // IMAGE_RATIO[0]
        card_h = 8 + image_h + 6 + 22 * self.card_name_rows + 4 + 20 + 4 + 22 + 8
        self.card_area = pygame.Rect(area.x, area.y, area.width, card_h)
        top = self.card_area.bottom + 16
        self.desc_rect = pygame.Rect(area.x, top, area.width, max(40, area.bottom - top))
        self._ensure_card_visible()

    def _ensure_card_visible(self):
        if self.card_max_scroll > 0:
            left = self.card_index * (self.card_w + CARD_GAP)
            if left < self.card_scroll:
                self.card_scroll = left
            elif left + self.card_w > self.card_scroll + self.card_area.width:
                self.card_scroll = left + self.card_w - self.card_area.width
        self.card_scroll = max(0, min(self.card_max_scroll, self.card_scroll))

    def _card_rect(self, i):
        base = self.card_area.x + (self.card_area.width - self.card_total) // 2 if self.card_max_scroll == 0 \
            else self.card_area.x - self.card_scroll
        return pygame.Rect(base + i * (self.card_w + CARD_GAP), self.card_area.y, self.card_w, self.card_area.height)

    def _select_card(self, i):
        n = len(self._skills())
        if n:
            self.card_index = max(0, min(n - 1, i))          # 端より先には進まない
            self.scroll = 0
            self._layout_body()

    def _image(self, path):
        if path not in self._images:
            try:
                self._images[path] = pygame.image.load(str(PROJECT_DIR / path)).convert_alpha()
            except Exception:
                self._images[path] = None                    # 読めなければ、代わりの絵にする
        return self._images[path]
    # ---------- 本文の折り返し (収まる最大の文字サイズを選ぶ。それでも収まらなければスクロール) ----------
    def _layout_body(self):
        if self._is_cards():
            skills = self._skills()
            self._layout_cards()
            self.card_index = min(self.card_index, max(0, len(skills) - 1))
            body = skills[self.card_index]["description"] if skills else "スキルのデータを読み込めませんでした。"
            self.body_rect = self.desc_rect
        else:
            body = self.items[self.selected]["body"]
            self.body_rect = self.text_rect
        for size in BODY_SIZES:
            font = self.fonts[size]
            lines = wrap_text(body, font, self.body_rect.width)
            line_h = font.get_linesize() + 8
            if len(lines) * line_h <= self.body_rect.height:
                break
        self.body_font, self.body_lines, self.line_h = font, lines, line_h
        self.max_scroll = max(0, len(lines) * line_h - self.body_rect.height)
        self.scroll = min(self.scroll, self.max_scroll)

    def _select(self, index):
        self.selected = index % len(self.items)
        self.scroll = 0
        self.card_index, self.card_scroll = 0, 0     # スキルカードの項目は、先頭のカードを選んだ状態から
        self._layout_body()

    # ---------- 入力 ----------
    def handle_event(self, event):
        """"back" / "quit" / None を返す"""
        if event.type == pygame.QUIT:
            return "quit"
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            self.keyboard = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.keyboard = False
            if self.back_rect.collidepoint(event.pos):
                return "back"
            for i, rect in enumerate(self.item_rects):
                if rect.collidepoint(event.pos):
                    self._select(i)
            if self._is_cards() and self.card_area.collidepoint(event.pos):
                for i in range(len(self._skills())):
                    if self._card_rect(i).collidepoint(event.pos):
                        self._select_card(i)
        elif event.type == pygame.MOUSEWHEEL:
            if self._is_cards() and self.card_max_scroll > 0 and self.card_area.collidepoint(self.mouse):
                self.card_scroll = max(0, min(self.card_max_scroll, self.card_scroll - event.y * 40))
            else:
                self.scroll = max(0, min(self.max_scroll, self.scroll - event.y * 40))
        elif event.type == pygame.KEYDOWN:
            self.keyboard = True
            if event.key == pygame.K_ESCAPE:
                return "back"
            if event.key == pygame.K_UP:
                self._select(self.selected - 1)
            elif event.key == pygame.K_DOWN:
                self._select(self.selected + 1)
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT) and self._is_cards():
                self._select_card(self.card_index + (1 if event.key == pygame.K_RIGHT else -1))
            elif event.key == pygame.K_PAGEUP:
                self.scroll = max(0, self.scroll - self.body_rect.height // 2)
            elif event.key == pygame.K_PAGEDOWN:
                self.scroll = min(self.max_scroll, self.scroll + self.body_rect.height // 2)
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

    def draw(self):
        self._background()
        self._text(self.heading, 28, center=(500, 50))
        self._text("知りたい項目を選んでください", 14, center=(500, 80), color=MUTED)
        for i, (item, rect) in enumerate(zip(self.items, self.item_rects)):
            selected = i == self.selected
            hovered = (not self.keyboard) and rect.collidepoint(self.mouse)
            pygame.draw.rect(self.screen, (51, 96, 56) if selected or hovered else (22, 49, 33), rect, border_radius=9)
            pygame.draw.rect(self.screen, ACCENT if selected else (56, 86, 60), rect, 2 if selected else 1, border_radius=9)
            self._text(item["title"], 20, center=rect.center)
        hovered = (not self.keyboard) and self.back_rect.collidepoint(self.mouse)
        pygame.draw.rect(self.screen, (51, 96, 56) if hovered else (22, 49, 33), self.back_rect, border_radius=9)
        pygame.draw.rect(self.screen, (56, 86, 60), self.back_rect, 1, border_radius=9)
        self._text("戻る", 22, center=self.back_rect.center)

        pygame.draw.rect(self.screen, (16, 36, 27), self.panel, border_radius=14)
        pygame.draw.rect(self.screen, (44, 76, 52), self.panel, 1, border_radius=14)
        self._text(self.items[self.selected]["title"], 28, topleft=(self.panel.x + 30, self.panel.y + 24), color=(163, 204, 131))
        if self._is_cards():
            self._text(self.items[self.selected]["body"], 14, topleft=(self.panel.x + 30, self.panel.y + 60), color=MUTED)
            self._draw_cards()
        old_clip = self.screen.get_clip()
        self.screen.set_clip(self.body_rect)
        y = self.body_rect.y - self.scroll
        for line in self.body_lines:
            if y + self.line_h >= self.body_rect.y and y <= self.body_rect.bottom:
                surf = self.body_font.render(line, True, TEXT)
                self.screen.blit(surf, (self.body_rect.x, y))
            y += self.line_h
        self.screen.set_clip(old_clip)
        if self.max_scroll > 0:
            self._text("ホイール / PageUp・PageDown でスクロール", 14,
                       center=(self.panel.centerx, self.panel.bottom - 12), color=MUTED)
        self._text("↑↓:項目 / ←→:カード / Esc:戻る" if self._is_cards() else "↑↓:項目 / Esc:戻る", 14, center=(500, 580), color=MUTED)

    def _draw_cards(self):
        skills = self._skills()
        old_clip = self.screen.get_clip()
        self.screen.set_clip(self.card_area)
        for i, skill in enumerate(skills):
            rect = self._card_rect(i)
            if not rect.colliderect(self.card_area):
                continue
            selected = i == self.card_index
            hovered = (not self.keyboard) and rect.collidepoint(self.mouse) and self.card_area.collidepoint(self.mouse)
            pygame.draw.rect(self.screen, (51, 96, 56) if selected else ((38, 78, 48) if hovered else (24, 52, 36)), rect, border_radius=12)
            pygame.draw.rect(self.screen, ACCENT if selected else (56, 86, 60), rect, 3 if selected else 1, border_radius=12)
            # 絵の枠 (image があれば絵、なければスキルごとの色の背景に頭文字)
            box = pygame.Rect(rect.x + 8, rect.y + 8, rect.width - 16, (rect.width - 16) * IMAGE_RATIO[1] // IMAGE_RATIO[0])
            image = self._image(skill["image"]) if skill["image"] else None
            if image is not None:
                scale = min(box.width / image.get_width(), box.height / image.get_height())
                size = (max(1, int(image.get_width() * scale)), max(1, int(image.get_height() * scale)))
                picture = pygame.transform.smoothscale(image, size)
                pygame.draw.rect(self.screen, (14, 30, 22), box, border_radius=8)
                self.screen.blit(picture, picture.get_rect(center=box.center))
            else:
                color = PLACEHOLDER_COLORS[sum(ord(c) for c in skill["id"]) % len(PLACEHOLDER_COLORS)]
                pygame.draw.rect(self.screen, color, box, border_radius=8)
                initial = self.fonts[56].render(skill["name"][:1], True, (250, 250, 240))
                self.screen.blit(initial, initial.get_rect(center=box.center))
            pygame.draw.rect(self.screen, (10, 24, 17), box, 1, border_radius=8)
            y = box.bottom + 6
            for line in wrap_text(skill["name"], self.fonts[18], rect.width - 16)[:2]:
                self._text(line, 18, center=(rect.centerx, y + 11))
                y += 22
            y = box.bottom + 6 + 22 * self.card_name_rows + 4
            level = skill["cost_level"]
            self._text(f"コスト: {COST_LABELS[level]}", 14, center=(rect.centerx, y + 10), color=COST_COLORS[level])
            tag = pygame.Rect(0, 0, rect.width - 24, 22)
            tag.midbottom = (rect.centerx, rect.bottom - 8)
            pygame.draw.rect(self.screen, (52, 86, 128) if skill["needs_target"] else (108, 88, 48), tag, border_radius=11)
            self._text("場所を選ぶ" if skill["needs_target"] else "すぐ使う", 14, center=tag.center)
        self.screen.set_clip(old_clip)
        if self.card_max_scroll > 0:
            self._text("◀ ホイール / ←→ で横にスクロール ▶", 14,
                       center=(self.card_area.centerx, self.card_area.bottom + 6), color=MUTED)


def show_help_screen(path=DATA_PATH, heading="解説"):
    """解説画面を開く。"back"(タイトル画面へ戻る) または "quit"(ウィンドウを閉じた) を返す。
    pygameの初期化と画面は、呼び出し元(タイトル画面)のものをそのまま使う。"""
    screen = HelpScreen(path, heading)
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            result = screen.handle_event(event)
            if result:
                return result
        screen.draw()
        pygame.display.flip()
        clock.tick(60)
