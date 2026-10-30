"""ゲームモードの結果画面 (クリア / 失敗)。

show_result_screen(result) : result は main._stage_outcome の辞書。
  "retry" (もう一度) / "back" (ステージ選択へ) / "quit" (ウィンドウを閉じた) を返す。
操作はマウスと、キーボード (←→↑↓で選んで Enter)。
"""
import pygame

from title_screen import SIZE, _font
from theme import color as C
from season_effects import season_label

SPECIES_JA = {"herbivore": "草食動物", "carnivore": "肉食動物"}
BUTTONS = (("retry", "もう一度"), ("back", "ステージ選択へ"))


def _button_rects():
    return [pygame.Rect(0, 0, 220, 52).move(500 - 230 + i * 240, 470) for i in range(len(BUTTONS))]


def _draw(screen, fonts, result, focus, mouse, keyboard, rects):
    screen.fill(C("bg"))
    for x in range(25, 1000, 55):
        for y in range(25, 600, 55):
            pygame.draw.circle(screen, C("dot"), (x, y), 1)

    def text(label, size, center, color=None):
        surf = fonts[size].render(label, True, C("text") if color is None else color)
        screen.blit(surf, surf.get_rect(center=center))

    clear = result["outcome"] == "clear"
    text("クリア！" if clear else "失敗…", 64, (500, 110), C("clear") if clear else C("fail"))
    if clear:
        text("草食動物も肉食動物も、生き残りました", 22, (500, 190))
    else:
        names = "と".join(SPECIES_JA[k] for k in result["extinct"])
        text(f"{names}が絶滅しました", 28, (500, 190), C("fail"))

    panel = pygame.Rect(0, 0, 520, 190)
    panel.center = (500, 330)
    pygame.draw.rect(screen, C("surface"), panel, border_radius=14)
    pygame.draw.rect(screen, C("button_edge"), panel, 1, border_radius=14)
    gen = result["generation"]
    label = "絶滅した世代" if not clear else "到達した世代"
    text(label, 14, (500, panel.y + 30), C("muted"))
    text(f"{gen}世代目  ({season_label(gen)})", 28, (500, panel.y + 66))
    text("最後の個体数", 14, (500, panel.y + 112), C("muted"))
    text(f"草食 {result['herbivores']} 匹", 28, (500 - 120, panel.y + 148), C("herb"))
    text(f"肉食 {result['carnivores']} 匹", 28, (500 + 120, panel.y + 148), C("carn"))

    for i, ((_, label), rect) in enumerate(zip(BUTTONS, rects)):
        active = focus == i if keyboard else rect.collidepoint(mouse)
        pygame.draw.rect(screen, C("button_hover") if active else C("button"), rect, border_radius=9)
        pygame.draw.rect(screen, C("accent") if active else C("button_edge"), rect, 2 if active else 1, border_radius=9)
        text(label, 22, rect.center)
    text("←→・Enterでも操作できます", 14, (500, 557), C("muted"))


def show_result_screen(result):
    screen = pygame.display.set_mode(SIZE)      # 遊んでいる画面とは大きさが違うので、メニューの大きさに戻す
    pygame.display.set_caption("ECOSYSTEM — 生態系シミュレーションゲーム")
    fonts = {size: _font(size) for size in (14, 22, 28, 64)}
    rects = _button_rects()
    clock = pygame.time.Clock()
    focus, keyboard, mouse = 0, False, pygame.mouse.get_pos()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.MOUSEMOTION:
                mouse, keyboard = event.pos, False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for (key, _), rect in zip(BUTTONS, rects):
                    if rect.collidepoint(event.pos):
                        return key
            elif event.type == pygame.KEYDOWN:
                keyboard = True
                if event.key in (pygame.K_LEFT, pygame.K_UP):
                    focus = max(0, focus - 1)
                elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    focus = min(len(BUTTONS) - 1, focus + 1)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    return BUTTONS[focus][0]
                elif event.key == pygame.K_ESCAPE:
                    return "back"
        _draw(screen, fonts, result, focus, mouse, keyboard, rects)
        pygame.display.flip()
        clock.tick(60)
