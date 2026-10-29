"""Assistant overview in the existing sidebar; detailed inspector stays available."""
import pygame

from navigator_explainer import NavigatorExplainer, PROFILE_NAMES
from status_panel import StatusPanel as DetailedPanel


class NavigatorPanel:
    def __init__(self, rect, ai_enabled=False):
        self.rect = pygame.Rect(rect)
        self.explainer = NavigatorExplainer()
        self.detail = DetailedPanel(rect)
        self.font = self.detail._font(15)
        self.small = self.detail._font(13)
        self.heading = self.detail._font(20)
        self.selected = None
        self.open = False          # 観察モード開始時は元の情報パネルを表示 (「解説」ボタン/Nキーで開く)
        self.view = 'overview'
        self.close_rect = pygame.Rect(self.rect.right - 65, 12, 53, 28)
        self.detail_rect = pygame.Rect(self.rect.right - 128, 12, 56, 28)
        self.cards = {}
        self.individual = {}
        self.layouts = []
        self._world = None
        self._token = None
        self.ai = None
        if ai_enabled:
            from ai_navigator import AINavigatorView
            self.ai = AINavigatorView(self.rect)
            self.view = 'ai'
        self.ai_rect = pygame.Rect(self.rect.right - 68, 46, 56, 25)

    def _sync_selection(self, org):
        if org is not None and not org.alive:
            org = None
        if org is not self.selected:
            self.selected = org
            if self.view != 'ai':
                self.view = 'overview'
            if org is not None:
                self.open = True

    def handle_event(self, event, org, world=None):
        self._sync_selection(org)
        if world is not None and self.ai is not None:
            self.ai.controller.sync(world, org)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_n:
                self.open = not self.open
                return True
            if event.key == pygame.K_TAB and self.selected is not None:
                self.open = True
                self.view = 'overview' if self.view == 'detail' else 'detail'
                self.detail.open = True
                return True
        if not self.open:
            return False
        if self.view == 'detail':
            consumed = self.detail.handle_event(event, self.selected)
            if not self.detail.open:
                self.view = 'overview'
            return consumed
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            if self.rect.collidepoint(event.pos):
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.close_rect.collidepoint(event.pos):
                        self.open = False
                    elif self.view == 'ai' and self.detail_rect.collidepoint(event.pos):
                        self.view = 'overview'
                    elif self.ai is not None and self.ai_rect.collidepoint(event.pos):
                        self.view = 'ai'
                    elif self.view == 'ai':
                        self.ai.handle_event(event)
                    elif self.selected is not None and self.detail_rect.collidepoint(event.pos):
                        self.view = 'detail'
                        self.detail.open = True
                return True
        # A wheel over the navigator must never zoom the map behind it.
        return event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos())

    def _refresh(self, world, org):
        import config
        token = (world.step_count, config.TEMPERATURE, config.USE_NEUROEVOLUTION)
        if self._world is not world or token != self._token:
            self.cards = {species:self.explainer.population(world.organisms, species, config.TEMPERATURE)
                          for species in ('herbivore', 'carnivore')}
            self._world, self._token = world, token
        self.individual = self.explainer.individual(org, config.TEMPERATURE)

    def _wrap(self, text, font, width):
        lines, line = [], ''
        for char in text:
            if line and font.size(line + char)[0] > width:
                lines.append(line)
                line = char
            else:
                line += char
        if line:
            lines.append(line)
        return lines

    def _mascot(self, screen, center, color, radius=14):
        x, y = center
        pygame.draw.circle(screen, (15, 37, 29), (x, y + 1), radius + 2)
        pygame.draw.circle(screen, color, (x, y), radius)
        pygame.draw.ellipse(screen, (116, 187, 112), (x - 1, y - radius - 8, 12, 8))
        pygame.draw.line(screen, (63, 117, 70), (x, y - radius + 2), (x + 4, y - radius - 3), 2)
        for dx in (-5, 5):
            pygame.draw.circle(screen, (20, 48, 37), (x + dx, y - 2), 2)
        pygame.draw.arc(screen, (20, 48, 37), (x - 5, y + 1, 10, 7), 3.3, 6.1, 2)

    def _caption(self, report):
        if not report['count']:
            return '観察対象なし'
        if report['profile'] == 'terrain':
            return f"平均 川{report['means']['river_tolerance']:.2f} / 山{report['means']['mountain_tolerance']:.2f}"
        if report['profile'] == 'balanced':
            return f"バランス型 {report['balanced_fraction']:.0%}"
        key = next((k for k,v in PROFILE_NAMES.items() if report['profile'].startswith(v + '_')), 'speed')
        label = {'river_tolerance':'川', 'mountain_tolerance':'山', 'speed':'速度', 'metabolism':'代謝', 'cold_resistance':'温度適性'}[key]
        if report['profile'] in ('mixed', 'varied'):
            return f"平均 速度{report['means']['speed']:.2f} / 川{report['means']['river_tolerance']:.2f}"
        level = 'LOW' if report['profile'].endswith('_low') else 'HIGH'
        fraction = report['distribution'][key][level] / report['count']
        return f"{label} {'低め' if level == 'LOW' else '高め'}{fraction:.0%} / 平均{report['means'][key]:.2f}"

    def _card(self, screen, y, height, title, caption, text, color):
        x, w = self.rect.x, self.rect.width
        screen.blit(self.font.render(title, True, color), (x + 12, y))
        cap = self.small.render(caption, True, (160, 187, 173))
        screen.blit(cap, (self.rect.right - 12 - cap.get_width(), y + 2))
        self._mascot(screen, (x + 25, y + 53), color)
        bubble = pygame.Rect(x + 47, y + 24, w - 59, height - 26)
        pygame.draw.polygon(screen, (29, 57, 44), [(bubble.left, y + 43), (bubble.left - 9, y + 50), (bubble.left, y + 57)])
        pygame.draw.rect(screen, (29, 57, 44), bubble, border_radius=10)
        pygame.draw.rect(screen, (53, 87, 66), bubble, 1, border_radius=10)
        font = self.font
        lines = self._wrap(text, font, bubble.width - 20)
        if len(lines) * (font.get_height() + 4) > bubble.height - 18:
            font = self.small
            lines = self._wrap(text, font, bubble.width - 20)
        line_height = font.get_height() + 4
        self.layouts.append((bubble, font, lines, line_height))
        for i, line in enumerate(lines):
            screen.blit(font.render(line, True, (231, 240, 226)), (bubble.x + 10, bubble.y + 9 + i * line_height))

    def advance(self, world, step_function, *args):
        if self.ai is None:
            return step_function(world, *args)
        return self.ai.controller.advance(world, step_function, *args)

    def close(self):
        if self.ai is not None:
            self.ai.controller.close()

    def draw(self, screen, org, world):
        if org is not None and (not org.alive or org not in world.organisms):
            org = None
        self._sync_selection(org)
        if self.ai is not None:
            self.ai.controller.sync(world, org)
        if not self.open:
            return
        if self.view == 'detail' and org is not None:
            self.detail.draw(screen, org, world)
            return
        self._refresh(world, org)
        if self.view == 'ai':
            self.ai.draw(screen, self, world, org)
            return
        pygame.draw.rect(screen, (12, 29, 23), self.rect)
        self._mascot(screen, (self.rect.x + 25, 30), (173, 209, 138))
        screen.blit(self.heading.render('リーフの観察メモ', True, (232, 242, 220)), (self.rect.x + 48, 16))
        for rect, label in ((self.detail_rect, '詳細'), (self.close_rect, '閉じる')):
            enabled = label != '詳細' or org is not None
            pygame.draw.rect(screen, (42, 72, 52) if enabled else (25, 43, 34), rect, border_radius=5)
            surface = self.small.render(label, True, (225, 237, 214) if enabled else (95, 119, 105))
            screen.blit(surface, surface.get_rect(center=rect.center))
        caption = '群れと個体を観察しよう！' if self.ai is not None else '群れと個体の「いま」を見てみよう！'
        screen.blit(self.small.render(caption, True, (155, 186, 165)), (self.rect.x + 12, 51))
        if self.ai is not None:
            self.ai._button(screen, self.small, self.ai_rect, 'AI')
        self.layouts = []
        height = (self.rect.height - 120) // 3
        for i, (species, label, color) in enumerate((('herbivore','草食たち',(171, 219, 143)), ('carnivore','肉食組',(239, 190, 134)))):
            report = self.cards[species]
            self._card(screen, 78 + i * (height + 8), height,
                       f"{label} · {report['count']}匹", self._caption(report), report['text'], color)
        label = '選択中の個体' if org is not None else '気になる個体を探そう'
        caption = f"{'草食' if org.org_type == 'herbivore' else '肉食'} / 蓄え{org.energy / org.max_energy:.0%}" if org is not None else 'クリックで選択'
        self._card(screen, 78 + 2 * (height + 8), height, label, caption, self.individual['text'], (151, 203, 218))
        screen.blit(self.small.render('N:元の表示 / Tab:個体詳細 / Esc:終了', True, (156, 183, 166)), (self.rect.x + 12, self.rect.bottom - 24))
