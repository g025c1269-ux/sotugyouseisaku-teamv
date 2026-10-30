"""ゲームモード専用の右パネルと、警告・ヒントの判定。

警告のしきい値は data/game_rules.json ("warnings")、ヒントの文章は data/hints.json にある。
上から: ステージ名・世代 / MPゲージ / スキルカード / 速度ボタン / 全体のステータス / リーフのヒント。
"""
import json
import math
from pathlib import Path

import numpy as np
import pygame

import config
from theme import color as C
from help_screen import wrap_text
from season_effects import season_label, season_of
from skill_art import draw_skill_art

DATA_DIR = Path(__file__).resolve().parent / "data"
SPECIES = (("herbivore", "草食", "herb"), ("carnivore", "肉食", "carn"))     # 3つめは theme の色の名前
CARD_Y, CARD_H = 108, 140          # スキルカードの位置と高さ (上: イラスト 96x72 / 名前 / MPとキー / 不足分)
NOTE_Y, SPECIES_Y, SPEED_Y = 256, 276, 304   # カードの下: 説明の行 / 補充する種のボタン / 速度ボタンのy


def _lighten(c, t):
    return tuple(round(v + (255 - v) * t) for v in c)


def load_hints(path=DATA_DIR / "hints.json"):
    """ステージidごとのヒントのリスト {"default": [...], "famine": [...]}。読めなければ空。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, list)}
    except Exception:
        return {}


def compute_warnings(world, rules):
    """種ごとの警告。{"herbivore": {count, decline, danger, mean_temp, temp_gap}, "carnivore": {...}}"""
    w = rules["warnings"]
    result = {}
    for species, _, _ in SPECIES:
        orgs = [o for o in world.organisms if o.org_type == species]
        recent = world.history[f"{species}_count"][-int(w["decline_generations"]):]
        decline = bool(recent) and len(orgs) <= max(recent) * float(w["decline_ratio"])
        danger = species == "carnivore" and len(orgs) <= int(w["carnivore_danger_count"])
        mean_temp = float(np.mean([o.genes["cold_resistance"] for o in orgs])) * 40.0 if orgs else None
        gap = mean_temp is not None and abs(mean_temp - config.TEMPERATURE) >= float(w["temp_gap"])
        result[species] = {"count": len(orgs), "decline": decline, "danger": danger,
                           "mean_temp": mean_temp, "temp_gap": gap}
    return result


def pick_hint(warnings, generation, hints, stage_id=None):
    """優先順位: 肉食が危険 > 個体数の減少 > 気温のずれ > 進み具合 > 季節。1つだけ返す。
    ヒントは、そのステージのidのリストを先に見て、条件に合うものがなければ "default" から選ぶ (idが無ければ default だけ)。"""
    lists = [hints.get(stage_id, [])] if stage_id != "default" else []
    lists.append(hints.get("default", []))
    carn, herb = warnings["carnivore"], warnings["herbivore"]
    for condition, active in (("carn_danger", carn["danger"]), ("carn_decline", carn["decline"]),
                              ("herb_decline", herb["decline"]),
                              ("temp_gap", carn["temp_gap"] or herb["temp_gap"])):
        if active:
            for lst in lists:
                for h in lst:
                    if h["condition"] == condition:
                        return h["text"]
    season = season_of(generation) if config.SEASONS_ENABLED else None
    for progress in (True, False):                 # 進み具合の一言 (最初の6世代・18世代以降) を、季節の一言より先に探す
        for lst in lists:                          # どちらも、そのステージのリストを先に、なければ default から
            pool = [h for h in lst if h["condition"] == "normal"
                    and h.get("season") in (None, season)
                    and generation >= h.get("min_generation", 0) and generation <= h.get("max_generation", 10 ** 9)
                    and (("min_generation" in h or "max_generation" in h) == progress)]
            if pool:
                return pool[generation % len(pool)]["text"]
    return ""


class GamePanel:
    def __init__(self, rect, skills, rules, hints, fonts, leaf, speed_draw):
        """fonts=(font, big_font, small_font)。leaf=リーフの絵と吹き出しを描く NavigatorPanel (既存のものを流用)。
        speed_draw(x, y, width) → (次のy, {速度名: Rect}) は、既存の速度ボタンの描画。"""
        self.rect, self.skills, self.rules, self.hints = rect, skills, rules, hints
        self.font, self.big_font, self.small_font = fonts
        self.leaf, self.speed_draw = leaf, speed_draw
        m = 14
        self.x, self.w = rect.x + m, rect.width - 2 * m
        card_w = (self.w - 16) // 3
        self.card_rects = {s["id"]: pygame.Rect(self.x + i * (card_w + 8), CARD_Y, card_w, CARD_H)
                           for i, s in enumerate(skills)}
        self.species_rects = {"herbivore": pygame.Rect(rect.right - m - 150, SPECIES_Y - 2, 70, 22),
                              "carnivore": pygame.Rect(rect.right - m - 72, SPECIES_Y - 2, 70, 22)}
        self.menu_rect = pygame.Rect(rect.right - m - 64, 12, 64, 28)
        self.speed_rects = {}

    # ---------- 部品 ----------
    def _text(self, screen, text, font, color, pos, right=False):
        surf = font.render(text, True, color)
        screen.blit(surf, (pos[0] - surf.get_width(), pos[1]) if right else pos)
        return surf.get_width()

    def _warn_pill(self, screen, text, x, y, danger=False):
        """個体数の警告 (▼ 減っている / ⚠ 危険)。印と文字は警告色。危険は大きく、点滅する。"""
        font = self.font if danger else self.small_font
        on = (not danger) or (pygame.time.get_ticks() // 500) % 2 == 0      # 危険は 0.5秒ごとに塗りと枠が入れ替わる
        surf = font.render(text, True, C("warn_ink") if (danger and on) else C("warn"))
        mark = 20 if danger else 12
        r = pygame.Rect(x, y - (3 if danger else 0), mark + surf.get_width() + 14, surf.get_height() + (8 if danger else 4))
        pygame.draw.rect(screen, C("warn") if (danger and on) else C("warn_pill_bg"), r, border_radius=5)
        pygame.draw.rect(screen, C("warn"), r, 3 if danger else 1, border_radius=5)
        c = C("warn_ink") if (danger and on) else C("warn")
        cx, cy, h = r.x + 6 + mark // 2, r.centery, mark // 2 - (1 if danger else 2)
        if danger:     # ⚠ (上向きの三角の中に !)
            pygame.draw.polygon(screen, c, [(cx, cy - h), (cx - h - 1, cy + h), (cx + h + 1, cy + h)], 2)
            pygame.draw.line(screen, c, (cx, cy - h + 5), (cx, cy + 1), 2)
            pygame.draw.rect(screen, c, (cx - 1, cy + 4, 2, 2))
        else:          # ▼
            pygame.draw.polygon(screen, c, [(cx - h, cy - h // 2), (cx + h, cy - h // 2), (cx, cy + h)])
        screen.blit(surf, (r.x + mark + 9, r.y + (r.height - surf.get_height()) // 2))
        return r.width + 6

    def _badge(self, screen, text, color, x, y):
        surf = self.small_font.render(text, True, C("badge_ink"))
        r = pygame.Rect(x, y, surf.get_width() + 10, surf.get_height() + 4)
        pygame.draw.rect(screen, color, r, border_radius=4)
        screen.blit(surf, (x + 5, y + 2))
        return r.width + 6

    def _leaf_card(self, screen, y, height, title, text, color):
        """リーフのヒント。吹き出しはテーマの色で自前で描き、リーフの絵だけ既存の描画 (NavigatorPanel._mascot) を使う。"""
        leaf = self.leaf
        x = self.rect.x
        screen.blit(leaf.font.render(title, True, color), (x + 12, y))
        leaf._mascot(screen, (x + 25, y + 53), color)
        bubble = pygame.Rect(x + 47, y + 24, self.rect.width - 59, height - 26)
        pygame.draw.polygon(screen, C("bubble_fill"), [(bubble.left, y + 43), (bubble.left - 9, y + 50), (bubble.left, y + 57)])
        pygame.draw.rect(screen, C("bubble_fill"), bubble, border_radius=10)
        pygame.draw.rect(screen, C("bubble_edge"), bubble, 1, border_radius=10)
        font = leaf.font
        lines = wrap_text(text, font, bubble.width - 20)
        if len(lines) * (font.get_height() + 4) > bubble.height - 18:      # 入りきらないときは小さい文字にする
            font = leaf.small
            lines = wrap_text(text, font, bubble.width - 20)
        line_height = font.get_height() + 4
        for i, line in enumerate(lines):
            screen.blit(font.render(line, True, C("bubble_text")), (bubble.x + 10, bubble.y + 9 + i * line_height))

    # ---------- 描画 ----------
    def draw(self, screen, world, stage, game, clear_generations, paused, speed_level, selection, species):
        warnings = compute_warnings(world, self.rules)
        pygame.draw.rect(screen, C("gp_bg"), self.rect)
        x, y = self.x, 8
        # 1. ステージ名・世代
        self._text(screen, stage["name"], self.big_font, C("accent_bright"), (x, y))
        for r, label in ((self.menu_rect, "メニュー"),):
            pygame.draw.rect(screen, C("gp_button"), r, border_radius=4)
            pygame.draw.rect(screen, C("gp_button_edge"), r, 1, border_radius=4)
            s = self.small_font.render(label, True, C("gp_text"))
            screen.blit(s, s.get_rect(center=r.center))
        gen_label = season_label(world.generation) if config.SEASONS_ENABLED else f"{world.generation}ヶ月目"
        remain = "" if clear_generations is None else f"    クリアまで {max(0, clear_generations - world.generation + 1)} 世代"
        self._text(screen, gen_label + remain, self.font, C("gp_text_strong"), (x, 38))
        # 2. MPゲージ
        self._text(screen, f"MP {int(game.mp)} / {int(game.mp_max)}", self.font, C("mp_text"), (x, 66))
        bar = pygame.Rect(x, 88, self.w, 12)
        pygame.draw.rect(screen, C("gp_bar_bg"), bar, border_radius=4)
        fill = bar.copy()
        fill.width = int(bar.width * game.mp / game.mp_max)
        pygame.draw.rect(screen, C("mp_bar"), fill, border_radius=4)
        # 3. スキルカード: 上にイラスト、名前、MPコストとキー。使えない(MP不足)カードは暗くして「あとMP N」を出す
        mouse = pygame.mouse.get_pos()
        for s in self.skills:
            r = self.card_rects[s["id"]]
            usable = game.can_use(s)
            chosen = selection is not None and selection["id"] == s["id"]
            hover = usable and r.collidepoint(mouse)
            pygame.draw.rect(screen, C("gp_card_off") if not usable else (_lighten(C("gp_card"), 0.15) if hover else C("gp_card")),
                             r, border_radius=6)
            box = pygame.Rect(0, 0, 96, 72)
            box.midtop = (r.centerx, r.y + 6)
            draw_skill_art(screen, box, s["id"])
            if not usable:
                veil = pygame.Surface(box.size, pygame.SRCALPHA)
                veil.fill((0, 0, 0, 120))                   # 絵を暗くする (どの配色でも)
                screen.blit(veil, box)
            pygame.draw.rect(screen, C("mp_text") if chosen else (C("gp_card_edge") if usable else C("gp_card_edge_off")),
                             r, 3 if chosen else (2 if hover else 1), border_radius=6)
            ink = C("gp_card_text") if usable else C("gp_card_text_off")
            name = self.font.render(s["name"], True, ink)
            screen.blit(name, name.get_rect(midtop=(r.centerx, box.bottom + 4)))
            screen.blit(self.font.render(f"MP {s['cost']}", True, C("mp_text") if usable else ink), (r.x + 8, box.bottom + 24))
            key = self.small_font.render(f"[{s['key']}]", True, C("gp_label") if usable else ink)
            screen.blit(key, key.get_rect(topright=(r.right - 8, box.bottom + 27)))
            if not usable:
                short = self.small_font.render(f"あとMP {math.ceil(s['cost'] - game.mp)}", True, C("ng_text"))
                screen.blit(short, short.get_rect(midtop=(r.centerx, box.bottom + 46)))
        # 選択中の説明 / 一時停止の表示
        if selection is not None:
            skill = next(s for s in self.skills if s["id"] == selection["id"])
            self._text(screen, "盤面をクリックで発動  (Escで取り消し)", self.small_font, C("mp_text"), (x, NOTE_Y))
            if skill["id"] == "spawn":
                self._text(screen, "補充する種:  Tabで切替", self.small_font, C("gp_dim"), (x, SPECIES_Y))
                for key, label, color in SPECIES:
                    color = C(color)
                    r = self.species_rects[key]
                    on = species == key
                    pygame.draw.rect(screen, C("button_hover") if on else C("gp_button"), r, border_radius=4)
                    pygame.draw.rect(screen, C("accent_bright") if on else C("gp_button_edge"), r, 2 if on else 1, border_radius=4)
                    s = self.small_font.render(label, True, color if on else C("gp_dim"))
                    screen.blit(s, s.get_rect(center=r.center))
        else:
            note = "[一時停止中]  Spaceで再開" if paused else "Z/X/C:スキル  Space:一時停止  Esc:メニュー"
            self._text(screen, note, self.small_font, C("temp") if paused else C("gp_faint"), (x, NOTE_Y))
        # 速度ボタン
        y, self.speed_rects = self.speed_draw(x, SPEED_Y, self.w)
        # 4. 全体のステータス
        y += 6
        self._text(screen, "いまの世界", self.font, C("gp_label"), (x, y))
        self._text(screen, f"気温: {config.TEMPERATURE:.1f}°C", self.font, C("temp"), (x + self.w, y), right=True)
        y += 26
        for key, label, color in SPECIES:
            color = C(color)
            info = warnings[key]
            w = self._text(screen, f"{label}動物: {info['count']} 匹", self.font, color, (x, y))   # 数字は種の色のまま
            bx = x + w + 10
            if info["decline"]:
                bx += self._warn_pill(screen, "減っている", bx, y)
            if info["danger"]:
                bx += self._warn_pill(screen, "危険", bx, y, danger=True)
            y += 22
            t = info["mean_temp"]
            text = "平均の適正気温: -" if t is None else f"平均の適正気温: {t:.1f}°C"
            w = self._text(screen, text, self.small_font, C("temp") if info["temp_gap"] else C("gp_soft"), (x + 12, y + 2))
            if info["temp_gap"]:
                self._badge(screen, "気温に合っていない", C("temp"), x + 12 + w + 10, y)
            y += 26
        # 5. リーフのヒント
        y += 4
        self._leaf_card(screen, y, self.rect.bottom - y - 6, "リーフのヒント",
                        pick_hint(warnings, world.generation, self.hints, stage["id"]), C("leaf_title"))
        return warnings
