"""Annual ecosystem reports in a single background request slot."""
from dataclasses import dataclass
import time
from datetime import datetime, timezone
from ai_diagnostics import write_diagnostics
from queue import Empty, Queue
from threading import Thread

from annual_report import AnnualHistory
from ollama_explainer import OllamaError, OllamaExplainer


@dataclass
class Comment:
    text: str = ''
    error: str = ''
    raw_response: str = ''
    request: dict = None
    diagnostics: dict = None
    error_kind: str = ""


class AINavigator:
    def __init__(self, client=None, log_path=None):
        self.client = client
        self.annual = AnnualHistory(log_path)
        self.busy = False
        self._results = Queue(maxsize=1)
        self._closed = False

    @staticmethod
    def _generate(client, context, token, results, log_path=None):
        # No World, Organism, Pygame, or simulation RNG is accessible here.
        request = None
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            client = client or OllamaExplainer()
            request = client.build_request(context) if hasattr(client, 'build_request') else {'test_client': type(client).__name__, 'context': context}
            text = client.generate(context)
            result = Comment(text=text)
        except OllamaError as exc:
            result = Comment(error=str(exc), raw_response=exc.raw_response or '', error_kind=exc.kind)
        except Exception:
            result = Comment(error='AIでエラーが起きたよ。ルール解説を表示するね。', error_kind='internal_error')
        result.diagnostics = dict(getattr(client, 'last_diagnostics', None) or {
            'year': context.get('year'), 'target': context.get('target'),
            'model': request.get('model') if request else None,
            'started_at': started_at, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': round(time.monotonic() - started, 6),
            'success': not bool(result.error), 'error_kind': result.error_kind or None, 'ollama': {},
        })
        if log_path is not None:
            write_diagnostics(log_path, result.diagnostics)
        result.request = request
        results.put((token, result))

    def poll(self):
        try:
            token, result = self._results.get_nowait()
        except Empty:
            return
        self.busy = False
        _, year, _ = token
        if not self._closed:
            entry = self.annual.entries[year]
            entry.update(status='fallback' if result.error else 'ready', text=result.text,
                         error=result.error, raw_response=result.raw_response or result.text,
                         request=result.request, diagnostics=result.diagnostics, error_kind=result.error_kind)
            self.annual.save()
        self._start_next_annual()

    def advance(self, world, step_function, step_in_gen, extinct, done):
        result = self.annual.advance(world, step_function, step_in_gen, extinct, done)
        self._start_next_annual()
        return result

    def _start_next_annual(self):
        if self.busy or self._closed:
            return
        for year, entry in self.annual.entries.items():
            if entry['status'] == 'queued':
                entry['status'] = 'running'
                self.annual.save()
                self.busy = True
                Thread(target=self._generate, args=(self.client, entry['context'], ('annual', year, 0), self._results, self.annual.log_path.with_suffix('.debug.jsonl')),
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


class AINavigatorView:
    """Annual history in the existing sidebar."""
    def __init__(self, rect, controller=None):
        import pygame
        self.controller = controller or AINavigator()
        x, y, w, h = rect
        self.previous_rect = pygame.Rect(x + 12, y + 122, 115, 34)
        self.latest_rect = pygame.Rect(x + 139, y + 122, 115, 34)
        self.next_rect = pygame.Rect(x + 266, y + 122, 115, 34)
        self.scroll = 0
        self.max_scroll = 0
        self._display_key = None

    def handle_event(self, event):
        import pygame
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(self.max_scroll, self.scroll - event.y * 3))
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self.previous_rect.collidepoint(event.pos):
            self.controller.annual.navigate(-1)
        elif self.next_rect.collidepoint(event.pos):
            self.controller.annual.navigate(1)
        elif self.latest_rect.collidepoint(event.pos):
            self.controller.annual.selected_year = None

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

    def draw(self, screen, panel):
        import pygame
        controller = self.controller
        x, y, w, h = panel.rect
        pygame.draw.rect(screen, (12, 29, 23), panel.rect)
        panel._mascot(screen, (x + 25, y + 30), (173, 209, 138))
        screen.blit(panel.heading.render('リーフのAIナビ', True, (232, 242, 220)), (x + 48, y + 16))
        self._button(screen, panel.small, panel.detail_rect, '観察')
        self._button(screen, panel.small, panel.close_rect, '閉じる')
        screen.blit(panel.small.render('1年ごとに生態系を振り返るよ', True, (155, 186, 165)), (x + 12, y + 51))
        screen.blit(panel.font.render('年間総括', True, (232, 242, 220)), (x + 12, y + 82))
        history = controller.annual
        entry = history.displayed()
        for rect, label in ((self.previous_rect, '前の総括'), (self.latest_rect, '最新へ'), (self.next_rect, '次の総括')):
            self._button(screen, panel.small, rect, label, enabled=entry is not None)
        pending = any(r['status'] in ('queued', 'running') for r in history.entries.values())
        message = 'AI生成中：次の年間レポートを作成中...' if pending else f'1年 = {history.recorder.cycle}世代 / 年末に1回だけ総括するよ。'
        if entry:
            c = entry['context']
            title = f"{c['year']}年目の総括" + ('（途中まで）' if c['partial'] else '')
            text = entry['text'] or entry['fallback']
            caption = ('AI生成成功 · AI総括' if entry['text'] else '通常解説（AI生成失敗）') + f" / 第{c['start']['generation']}〜{c['end']['generation']}世代"
            elapsed = (entry.get('diagnostics') or {}).get('elapsed_seconds')
            if elapsed is not None:
                caption += f' / {elapsed:.1f}秒'
            if entry['error']:
                kind = entry.get('error_kind', '')
                reason = {'timeout': 'タイムアウト', 'response_format': '回答形式エラー',
                          'connection_error': 'Ollama接続不可', 'model_not_found': 'モデル未導入',
                          'http_error': 'Ollama応答エラー'}.get(kind, 'AI生成失敗')
                message += ' / ' + reason + '：通常解説に切り替え' if pending else ''
                if not pending:
                    message = reason + '：通常解説に切り替えたよ。'
        else:
            title = '最初の1年間を観察中！'
            text = '1年が終わったら、草食たちと肉食組の変化を振り返るよ。草食・肉食の観察メモも確認できるよ！'
            caption = '年末に1回更新 / 途中終了時は記録のみ保存'
        notes = '完成した総括は次の総括まで残るよ。過去の総括は前後ボタンで確認。「reports」に入力データと回答を保存するよ。'
        if history.save_error:
            notes = history.save_error
        for i, line in enumerate(panel._wrap(message, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (234, 198, 137)), (x + 12, y + 172 + i * 20))
        panel.layouts = []
        display_key = (title, text)
        if display_key != self._display_key:
            self.scroll = 0
            self._display_key = display_key
        # Keep the existing bubble/icon; scroll only its text, without truncation.
        panel._card(screen, y + 225, 240, title, '', '', (173, 209, 138))
        bubble = panel.layouts[-1][0]
        font = panel.small
        lines = panel._wrap(text, font, bubble.width - 20)
        line_height = font.get_height() + 4
        visible = max(1, (bubble.height - 18) // line_height)
        self.max_scroll = max(0, len(lines) - visible)
        self.scroll = min(self.scroll, self.max_scroll)
        clip = screen.get_clip()
        screen.set_clip(bubble.inflate(-16, -16))
        for i, line in enumerate(lines[self.scroll:self.scroll + visible]):
            screen.blit(font.render(line, True, (231, 240, 226)), (bubble.x + 10, bubble.y + 9 + i * line_height))
        screen.set_clip(clip)
        if self.max_scroll:
            caption += ' / 吹き出し内はホイールでスクロール'
        for i, line in enumerate(panel._wrap(caption, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (161, 190, 169)), (x + 12, y + 480 + i * 20))
        for i, line in enumerate(panel._wrap(notes, panel.small, w - 24)):
            screen.blit(panel.small.render(line, True, (161, 190, 169)), (x + 12, y + 519 + i * 20))
        screen.blit(panel.small.render('N:元の表示 / Tab:数値詳細 / Esc:終了', True, (156, 183, 166)), (x + 12, panel.rect.bottom - 24))
