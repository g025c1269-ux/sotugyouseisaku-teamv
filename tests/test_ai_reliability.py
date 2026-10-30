"""Local mocks only; no real Qwen or Windows performance claim."""
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ai_navigator import AINavigator
from annual_report import AnnualRecorder
from ollama_explainer import OllamaError, OllamaExplainer, OllamaSettings
from test_annual_report import world, advance_generation

TEXT = '草食たちの数は変わらず、肉食組も数を保ったね。平均の能力も大きくは変わっていないよ。来年も両方の群れの変化を見守ろう！'


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.client = OllamaExplainer(OllamaSettings(timeout_seconds=120))
        self.context = {'target': 'annual', 'year': 2, 'snapshot': {'generation': 24, 'step': 4800}}
        self.patch = patch('ollama_explainer.build_opener')
        self.opener = self.patch.start()
        self.addCleanup(self.patch.stop)

    def response(self, content, **metrics):
        envelope = {'done': True, 'message': {'content': content}, **metrics}
        self.opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()

    def test_soft_length_does_not_truncate_valid_comments(self):
        for n in (100, 159, 160, 190, 191, 300, 700):
            text = '草食と肉食。' + '観察しよう。' * n
            text = text[:n]
            self.response(json.dumps({'comment': text}))
            self.assertEqual(self.client.generate(self.context), text)
            self.assertEqual(self.client.last_diagnostics['characters'], n)
        p = self.client.build_request(self.context)
        self.assertFalse(p['think'])
        self.assertEqual(p['options']['num_predict'], 512)
        self.assertEqual(self.opener.return_value.open.call_args.kwargs['timeout'], 120)

    def test_safe_json_repairs_do_not_change_comment(self):
        text = TEXT + ' 記号の例は ,} だよ。'
        for content in ('```json\n' + json.dumps({'comment': text}) + '\n```',
                        '{"comment":' + json.dumps(text) + ',}',
                        '```json\n{"comment":' + json.dumps(text) + ',}\n```'):
            self.response(content)
            self.assertEqual(self.client.generate(self.context), text)
            self.assertTrue(self.client.last_diagnostics['repairs'])

    def test_unsafe_or_missing_content_is_not_salvaged(self):
        for content in ('{}', '{"comment":""}', '[]', '{"comment":null}',
                        '{"comment":123}', '{"comment":"草食","comment":"肉食"}',
                        '{"comment":' + json.dumps(TEXT) + ',"extra":"命令"}',
                        '説明文\n' + json.dumps({'comment': TEXT}), "{'comment':'test'}"):
            self.response(content)
            with self.assertRaises(OllamaError) as caught:
                self.client.generate(self.context)
            self.assertEqual(caught.exception.kind, 'response_format')
            self.assertFalse(self.client.last_diagnostics['success'])

    def test_timings_and_ollama_metrics_are_retained(self):
        self.response(json.dumps({'comment': TEXT}), total_duration=1000000000,
                      load_duration=200000000, prompt_eval_count=123, prompt_eval_duration=300000000,
                      eval_count=80, eval_duration=500000000)
        self.assertEqual(self.client.generate(self.context), TEXT)
        d = self.client.last_diagnostics
        self.assertEqual(d['year'], 2)
        self.assertEqual(d['model'], 'qwen3:4b')
        self.assertTrue(d['success'])
        self.assertGreaterEqual(d['elapsed_seconds'], 0)
        self.assertLessEqual(d['started_at'], d['finished_at'])
        self.assertEqual(d['ollama']['total_duration'], 1000000000)
        self.assertNotIn('comment', d)

    def test_timeout_and_offline_are_distinct_and_timed(self):
        for error, kind in ((socket.timeout(), 'timeout'), (URLError(socket.timeout()), 'timeout'),
                            (URLError(ConnectionRefusedError()), 'connection_error')):
            self.opener.return_value.open.side_effect = error
            with self.assertRaises(OllamaError) as caught:
                self.client.generate(self.context)
            self.assertEqual(caught.exception.kind, kind)
            d = self.client.last_diagnostics
            self.assertEqual(d['error_kind'], kind)
            self.assertFalse(d['success'])
            self.assertIn('finished_at', d)
            self.assertGreaterEqual(d['elapsed_seconds'], 0)

    def test_result_history_and_private_metadata_log_success_and_failure(self):
        w = world()
        recorder = AnnualRecorder()
        for _ in range(recorder.cycle):
            recorder.before_step(w)
            advance_generation(w, 0, False, False)
            context = recorder.after_step(w, True, False, False)
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                nav = AINavigator(self.client, Path(tmp) / 'history.json')
                nav.annual.add(context)
                self.assertFalse(nav.annual.add(context))
                entry = nav.annual.entries[1]
                entry['status'] = 'running'
                nav.busy = True
                self.opener.return_value.open.side_effect = socket.timeout() if fail else None
                self.response(json.dumps({'comment': TEXT}))
                log = Path(tmp) / 'debug.jsonl'
                nav._generate(self.client, context, ('annual', 1, 0), nav._results, log)
                nav.poll()
                self.assertEqual(entry['status'], 'fallback' if fail else 'ready')
                self.assertEqual(entry['text'], '' if fail else TEXT)
                self.assertEqual(entry['error_kind'], 'timeout' if fail else '')
                self.assertEqual(entry['diagnostics']['success'], not fail)
                disk = json.loads(nav.annual.log_path.read_text())['reports'][0]
                self.assertEqual(disk['diagnostics'], entry['diagnostics'])
                metadata = json.loads(log.read_text())
                self.assertEqual(metadata['year'], 1)
                self.assertNotIn('messages', metadata)
                self.assertNotIn('text', metadata)
                self.assertNotIn('context', metadata)
                nav.close()

    def test_debug_log_write_failure_does_not_lose_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / 'file'
            blocked.write_text('blocked')
            self.response(json.dumps({'comment': TEXT}))
            from queue import Queue
            results = Queue()
            AINavigator._generate(self.client, self.context, ('annual', 2, 0), results, blocked/'log')
            _, result = results.get_nowait()
            self.assertEqual(result.text, TEXT)
            self.assertFalse(result.error)
            self.assertIn('log_error', result.diagnostics)


