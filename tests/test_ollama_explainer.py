"""Local HTTP stand-in only: these tests never claim to test a real Qwen model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ollama_explainer import MAX_RESPONSE_BYTES, OllamaError, OllamaExplainer, OllamaSettings


COMMENT = '足の速さと川への適応がいい感じだね！移動の幅を広げやすいけど、たくさん動いた時の蓄えには気をつけよう。'


class OllamaClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        cls.response = None
        cls.status = 200
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                cls.calls.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(cls.status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(cls.response)
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        type(self).status = 200
        self.set_comment(COMMENT)
        self.client = OllamaExplainer(OllamaSettings(base_url=f'http://127.0.0.1:{self.server.server_port}'))

    def set_comment(self, text):
        type(self).response = json.dumps({'done': True, 'message': {'content': json.dumps({'comment': text}, ensure_ascii=False)}}).encode()

    def test_official_api_payload_for_all_targets(self):
        for target in ('herbivore', 'carnivore', 'individual'):
            self.assertEqual(self.client.generate({'target': target, 'snapshot': {'step': 2}}), COMMENT)
            path, payload = self.calls[-1]
            self.assertEqual(path, '/api/chat')
            self.assertEqual(payload['model'], 'qwen3:4b')
            self.assertIs(payload['think'], False)
            self.assertIs(payload['stream'], False)
            self.assertEqual(payload['options']['num_predict'], 256)
            self.assertEqual(payload['options']['num_thread'], 4)
            self.assertEqual(json.loads(payload['messages'][1]['content'])['target'], target)
            self.assertEqual(payload['format']['properties']['comment']['maxLength'], 80)

    def test_error_missing_model_malformed_truncated_and_large_response(self):
        type(self).status = 404
        with self.assertRaisesRegex(OllamaError, 'モデル'):
            self.client.generate({})
        type(self).status = 500
        with self.assertRaisesRegex(OllamaError, '応答'):
            self.client.generate({})
        type(self).status = 200
        for raw in (b'not JSON', b'[]', b'{}', b'{"done": false}', b'x' * (MAX_RESPONSE_BYTES + 1)):
            type(self).response = raw
            with self.assertRaises(OllamaError):
                self.client.generate({})

    def test_reject_invalid_text_and_accept_character_boundaries(self):
        for text in ('', '短すぎるよ。', 'あ' * 81, 'a' * 50, '<think>' + 'あ' * 45, None, 123):
            self.set_comment(text)
            with self.assertRaises(OllamaError):
                self.client.generate({})
        for n in (40, 80):
            self.set_comment('あ' * n)
            self.assertEqual(len(self.client.generate({})), n)

    def test_annual_request_limits_both_species_and_separate_prompt(self):
        for n in (160, 190):
            text = '草食たちと肉食組。' + 'あ' * (n - len('草食たちと肉食組。'))
            self.set_comment(text)
            self.assertEqual(self.client.generate({'target': 'annual', 'year': 1}), text)
            payload = self.calls[-1][1]
            self.assertEqual(payload['format']['properties']['comment']['minLength'], 40)
            self.assertEqual(payload['format']['properties']['comment']['maxLength'], 2000)
            self.assertEqual(payload['options']['num_predict'], 512)
            self.assertIs(payload['think'], False)
            self.assertEqual([m['role'] for m in payload['messages']], ['user'])
            self.assertIn('未来は条件付き', payload['messages'][0]['content'])

    def test_annual_invalid_response_is_kept_for_audit(self):
        for text in ('あ' * 180, '草食だけ' + 'あ' * 180, '草食と肉食' + 'あ' * 2000):
            self.set_comment(text)
            with self.assertRaises(OllamaError) as caught:
                self.client.generate({'target': 'annual', 'year': 1})
            self.assertTrue(caught.exception.raw_response)

    def test_connection_refusal_and_timeouts_are_friendly(self):
        for exc, message in ((URLError(ConnectionRefusedError()), 'つながらない'),
                             (URLError(socket.timeout()), '時間切れ'), (socket.timeout(), '時間切れ')):
            with patch('ollama_explainer.build_opener') as opener:
                opener.return_value.open.side_effect = exc
                with self.assertRaisesRegex(OllamaError, message):
                    self.client.generate({})
                self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], 60)

    def test_actual_connection_refusal(self):
        # Bind a port without listening: the OS rejects the actual HTTP connection.
        with socket.socket() as bound:
            bound.bind(('127.0.0.1', 0))
            cfg = OllamaSettings(base_url=f'http://127.0.0.1:{bound.getsockname()[1]}', timeout_seconds=1)
            with self.assertRaisesRegex(OllamaError, 'つながらない'):
                OllamaExplainer(cfg).generate({})

    def test_proxy_bypass_and_no_external_redirects(self):
        from ollama_explainer import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
        with patch('ollama_explainer.build_opener', wraps=__import__('urllib.request', fromlist=['build_opener']).build_opener) as build:
            self.client.generate({})
            self.assertEqual(build.call_args.args[0].proxies, {})

    def test_settings_are_local_bounded_and_config_errors_do_not_escape(self):
        for kwargs in ({'base_url': 'https://api.example.com'}, {'base_url': 'http://localhost@evil.test'},
                       {'base_url': 'http://localhost:11434/path'}, {'base_url': 'http://localhost:bad'},
                       {'timeout_seconds': 0}, {'timeout_seconds': 181}, {'num_predict': 100000},
                       {'num_thread': 32}, {'model': ''}, {'keep_alive': '-1'}):
            with self.assertRaises(ValueError):
                OllamaSettings(**kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.json'
            for content in ('{', '[]', '{"model": null}', '{"unknown": true}'):
                p.write_text(content)
                with self.assertRaises(OllamaError):
                    OllamaSettings.load(p)
        self.assertEqual(OllamaSettings.load().model, 'ecosystem-leaf:latest')


if __name__ == '__main__':
    unittest.main()
