"""Pygame title/mission menus, independent of the ecosystem simulation."""
from pathlib import Path

import pygame

SIZE = (1000, 600)
BACKGROUND = (8, 19, 16)
TEXT = (234, 244, 226)
MUTED = (153, 177, 155)


def _font(size):
    # Match Japanese fonts first. The existing japanize_matplotlib dependency
    # provides a portable Japanese font when no suitable system font exists.
    path = pygame.font.match_font(
        "meiryo,msgothic,yugothic,notosanscjkjp,notosanscjk,ipagothic,takaogothic"
    )
    if path is None:
        import japanize_matplotlib
        path = str(Path(japanize_matplotlib.__file__).parent / "fonts" / "ipaexg.ttf")
    return pygame.font.Font(path, size)


class TitleScreen:
    """Owns only menu UI state; never reads or changes simulation parameters."""

    def __init__(self):
        self.screen = pygame.display.set_mode(SIZE)
        pygame.display.set_caption("ECOSYSTEM — 生態系シミュレーションゲーム")
        self.fonts = {size: _font(size) for size in (14, 18, 22, 28, 64)}
        self.page = "title"
        self.focus = 0
        self.mouse = pygame.mouse.get_pos()
        self.keyboard = False
        self.buttons = []
        self.help_center, self.help_radius = (948, 52), 22      # 右上の丸い「？」ボタン (解説画面を開く)
        self._set_buttons()

    def _set_buttons(self):
        if self.page == "title":
            labels = [("mission", "ゲームモード"),
                      ("god", "観察モード"), ("quit", "ゲーム終了")]
            self.buttons = [(key, label, pygame.Rect(320, 290 + i * 76, 360, 58))
                            for i, (key, label) in enumerate(labels)]
        else:
            self.buttons = [("back", "タイトル画面に戻る", pygame.Rect(320, 426, 360, 58))]
        self.focus = 0

    def _activate(self, key):
        if key == "back":
            self.page = "title"
            self._set_buttons()
        else:
            return key
        return None

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            return "quit"
        if event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            self.keyboard = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._help_hit(event.pos):
                return "help"
            for key, _, rect in self.buttons:
                if rect.collidepoint(event.pos):
                    return self._activate(key)
        elif event.type == pygame.KEYDOWN:
            if self.page == "title" and (event.key == pygame.K_F1 or getattr(event, "unicode", "") in ("?", "？")):
                return "help"
            if event.key == pygame.K_ESCAPE:
                return self._activate("back" if self.page == "mission" else "quit")
            if event.key in (pygame.K_UP, pygame.K_DOWN):
                self.keyboard = True
                self.focus = (self.focus + (1 if event.key == pygame.K_DOWN else -1)) % len(self.buttons)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self._activate(self.buttons[self.focus][0])
        return None

    def _help_hit(self, pos):
        if self.page != "title":
            return False
        dx, dy = pos[0] - self.help_center[0], pos[1] - self.help_center[1]
        return dx * dx + dy * dy <= self.help_radius ** 2

    def _text(self, text, size, center, color=TEXT):
        surface = self.fonts[size].render(text, True, color)
        self.screen.blit(surface, surface.get_rect(center=center))

    def draw(self):
        self.screen.fill(BACKGROUND)
        # Fixed decorative shapes avoid consuming the simulation's random state.
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
        pygame.draw.circle(self.screen, (38, 73, 48), (500, 72), 24, 1)
        pygame.draw.ellipse(self.screen, (123, 178, 99), (493, 55, 13, 24))
        pygame.draw.line(self.screen, TEXT, (500, 66), (500, 88), 1)
        if self.page == "title":
            self._text("ECOSYSTEM", 64, (500, 154))
            self._text("生態系シミュレーションゲーム", 22, (500, 216), MUTED)
            self._text("命がつながり、世界が変わる。", 14, (500, 250), MUTED)
        else:
            self._text("ECOSYSTEM", 18, (500, 132), MUTED)
            self._text("ミッションモード", 28, (500, 213))
            pygame.draw.rect(self.screen, (16, 36, 27), (280, 266, 440, 116), border_radius=14)
            self._text("準備中", 28, (500, 304), (163, 204, 131))
            self._text("新しいミッションを準備しています。", 18, (500, 348), MUTED)
        for i, (_, label, rect) in enumerate(self.buttons):
            active = self.focus == i if self.keyboard else rect.collidepoint(self.mouse)
            pygame.draw.rect(self.screen, (51, 96, 56) if active else (22, 49, 33), rect, border_radius=9)
            pygame.draw.rect(self.screen, (152, 197, 123) if active else (56, 86, 60), rect, 1, border_radius=9)
            self._text(label, 22, rect.center)
        self._text("マウスで選択  /  ↑↓・Enterでも操作できます", 14, (500, 557), MUTED)
        if self.page == "title":
            hover = self._help_hit(self.mouse)
            pygame.draw.circle(self.screen, (51, 96, 56) if hover else (22, 49, 33), self.help_center, self.help_radius)
            pygame.draw.circle(self.screen, (152, 197, 123) if hover else (56, 86, 60), self.help_center, self.help_radius, 2)
            self._text("？", 28, self.help_center)
            self._text("解説", 14, (self.help_center[0], self.help_center[1] + 36), MUTED)


def show_title_screen():
    """Return 'god' or 'quit'; caller owns launching the unchanged simulation."""
    pygame.init()
    try:
        menu = TitleScreen()
        clock = pygame.time.Clock()
        while True:
            for event in pygame.event.get():
                action = menu.handle_event(event)
                if action == "mission":                   # ゲームモード → ステージ選択画面 → 戻ったらタイトル画面のまま
                    from stage_select import show_stage_select
                    if show_stage_select() == "quit":
                        return "quit"
                    menu.mouse = pygame.mouse.get_pos()
                    break
                if action == "help":                      # 「？」→ 解説画面 → 戻ったらタイトル画面のまま
                    from help_screen import show_help_screen
                    if show_help_screen() == "quit":
                        return "quit"
                    menu.mouse = pygame.mouse.get_pos()
                    break
                if action:
                    return action
            menu.draw()
            pygame.display.flip()
            clock.tick(60)
    finally:
        pygame.quit()
