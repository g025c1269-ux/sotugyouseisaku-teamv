"""スキルのイラスト。解説画面 (help_screen.py) とゲーム内のスキルカード (game_panel.py) が、同じ関数で描く。

draw_skill_art(surface, rect, skill_id): rect (絵の枠) にスキルの絵を描く。
  assets/skills/<id>.png (food.png / spawn.png / adapt.png) があれば、それを縦横比を保って枠に収めて出す。
    推奨サイズ: 4:3 の PNG、480x360 px (背景は透明か、余白を少なめに)。小さくても 192x144 px 以上。
    枠の大きさは、ゲーム内のカードで 96x72 px、解説画面のカードで 最大 152x114 px (どちらも 4:3)。
  なければ、ステージ選択の代わりの絵と同じ「色の背景」に、図形の絵を描く (色は theme から読む)。
    food=木の実 (pixel_art.BERRY を拡大) / spawn=草食と肉食のドット絵 / adapt=温度計と矢印
"""
from pathlib import Path

import pygame

from pixel_art import BERRY, BERRY_PALETTE, SPRITE, compose_pixels
from theme import color as C

SKILL_IMAGE_DIR = Path(__file__).resolve().parent / "assets" / "skills"
_images = {}          # スキルのid → 読み込んだ絵 (なければ None)
_sprites = {}         # (種類, 倍率) → ドット絵


def _png(skill_id):
    if skill_id not in _images:
        try:
            _images[skill_id] = pygame.image.load(str(SKILL_IMAGE_DIR / f"{skill_id}.png")).convert_alpha()
        except Exception:
            _images[skill_id] = None          # ファイルがない・読めないときは、代わりの絵にする
    return _images[skill_id]


def reload_images():
    """読み込み済みの絵を忘れる (assets/skills/ の中身を差し替えたあと用)。"""
    _images.clear()


def _pixel_surface(key, rows_or_pixels, scale):
    """ドット絵 (文字の並び+パレット、または色の並び) を、整数倍に拡大した Surface にする。"""
    cache_key = (key, scale)
    if cache_key not in _sprites:
        if key == "berry":
            rows = rows_or_pixels
            base = pygame.Surface((len(rows[0]), len(rows)), pygame.SRCALPHA)
            for y, row in enumerate(rows):
                for x, ch in enumerate(row):
                    if BERRY_PALETTE.get(ch) is not None:
                        base.set_at((x, y), BERRY_PALETTE[ch] + (255,))
        else:
            base = pygame.Surface((SPRITE, SPRITE), pygame.SRCALPHA)
            for y, row in enumerate(rows_or_pixels):
                for x, c in enumerate(row):
                    if c is not None:
                        base.set_at((x, y), c + (255,))
        _sprites[cache_key] = pygame.transform.scale(base, (base.get_width() * scale, base.get_height() * scale))
    return _sprites[cache_key]


def _animal(kind, scale):
    genes = {"cold_resistance": 0.5, "metabolism": 0.5, "mountain_tolerance": 0.8, "river_tolerance": 0.0, "speed": 0.5}
    return _pixel_surface(kind, compose_pixels(kind, 0, genes), scale)


def _draw_food(surface, rect):
    scale = max(1, int(min(rect.height * 0.78, rect.width * 0.6)) // len(BERRY))
    berry = _pixel_surface("berry", BERRY, scale)
    surface.blit(berry, berry.get_rect(center=rect.center))


def _draw_spawn(surface, rect):
    scale = max(1, int(min(rect.height * 0.7, rect.width * 0.4)) // SPRITE)
    herb, carn = _animal("herbivore", scale), _animal("carnivore", scale)
    gap = max(2, rect.width // 14)
    x = rect.centerx - (herb.get_width() + gap + carn.get_width()) // 2
    surface.blit(herb, herb.get_rect(midleft=(x, rect.centery)))
    surface.blit(carn, carn.get_rect(midleft=(x + herb.get_width() + gap, rect.centery)))


def _draw_adapt(surface, rect):
    """温度計 (左) と、水銀の高さに向かう矢印 (右)。"""
    ink, mercury = C("art_text"), C("carn")
    h = rect.height
    tube_w = max(6, int(h * 0.16))
    tube = pygame.Rect(0, 0, tube_w, int(h * 0.58))
    tube.midbottom = (rect.centerx - int(rect.width * 0.14), rect.centery + int(h * 0.12))
    bulb_r = int(tube_w * 0.95)
    bulb = (tube.centerx, tube.bottom + bulb_r - 2)
    pygame.draw.rect(surface, ink, tube, border_radius=tube_w // 2)
    pygame.draw.circle(surface, ink, bulb, bulb_r)
    inner = max(2, tube_w - 4)
    level = tube.y + int(tube.height * 0.38)                      # 水銀の高さ
    pygame.draw.rect(surface, mercury, (tube.centerx - inner // 2, level, inner, tube.bottom - level + 2))
    pygame.draw.circle(surface, mercury, bulb, max(2, bulb_r - 3))
    for k in range(4):                                            # 目盛り
        ty = tube.y + 6 + k * (tube.height - 12) // 3
        pygame.draw.line(surface, ink, (tube.right + 3, ty), (tube.right + 3 + (7 if k % 3 == 0 else 4), ty), 2)
    # 水銀の高さへ向かう矢印 (右 → 左)
    tip = (tube.right + 18, level)
    tail = (rect.right - max(8, rect.width // 8), level)
    pygame.draw.line(surface, ink, (tip[0] + 6, level), tail, max(2, h // 22))
    pygame.draw.polygon(surface, ink, [tip, (tip[0] + 10, level - 7), (tip[0] + 10, level + 7)])


def _draw_generic(surface, rect):
    pygame.draw.circle(surface, C("art_text"), rect.center, int(min(rect.size) * 0.28), max(2, rect.height // 24))


SHAPES = {"food": _draw_food, "spawn": _draw_spawn, "adapt": _draw_adapt}


def draw_skill_art(surface, rect, skill_id, radius=8):
    """rect の中に、スキルの絵 (画像か、代わりの図形の絵) と枠線を描く。"""
    image = _png(skill_id)
    if image is not None:
        pygame.draw.rect(surface, C("image_bg"), rect, border_radius=radius)
        scale = min(rect.width / image.get_width(), rect.height / image.get_height())
        picture = pygame.transform.smoothscale(image, (max(1, int(image.get_width() * scale)), max(1, int(image.get_height() * scale))))
        surface.blit(picture, picture.get_rect(center=rect.center))
    else:
        pygame.draw.rect(surface, C(f"art_{sum(ord(c) for c in skill_id) % 6 + 1}"), rect, border_radius=radius)
        old = surface.get_clip()
        surface.set_clip(rect)
        SHAPES.get(skill_id, _draw_generic)(surface, rect)
        surface.set_clip(old)
    pygame.draw.rect(surface, C("image_edge"), rect, 1, border_radius=radius)
