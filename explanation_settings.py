"""Explanation selector in unused settings margins; local checks run off-thread."""
import json
from queue import Empty, Queue
from threading import Thread

import pygame


INSTALL_NOTICE = 'AI解説を利用するには、OllamaのインストールとローカルAIモデル『qwen3:4b』のダウンロードが必要です。'
GUIDE = (INSTALL_NOTICE, 'Ollama公式サイト：', 'https://ollama.com/download',
         'モデルの導入コマンド：', 'ollama pull qwen3:4b',
         '初回ダウンロードにはインターネット接続が必要です。',
         'AI生成時はPCのメモリ・CPUなどを使用するため、動作が重くなる場合があります。',
         'モデル導入後は基本的にローカルでAI解説を実行できます。')


def check_ollama():
    # Import/load AI settings only after the player explicitly selects AI.
    from ollama_explainer import OllamaSettings, _NoRedirect, MAX_RESPONSE_BYTES
    from urllib.request import ProxyHandler, build_opener
    from urllib.error import URLError, HTTPError
    import socket
    try:
        cfg = OllamaSettings.load()
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(cfg.base_url.rstrip('/') + '/api/tags', timeout=3) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return False, 'Ollamaの応答を確認できませんでした。'
        models = json.loads(raw)['models']
        if any(cfg.model in (m.get('name'), m.get('model')) for m in models):
            return True, 'AI解説を利用できます。'
        return False, f'{cfg.model}がインストールされていません。'
    except (socket.timeout, TimeoutError):
        return False, 'Ollamaの確認が時間切れになりました。'
    except HTTPError:
        return False, 'Ollamaの応答を確認できませんでした。'
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return False, 'Ollamaの確認が時間切れになりました。'
        return False, 'Ollamaが起動していません。'
    except Exception:
        return False, 'AIの接続設定・応答を確認できませんでした。'


class ExplanationSettings:
    def __init__(self, font_factory, checker=None):
        self.mode = 'rule'
        self.font = font_factory(14)
        self.small = font_factory(12)
        self.heading = font_factory(18)
        self.radios = {'rule': pygame.Rect(14, 151, 160, 62), 'ai': pygame.Rect(14, 226, 160, 68)}
        self.retry_rect = pygame.Rect(18, 312, 150, 32)
        self.checker = checker or check_ollama
        self.results = Queue(maxsize=1)
        self.busy = False
        self.ready = False
        self.message = ''
        self.layouts = []

    def select(self, mode):
        if mode != self.mode:
            self.mode = mode
            if mode == 'ai':
                self.check()

    def check(self):
        if self.mode != 'ai' or self.busy:
            return
        self.busy, self.ready = True, False
        self.message = 'Ollamaを確認中...'
        checker, results = self.checker, self.results
        def worker():
            try:
                result = checker()
            except Exception:
                result = (False, 'Ollamaの確認に失敗しました。')
            results.put(result)
        Thread(target=worker, daemon=True, name='ollama-availability').start()

    def poll(self):
        try:
            self.ready, self.message = self.results.get_nowait()
        except Empty:
            return
        self.busy = False

    def can_start(self):
        self.poll()
        return self.mode == 'rule' or (self.ready and not self.busy)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for mode, rect in self.radios.items():
                if rect.collidepoint(event.pos):
                    self.select(mode)
                    return True
            if self.mode == 'ai' and self.retry_rect.collidepoint(event.pos):
                self.check()
                return True
        return False

    @staticmethod
    def _wrap(text, font, width):
        lines, line = [], ''
        for ch in text:
            if ch == '\n':
                lines.append(line)
                line = ''
                continue
            if line and font.size(line + ch)[0] > width:
                lines.append(line)
                line = ch
            else:
                line += ch
        if line:
            lines.append(line)
        return lines

    def _paragraph(self, screen, text, font, x, y, width, color):
        lines = self._wrap(text, font, width)
        height = font.get_linesize() + 3
        self.layouts.append((text, pygame.Rect(x, y, width, len(lines) * height)))
        for line in lines:
            screen.blit(font.render(line, True, color), (x, y))
            y += height
        return y

    def draw(self, screen, focus=None):
        self.poll()
        self.layouts = []
        pygame.draw.rect(screen, (12, 29, 23), (10, 104, 168, 377), border_radius=8)
        screen.blit(self.heading.render('解説方式', True, (234, 244, 226)), (20, 112))
        for mode, label in (('rule', '通常解説（AIなし）'), ('ai', 'AI解説\n（ローカルLLM）')):
            rect = self.radios[mode]
            pygame.draw.rect(screen, (16, 36, 27), rect, border_radius=8)
            pygame.draw.rect(screen, (152, 197, 123) if self.mode == mode else (44, 76, 52), rect, 2, border_radius=8)
            if focus == ('explanation', mode):
                pygame.draw.rect(screen, (234, 244, 226), rect, 1, border_radius=8)
            center = (rect.x + 13, rect.y + 17)
            pygame.draw.circle(screen, (152, 197, 123), center, 6, 1)
            if self.mode == mode:
                pygame.draw.circle(screen, (152, 197, 123), center, 3)
            self._paragraph(screen, label, self.font, rect.x + 26, rect.y + 9, rect.width - 30, (234, 244, 226))
        if self.mode == 'rule':
            self._paragraph(screen, 'Ollama不要。ネット接続なしで使えます。', self.font, 18, 316, 150, (153, 177, 155))
            return
        pygame.draw.rect(screen, (22, 49, 33), self.retry_rect, border_radius=6)
        screen.blit(self.font.render('確認中...' if self.busy else '接続を再確認', True, (234, 244, 226)), (30, 317))
        y = self._paragraph(screen, self.message, self.font, 18, 359, 150, (163, 204, 131) if self.ready else (240, 180, 120))
        if not self.ready:
            self._paragraph(screen, '通常解説を選ぶと、そのまま開始できます。', self.font, 18, y + 12, 150, (153, 177, 155))
        y = 106
        pygame.draw.rect(screen, (12, 29, 23), (821, 100, 173, 410), border_radius=8)
        for text in GUIDE:
            y = self._paragraph(screen, text, self.small, 829, y, 157, (183, 202, 178)) + 5
