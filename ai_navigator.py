"""Annual reports and manual individual navigation share one background request slot."""
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread

from annual_report import AnnualHistory
from ecosystem_ai_context import EcosystemAIContext
from ollama_explainer import OllamaError, OllamaExplainer


TARGETS = (('annual', '年間総括'), ('individual', '選択個体'))


@dataclass
class Comment:
    text: str = ''
    error: str = ''
    stamp: tuple = ()
    raw_response: str = ''
    request: dict = None


class AINavigator:
    def __init__(self, client=None, log_path=None):
        self.client = client
        self.context = EcosystemAIContext()
        self.target = 'annual'
        self.annual = AnnualHistory(log_path)
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
        request = None
        try:
            client = client or OllamaExplainer()
            request = client.build_request(context) if hasattr(client, 'build_request') else {'test_client': type(client).__name__, 'context': context}
            text = client.generate(context)
            result = Comment(text=text, stamp=(context['snapshot']['generation'], context['snapshot']['step']))
        except OllamaError as exc:
            result = Comment(error=str(exc), raw_response=exc.raw_response or '')
        except Exception:
            result = Comment(error='AIでエラーが起きたよ。ルール解説を表示するね。')
        result.request = request
        results.put((token, result))

    def request(self):
        if self.busy or self._closed or self._world is None or self.target == 'annual':
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
        if target == 'annual':
            if not self._closed:
                entry = self.annual.entries[world_revision]  # token carries the completed year
                entry.update(status='fallback' if result.error else 'ready', text=result.text,
                             error=result.error, raw_response=result.raw_response or result.text,
                             request=result.request)
                self.annual.save()
        elif (not self._closed and world_revision == self._world_revision
                and (target != 'individual' or selection_revision == self._selection_revision)):
            self.comments[target] = result
        self._start_next_annual()

    def advance(self, world, step_function, step_in_gen, extinct, done):
        self.annual.recorder.before_step(world)
        result = step_function(world, step_in_gen, extinct, done)
        context = self.annual.recorder.after_step(world, result[0] == 0, result[2], result[1])
        if context is not None and self.annual.add(context):
            self._start_next_annual()
        return result

    def _start_next_annual(self):
        if self.busy or self._closed:
            return
        for year, entry in self.annual.entries.items():
            if entry['status'] == 'queued':
                entry['status'] = 'running'
                self.annual.save()
                self.busy, self.pending_target = True, 'annual'
                Thread(target=self._generate, args=(self.client, entry['context'], ('annual', year, 0), self._results),
                       name='ollama-annual-report', daemon=True).start()
                return

    def close(self):
        # Never block game exit waiting for a slow/offline local model.
        self._closed = True
        for entry in self.annual.entries.values():
            if entry['status'] in ('queued', 'running'):
                entry.update(status='interrupted', error='終了時点でAIは未完了。ルール総括を保存したよ。')
        if self.annual.entries:
            self.annual.save()
        self.comments.clear()
        self._world = self._selected = None


