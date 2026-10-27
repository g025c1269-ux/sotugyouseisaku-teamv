"""Manual AI navigation: one daemon worker, immutable snapshots, main-thread UI."""
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread

from ecosystem_ai_context import EcosystemAIContext
from ollama_explainer import OllamaError, OllamaExplainer


TARGETS = (('herbivore', '草食全体'), ('carnivore', '肉食全体'), ('individual', '選択個体'))


@dataclass
class Comment:
    text: str = ''
    error: str = ''
    stamp: tuple = ()


class AINavigator:
    def __init__(self, client=None):
        self.client = client
        self.context = EcosystemAIContext()
        self.target = 'herbivore'
        self.comments = {}
        self.busy = False
        self.pending_target = None
        self._world = None
        self._selected = None
        self._world_revision = 0
        self._selection_revision = 0
        self._results = Queue(maxsize=1)
        self._closed = False

    def sync(self, world, selected):
        if world is not self._world:
            self._world = world
            self._world_revision += 1
            self.comments.clear()
        if selected is not None and (not selected.alive or selected not in world.organisms):
            selected = None
        if selected is not self._selected:
            self._selected = selected
            self._selection_revision += 1
            self.comments.pop('individual', None)
        self.poll()

    @staticmethod
    def _generate(client, context, token, results):
        # No World, Organism, Pygame, or simulation RNG is accessible here.
        try:
            text = (client or OllamaExplainer()).generate(context)
            result = Comment(text=text, stamp=(context['snapshot']['generation'], context['snapshot']['step']))
        except OllamaError as exc:
            result = Comment(error=str(exc))
        except Exception:
            result = Comment(error='AIでエラーが起きたよ。ルール解説を表示するね。')
        results.put((token, result))

    def request(self):
        if self.busy or self._closed or self._world is None:
            return False
        target = self.target
        try:
            snapshot = self.context.build(self._world, target, self._selected)
        except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError):
            message = ('マップで生きている個体を選んでね。' if target == 'individual'
                       else '対象の生物がいないか、値を読み取れないよ。')
            self.comments[target] = Comment(error=message)
            return False
        token = (target, self._world_revision, self._selection_revision)
        self.comments.pop(target, None)
        self.busy, self.pending_target = True, target
        Thread(target=self._generate, args=(self.client, snapshot, token, self._results),
               name='ollama-navigator', daemon=True).start()
        return True

    def poll(self):
        try:
            token, result = self._results.get_nowait()
        except Empty:
            return
        self.busy, self.pending_target = False, None
        target, world_revision, selection_revision = token
        if (not self._closed and world_revision == self._world_revision
                and (target != 'individual' or selection_revision == self._selection_revision)):
            self.comments[target] = result

    def close(self):
        # Never block game exit waiting for a slow/offline local model.
        self._closed = True
        self.comments.clear()
        self._world = self._selected = None


class AINavigatorView:
    """Reuse the existing sidebar, mascot and speech-bubble renderer."""
    def __init__(self, rect, controller=None):
        import pygame
        self.controller = controller or AINavigator()
        x, y, w, h = rect
        self.tabs = {target: pygame.Rect(x + 12 + i * ((w - 24) // 3), y + 76, (w - 24) // 3 - 4, 32)
                     for i, (target, _) in enumerate(TARGETS)}
        self.update_rect = pygame.Rect(x + 47, y + 122, w - 59, 38)

    def handle_event(self, event):
        import pygame
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        for target, rect in self.tabs.items():
            if rect.collidepoint(event.pos):
                self.controller.target = target
        if self.update_rect.collidepoint(event.pos):
            self.controller.request()

    @staticmethod
    def _button(screen, font, rect, label, active=False, enabled=True):
        import pygame
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        color = ((65, 103, 66) if hover else (44, 81, 54)) if enabled else (27, 45, 35)
        pygame.draw.rect(screen, color, rect, border_radius=6)
        if active:
            pygame.draw.rect(screen, (177, 211, 141), rect, 2, border_radius=6)
        text = font.render(label, True, (232, 242, 220) if enabled else (137, 158, 144))
        screen.blit(text, text.get_rect(center=rect.center))

    def draw(self, screen, panel, world, org):
        import pygame
        controller = self.controller
        x, y, w, h = panel.rect
        target = controller.target
        record = controller.comments.get(target, Comment())
        pending = controller.busy and controller.pending_target == target
        if target == 'individual':
            fallback = panel.individual['text']
            available = org is not None
            caption = '選択した個体を集団と比較'
        else:
            report = panel.cards[target]
            fallback = report['text']
            available = report['count'] > 0
            caption = f"現在 {report['count']}匹 / 平均と分布を観察"
        # An extinct population must not display a previous, living population's AI text.
        use_ai = available and bool(record.text) and not pending
        status = 'AI解説（更新時点）' if use_ai else 'ルール解説（現在）'
        text = record.text if use_ai else fallback
        pygame.draw.rect(screen, (12, 29, 23), panel.rect)
        panel._mascot(screen, (x + 25, y + 30), (173, 209, 138))
        screen.blit(panel.heading.render('リーフのAIナビ', True, (232, 242, 220)), (x + 48, y + 16))
        self._button(screen, panel.small, panel.detail_rect, '観察')
        self._button(screen, panel.small, panel.close_rect, '閉じる')
        screen.blit(panel.small.render('ローカルAI / ボタンを押した時だけ生成', True, (155, 186, 165)), (x + 12, y + 51))
        for key, label in TARGETS:
            self._button(screen, panel.small, self.tabs[key], label, active=key == target)
        self._button(screen, panel.font, self.update_rect, '考え中...' if controller.busy else 'AI解説を更新',
                     enabled=available and not controller.busy)
        if pending:
            message = '考え中... 操作を続けて大丈夫だよ！'
        elif controller.busy:
            message = '別の対象を考え中... 終わったら更新できるよ。'
        elif record.error:
            message = record.error
        elif use_ai:
            generation, step = record.stamp
            message = f'{generation}世代・累計{step}ステップ時点の観察だよ。'
        elif not available:
            message = '個体を選択してね。' if target == 'individual' else 'この種類は今いないよ。'
        else:
            message = '更新するとAIがこの瞬間の特徴を紹介するよ！'
        for i, line in enumerate(panel._wrap(message, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (234, 198, 137)), (x + 12, y + 172 + i * 20))
        panel.layouts = []
        title = dict(TARGETS)[target] + ' · ' + status
        panel._card(screen, y + 225, 240, title, '', text, (173, 209, 138))
        for i, line in enumerate(panel._wrap(caption, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (161, 190, 169)), (x + 12, y + 480 + i * 20))
        notes = 'AI文は更新時点の参考コメント。最新の数値は「観察」→「詳細」で確認してね。接続できない時はルール解説が使えるよ。'
        for i, line in enumerate(panel._wrap(notes, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (161, 190, 169)), (x + 12, y + 519 + i * 20))
        screen.blit(panel.small.render('N:元の表示 / Tab:個体詳細 / Esc:終了', True, (156, 183, 166)), (x + 12, panel.rect.bottom - 24))
