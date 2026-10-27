"""タイトル画面の「？」から開く解説画面 (左: 項目の一覧 / 右: 選んだ項目の説明)。
説明の文章は data/help_text.json にあり、コードには書かない。"""
import json
from pathlib import Path

import pygame

from title_screen import SIZE, BACKGROUND, TEXT, MUTED, _font

DATA_PATH = Path(__file__).resolve().parent / "data" / "help_text.json"
ACCENT = (152, 197, 123)
BODY_SIZES = (22, 20, 18, 16, 14)          # 収まる一番大きい文字サイズを使う
NO_LINE_START = "。、，．）」』！？!?)"       # 行頭に来ないようにする文字


def load_items(path=DATA_PATH):
    """[{"title": 項目名, "body": 本文}, ...] を返す。読めないときは、その旨を1項目で返す。"""
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)["items"]
        items = [{"title": str(i["title"]), "body": str(i["body"])} for i in items]
        if items:
            return items
    except Exception:
        pass
    return [{"title": "解説", "body": "解説のデータを読み込めませんでした。"}]


def wrap_text(text, font, width):
    """文字単位で折り返す (単語区切りのない日本語向け)。。や、などが行頭に来ないようにする。"""
    lines, line = [], ""
    for ch in text:
        if line and font.size(line + ch)[0] > width:
            if ch in NO_LINE_START and len(line) > 1:
                lines.append(line[:-1])
                line = line[-1] + ch
            else:
                lines.append(line)
                line = ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines


class HelpScreen:
    def __init__(self):
        self.screen = pygame.display.get_surface() or pygame.display.set_mode(SIZE)
        self.fonts = {size: _font(size) for size in (14,) + BODY_SIZES + (28,)}
        self.items = load_items()
        self.selected = 0                 # 最初は先頭の項目を選んだ状態
        self.scroll = 0
        self.mouse = pygame.mouse.get_pos()
        self.keyboard = False
        self.item_rects = [pygame.Rect(40, 104 + i * 52, 280, 46) for i in range(len(self.items))]
        self.back_rect = pygame.Rect(40, 500, 280, 48)
        self.panel = pygame.Rect(344, 104, 616, 444)
        self.body_rect = pygame.Rect(self.panel.x + 30, self.panel.y + 84, self.panel.width - 60, self.panel.height - 84 - 24)
        self._layout_body()

    # ---------- 本文の折り返し (収まる最大の文字サイズを選ぶ。それでも収まらなければスクロール) ----------
    def _layout_body(self):
        body = self.items[self.selected]["body"]
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
        elif event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(self.max_scroll, self.scroll - event.y * 40))
        elif event.type == pygame.KEYDOWN:
            self.keyboard = True
            if event.key == pygame.K_ESCAPE:
                return "back"
            if event.key == pygame.K_UP:
                self._select(self.selected - 1)
            elif event.key == pygame.K_DOWN:
                self._select(self.selected + 1)
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
        self._text("解説", 28, center=(500, 50))
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
        self._text("↑↓:項目 / Esc:戻る", 14, center=(500, 580), color=MUTED)


def show_help_screen():
    """解説画面を開く。"back"(タイトル画面へ戻る) または "quit"(ウィンドウを閉じた) を返す。
    pygameの初期化と画面は、呼び出し元(タイトル画面)のものをそのまま使う。"""
    screen = HelpScreen()
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            result = screen.handle_event(event)
            if result:
                return result
        screen.draw()
        pygame.display.flip()
        clock.tick(60)