class AINavigatorView:
    """Annual history and manual individual explanations in the existing sidebar."""
    def __init__(self, rect, controller=None):
        import pygame
        self.controller = controller or AINavigator()
        x, y, w, h = rect
        self.tabs = {target: pygame.Rect(x + 12 + i * ((w - 24) // 2), y + 76, (w - 24) // 2 - 4, 32)
                     for i, (target, _) in enumerate(TARGETS)}
        self.update_rect = pygame.Rect(x + 47, y + 122, w - 59, 38)
        self.previous_rect = pygame.Rect(x + 12, y + 122, 115, 34)
        self.latest_rect = pygame.Rect(x + 139, y + 122, 115, 34)
        self.next_rect = pygame.Rect(x + 266, y + 122, 115, 34)

    def handle_event(self, event):
        import pygame
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        for target, rect in self.tabs.items():
            if rect.collidepoint(event.pos):
                self.controller.target = target
        if self.controller.target == 'annual':
            if self.previous_rect.collidepoint(event.pos):
                self.controller.annual.navigate(-1)
            elif self.next_rect.collidepoint(event.pos):
                self.controller.annual.navigate(1)
            elif self.latest_rect.collidepoint(event.pos):
                self.controller.annual.selected_year = None
        elif self.update_rect.collidepoint(event.pos):
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
        annual = controller.target == 'annual'
        pygame.draw.rect(screen, (12, 29, 23), panel.rect)
        panel._mascot(screen, (x + 25, y + 30), (173, 209, 138))
        screen.blit(panel.heading.render('リーフのAIナビ', True, (232, 242, 220)), (x + 48, y + 16))
        self._button(screen, panel.small, panel.detail_rect, '観察')
        self._button(screen, panel.small, panel.close_rect, '閉じる')
        screen.blit(panel.small.render('1年ごとに振り返り / 個体は手動で確認', True, (155, 186, 165)), (x + 12, y + 51))
        for key, label in TARGETS:
            self._button(screen, panel.small, self.tabs[key], label, active=key == controller.target)
        if annual:
            history = controller.annual
            entry = history.displayed()
            for rect, label in ((self.previous_rect, '前の総括'), (self.latest_rect, '最新へ'), (self.next_rect, '次の総括')):
                self._button(screen, panel.small, rect, label, enabled=entry is not None)
            pending = any(r['status'] in ('queued', 'running') for r in history.entries.values())
            message = '次の年間レポートを作成中...' if pending else f'1年 = {history.recorder.cycle}世代 / 年末に1回だけ総括するよ。'
            if entry:
                c = entry['context']
                title = f"{c['year']}年目の総括" + ('（途中まで）' if c['partial'] else '')
                text = entry['text'] or entry['fallback']
                caption = ('AI総括' if entry['text'] else 'ルール総括') + f" / 第{c['start']['generation']}〜{c['end']['generation']}世代 / 初回記録"
                if not pending and entry['error']:
                    message = entry['error']
            else:
                title = '年間総括を待っているよ'
                text = '1年が終わったら、草食たちと肉食組の変化を振り返るよ。観察メモや個体の解説は、今までどおり確認できるよ！'
                caption = '年の途中で全種絶滅・計算完了した時も記録'
            notes = '完成した総括は次の総括まで残るよ。過去の総括は前後ボタンで確認。「reports」に入力データと回答を保存するよ。'
            if history.save_error:
                notes = history.save_error
        else:
            record = controller.comments.get('individual', Comment())
            available = org is not None
            pending = controller.busy and controller.pending_target == 'individual'
            self._button(screen, panel.font, self.update_rect, '考え中...' if controller.busy else 'AI解説を更新',
                         enabled=available and not controller.busy)
            text = record.text if available and record.text and not pending else panel.individual['text']
            title = '選択個体 · ' + ('AI解説' if available and record.text and not pending else 'ルール解説')
            caption = '選択した個体を同じ種類の集団と比較'
            if pending:
                message = '考え中... 操作を続けて大丈夫だよ！'
            elif controller.busy:
                message = '年間総括を作成中。終わったら個体を更新できるよ。'
            elif record.error:
                message = record.error
            elif record.text and available:
                message = f'{record.stamp[0]}世代・累計{record.stamp[1]}ステップ時点の観察だよ。'
            else:
                message = '個体を選んで更新すると、特徴を紹介するよ！'
            notes = '個体のAI文は更新時点の参考コメント。最新の数値は「観察」→「詳細」で確認。接続できない時はルール解説が使えるよ。'
        for i, line in enumerate(panel._wrap(message, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (234, 198, 137)), (x + 12, y + 172 + i * 20))
        panel.layouts = []
        panel._card(screen, y + 225, 240, title, '', text, (173, 209, 138))
        for i, line in enumerate(panel._wrap(caption, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (161, 190, 169)), (x + 12, y + 480 + i * 20))
        for i, line in enumerate(panel._wrap(notes, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (161, 190, 169)), (x + 12, y + 519 + i * 20))
        screen.blit(panel.small.render('N:元の表示 / Tab:個体詳細 / Esc:終了', True, (156, 183, 166)), (x + 12, panel.rect.bottom - 24))