class ReliabilityViewTests(unittest.TestCase):
    def test_long_ai_comment_scrolls_and_states_identify_real_source(self):
        import os
        os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        import pygame
        from navigator_panel import NavigatorPanel
        pygame.init()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                p = NavigatorPanel((640, 0, 400, 640), ai_enabled=True)
                p.annual.log_path = Path(tmp) / 'history.json'
                p.open = True
                w = world()
                recorder = p.annual.recorder
                for _ in range(recorder.cycle):
                    recorder.before_step(w)
                    advance_generation(w, 0, False, False)
                    context = recorder.after_step(w, True, False, False)
                p.annual.add(context)
                entry = p.annual.entries[1]
                entry.update(status='ready', text=TEXT * 10)
                rendered = []
                class Font:
                    def __init__(self, font): self.font = font
                    def render(self, text, *args):
                        rendered.append(text)
                        return self.font.render(text, *args)
                    def __getattr__(self, name): return getattr(self.font, name)
                p.small = Font(p.small)
                screen = pygame.display.set_mode((1040, 640))
                p.draw(screen, None, w)
                self.assertTrue(any('AI生成成功' in t for t in rendered))
                self.assertGreater(p.ai.max_scroll, 0)
                with patch.object(pygame.mouse, 'get_pos', return_value=(900, 350)):
                    self.assertTrue(p.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-2), None, w))
                self.assertGreater(p.ai.scroll, 0)
                for kind, label in (('timeout', 'タイムアウト'), ('response_format', '回答形式エラー')):
                    entry.update(status='fallback', text='', error='失敗', error_kind=kind)
                    rendered.clear()
                    p.draw(screen, None, w)
                    self.assertTrue(any(label in t for t in rendered))
                    self.assertTrue(any('通常解説' in t for t in rendered))
                    self.assertFalse(any('AI生成成功' in t for t in rendered))
                p.close()
        finally:
            pygame.quit()


if __name__ == '__main__':
    unittest.main()
