"""Scrollable numeric status inspector; no individual commentary is generated."""
from pathlib import Path

import pygame

from status_explainer import StatusExplainer


class StatusPanel:
    def __init__(self, rect):
        self.rect = pygame.Rect(rect)
        self.explainer = StatusExplainer()
        self.font = self._font(16)
        self.heading = self._font(20)
        self.selected = None
        self.open = False
        self.scroll = 0
        self.lines = []
        self.signature = None
        self.content_height = 0
        self.close_rect = pygame.Rect(self.rect.right - 76, 10, 64, 30)
        self.body = pygame.Rect(self.rect.x + 16, 92, self.rect.width - 36, self.rect.height - 120)

    @staticmethod
    def _font(size):
        path = pygame.font.match_font("meiryo,msgothic,yugothic,notosanscjkjp,notosanscjk,ipagothic")
        if path is None:
            import japanize_matplotlib
            path = str(Path(japanize_matplotlib.__file__).parent / "fonts" / "ipaexg.ttf")
        return pygame.font.Font(path, size)

    def _sync_selection(self, org):
        if org is not self.selected:
            self.selected = org
            self.open = org is not None
            self.scroll = 0
            self.signature = None

    def handle_event(self, event, org):
        self._sync_selection(org)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_n and org is not None:
            self.open = not self.open
            return True
        if not self.open:
            return False
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll = max(0, min(self.max_scroll, self.scroll - event.y * 60))
            return True
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            if self.rect.collidepoint(event.pos):
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.close_rect.collidepoint(event.pos):
                    self.open = False
                return True
        return False

    @property
    def max_scroll(self):
        return max(0, self.content_height - self.body.height)

    def _wrap(self, text):
        lines, current = [], ""
        for char in text:
            if char == '\n':
                lines.append(current)
                current = ""
            elif current and self.font.size(current + char)[0] > self.body.width:
                lines.append(current)
                current = char
            else:
                current += char
        if current:
            lines.append(current)
        return lines

    def _refresh(self, org, world):
        import config
        signature = (tuple(sorted(org.genes.items())), org.energy, org.max_energy,
                     org.age, org.alive, org.x, org.y, world.get_zone(org.x, org.y),
                     config.TEMPERATURE, config.HERBIVORE_BASE_ENERGY_COST,
                     config.CARNIVORE_BASE_ENERGY_COST, config.HERBIVORE_TEMP_PENALTY_COEF,
                     config.CARNIVORE_TEMP_PENALTY_COEF, config.DESERT_TEMP_PENALTY_MULTIPLIER,
                     config.HERBIVORE_MOVE_ENERGY_COST, config.CARNIVORE_MOVE_ENERGY_COST,
                     config.USE_NEUROEVOLUTION, config.MAX_AGE, config.MIN_REPRODUCE_AGE,
                     org.org_type, sum(o.alive and o.org_type == 'herbivore' for o in world.organisms),
                     sum(o.alive and o.org_type == 'carnivore' for o in world.organisms))
        if signature == self.signature:
            return
        import math
        if not math.isfinite(org.energy) or not math.isfinite(org.max_energy) or org.max_energy <= 0:
            raise ValueError('Invalid energy/capacity')
        ratio = max(0., min(1., org.energy / org.max_energy))
        mode = self.explainer.current_mode()
        zones = {'grassland':'草原', 'river':'川', 'mountain':'山', 'desert':'砂漠', 'sea':'海'}
        zone = world.get_zone(org.x, org.y)
        paragraphs = [f"種類：{self.explainer.data['species'][org.org_type]} / {'生存' if org.alive else '死亡'}",
                      f"エネルギー：{org.energy:.3f} / {org.max_energy:.3f}",
                      f"行動数：{org.age} / {config.MAX_AGE}",
                      f"行動方式：{self.explainer.modes[mode]}",
                      f"現在地：{zones.get(zone, zone)} ({org.x}, {org.y})",
                      '【現在の能力・評価】']
        for stat in self.explainer.stats:
            key = stat['key']
            value = float(org.genes[key]) if stat['source'] == 'gene' else ratio
            level = self.explainer.classify(key, value)
            paragraphs.extend([stat['label'], f"  {value:.6f} [{level}]"
                               + (' ※現在の方式では未使用' if mode in stat.get('inactive_in', []) else '')])
        base = (config.HERBIVORE_BASE_ENERGY_COST if org.org_type == 'herbivore'
                else config.CARNIVORE_BASE_ENERGY_COST) * (0.5 + org.genes['metabolism'])
        paragraphs += ['LOW＝低い / MID＝普通 / HIGH＝高い', '【現在の消費値】',
                       f"基本：{base:.3f} / 温度：{org._calc_temp_penalty(world):.3f}",
                       f"移動1マス：{org._move_energy_cost(world):.3f}"]
        paragraphs += [f"気温：{config.TEMPERATURE:.1f}℃ / 適温：{org.genes['cold_resistance'] * 40:.1f}℃",
                       f"繁殖最低行動数：{config.MIN_REPRODUCE_AGE}"]
        if config.USE_NEUROEVOLUTION:
            count = sum(p.size for p in org.brain.params()) if org.brain is not None else 0
            paragraphs.append(f"NNパラメータ数：{count}")
            if org.org_type == 'carnivore':
                from organism import CARN_HERB_RATIO_LIMIT
                herbs = sum(o.alive and o.org_type == 'herbivore' for o in world.organisms)
                carns = sum(o.alive and o.org_type == 'carnivore' for o in world.organisms)
                ratio_text = f"{carns / herbs:.3f}" if herbs else '∞'
                paragraphs.append(f"肉食/草食比：{ratio_text} / 閾値：{CARN_HERB_RATIO_LIMIT}")
        unknown = sorted(set(org.genes) - {s['key'] for s in self.explainer.stats if s['source'] == 'gene'})
        if unknown:
            paragraphs.append('未分類：' + '、'.join(unknown))
        self.lines = []
        for paragraph in paragraphs:
            color = (155, 211, 144) if paragraph.startswith('【') else (225, 233, 227)
            self.lines.extend((line, color) for line in self._wrap(paragraph))
            if paragraph.startswith('【'):
                self.lines.append(('', color))
        self.content_height = len(self.lines) * 23
        self.scroll = min(self.scroll, self.max_scroll)
        self.signature = signature

    def draw(self, screen, org, world):
        if org is not None and (not org.alive or org not in world.organisms):
            org = None
        self._sync_selection(org)
        if not self.open or org is None:
            return
        try:
            self._refresh(org, world)
        except (ValueError, KeyError) as error:
            # Invalid new data should remain visible as an error, not crash the game.
            self.lines = [(s, (255, 180, 140)) for s in self._wrap(f'評価できないデータです：{error}')]
            self.content_height = len(self.lines) * 23
            self.scroll = 0
        pygame.draw.rect(screen, (13, 28, 22), self.rect)
        screen.blit(self.heading.render('生物のステータス', True, (235, 245, 230)), (self.rect.x + 16, 18))
        pygame.draw.rect(screen, (43, 73, 53), self.close_rect, border_radius=5)
        screen.blit(self.font.render('閉じる', True, (240, 245, 235)), (self.close_rect.x + 8, self.close_rect.y + 5))
        screen.blit(self.font.render('N：表示切替 / ホイール：スクロール', True, (161, 188, 167)), (self.rect.x + 16, 57))
        clip = screen.get_clip()
        screen.set_clip(self.body.clip(clip))
        for i, (line, color) in enumerate(self.lines):
            y = self.body.y + i * 23 - self.scroll
            if y + 23 > self.body.top and y < self.body.bottom:
                screen.blit(self.font.render(line, True, color), (self.body.x, y))
        screen.set_clip(clip)
        if self.max_scroll:
            rail = pygame.Rect(self.rect.right - 10, self.body.top, 4, self.body.height)
            pygame.draw.rect(screen, (44, 68, 51), rail)
            height = max(24, int(self.body.height ** 2 / self.content_height))
            top = rail.y + int((self.body.height - height) * self.scroll / self.max_scroll)
            pygame.draw.rect(screen, (144, 185, 137), (rail.x, top, 4, height))
