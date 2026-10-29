"""Selection and integration only. No real Ollama/model is used by these tests."""
import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import runpy
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError
from io import BytesIO

os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/teamv-mode-mpl')
os.environ.setdefault('XDG_CACHE_HOME', '/tmp/teamv-mode-cache')

import numpy as np
import pygame
import config
import main
import save_load
from explanation_settings import ExplanationSettings, GUIDE, INSTALL_NOTICE, check_ollama
from navigator_panel import NavigatorPanel
from settings_screen import SettingsScreen, default_settings
from title_screen import _font
from world import World

ROOT = Path(__file__).resolve().parents[1]
INDIVIDUAL = '足の速さと川への適応がいい感じだね！移動の幅を広げやすいけど、たくさん動いた時の蓄えには気をつけよう。'
ANNUAL = '草食たちは年初より仲間が減ったけれど、平均の川適応は上がっているね。川を移動するときの負担を抑えやすい集団になっているのが、注目ポイントだよ！肉食組は数をほぼ保ち、平均の山適応が高めになったみたい。山での移動のしやすさを見てみよう。今年は気温にも変化があったけれど、仲間の増減の理由を気温だけで決めることはできないよ。来年も両方の群れの数と、地形への適応を追いかけていこう！'


def settle(probe):
    deadline = time.monotonic() + 2
    while probe.busy and time.monotonic() < deadline:
        probe.poll()
        time.sleep(.001)
    assert not probe.busy


class SettingsTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.s = SettingsScreen()

    def tearDown(self):
        pygame.quit()

    def click(self, rect):
        return self.s.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))

    def test_rule_default_never_connects_and_original_positions_unchanged(self):
        self.assertEqual(default_settings()['explanation_mode'], 'rule')
        with patch('urllib.request.build_opener', side_effect=AssertionError('network in rule mode')):
            self.s.draw()
            self.assertEqual(self.s._activate_button('start')[1]['explanation_mode'], 'rule')
            self.assertEqual(self.s._activate_button('load')[1]['explanation_mode'], 'rule')
        for i, (key, _, _) in enumerate(self.s.ROWS):
            self.assertEqual(self.s.row_rects[key], pygame.Rect(190, 104 + i * 58, 620, 52))
        for i, (key, _) in enumerate(self.s.BUTTONS):
            self.assertEqual(self.s.button_rects[key], pygame.Rect(210 + i * 210, 500, 190, 52))
        self.assertFalse(any(INSTALL_NOTICE == text for text, _ in self.s.explanation.layouts))

    def test_ai_notice_availability_and_start_load_forward_selection(self):
        self.s.explanation.checker = lambda: (True, 'AI解説を利用できます。')
        self.click(self.s.explanation.radios['ai'])
        settle(self.s.explanation)
        self.s.draw()
        displayed = [text for text, _ in self.s.explanation.layouts]
        self.assertTrue(all(text in displayed for text in GUIDE))
        self.assertEqual(self.s._activate_button('start')[1]['explanation_mode'], 'ai')
        self.assertEqual(self.s._activate_button('load')[1]['explanation_mode'], 'ai')
        for _, rect in self.s.explanation.layouts:
            self.assertGreaterEqual(rect.top, 100)
            self.assertLessEqual(rect.bottom, 552)
            self.assertTrue(rect.right < 190 or rect.left > 810)

    def test_unavailable_ai_blocks_only_ai_start_can_always_switch_to_rule(self):
        self.s.explanation.checker = lambda: (False, 'qwen3:4bがインストールされていません。')
        self.click(self.s.explanation.radios['ai'])
        settle(self.s.explanation)
        self.assertIsNone(self.s._activate_button('start'))
        self.assertIsNone(self.s._activate_button('load'))
        self.assertIn('qwen3:4b', self.s.explanation.message)
        self.click(self.s.explanation.radios['rule'])
        self.assertEqual(self.s._activate_button('start')[1]['explanation_mode'], 'rule')

    def test_delayed_check_is_nonblocking_and_single_flight(self):
        release, entered = Event(), Event()
        calls = []
        def slow():
            calls.append(1)
            entered.set()
            release.wait()
            return False, 'Ollamaが起動していません。'
        self.s.explanation.checker = slow
        try:
            self.click(self.s.explanation.radios['ai'])
            self.assertTrue(entered.wait(1))
            for _ in range(5):
                self.s.draw()
                self.s.explanation.check()
                pygame.event.pump()
            self.assertEqual(len(calls), 1)
            self.assertIsNone(self.s._activate_button('start'))
            self.click(self.s.explanation.radios['rule'])
            self.assertEqual(self.s._activate_button('start')[1]['explanation_mode'], 'rule')
        finally:
            release.set()
            settle(self.s.explanation)

    def test_keyboard_can_select_both_modes_and_existing_edits_still_work(self):
        self.s.explanation.checker = lambda: (True, 'OK')
        self.s.focus_id = ('explanation', 'rule')
        self.s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT))
        settle(self.s.explanation)
        self.assertEqual(self.s.explanation.mode, 'ai')
        self.s.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT))
        self.assertEqual(self.s.explanation.mode, 'rule')
        self.s._start_edit('herb', '123')
        self.s._commit()
        self.assertEqual(self.s.s['herb'], 123)


class ProbeTests(unittest.TestCase):
    def test_ready_missing_refused_timeout_invalid_and_no_proxy(self):
        from urllib.request import ProxyHandler
        import socket
        for body, expected, phrase in (({'models': [{'name': 'qwen3:4b'}]}, True, '利用できます'),
                                        ({'models': [{'model': 'qwen3:4b'}]}, True, '利用できます'),
                                        ({'models': [{'name': 'other:4b'}]}, False, 'インストール'),
                                        ({'unexpected': []}, False, '確認できません')):
            with patch('urllib.request.build_opener') as build:
                build.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
                ready, text = check_ollama()
                self.assertIs(ready, expected)
                self.assertIn(phrase, text)
                self.assertEqual(build.call_args.args[0].proxies, {})
                build.return_value.open.assert_called_once_with('http://localhost:11434/api/tags', timeout=3)
        for exc, phrase in ((URLError(ConnectionRefusedError()), '起動していません'),
                            (socket.timeout(), '時間切れ')):
            with patch('urllib.request.build_opener') as build:
                build.return_value.open.side_effect = exc
                self.assertIn(phrase, check_ollama()[1])


class GameModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd, self.temperature = Path.cwd(), config.TEMPERATURE
        os.chdir(self.tmp.name)
        pygame.init()
        self.screen = pygame.display.set_mode((1040, 640))

    def tearDown(self):
        pygame.quit()
        config.TEMPERATURE = self.temperature
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_rule_no_ai_instance_no_http_live_three_cards_and_detail(self):
        np.random.seed(1000)
        w = World()
        panel = NavigatorPanel((640, 0, 400, 640))
        self.assertIsNone(panel.ai)
        panel.open = True
        with patch('urllib.request.build_opener', side_effect=AssertionError('network')):
            panel.draw(self.screen, None, w)
            self.assertEqual(len(panel.layouts), 3)
            self.assertGreater(panel.cards['herbivore']['count'], 0)
            self.assertGreater(panel.cards['carnivore']['count'], 0)
            selected = w.organisms[0]
            panel.draw(self.screen, selected, w)
            panel.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB), selected, w)
            panel.draw(self.screen, selected, w)
            self.assertEqual(panel.view, 'detail')
            old_step = w.step_count
            panel.advance(w, main._step_simulation, 0, False, False)
            self.assertEqual(w.step_count, old_step + 1)
        panel.close()

    def test_ai_controller_defaults_to_annual_keeps_rules_and_manual_individual(self):
        from ollama_explainer import OllamaError
        np.random.seed(1000)
        w = World()
        panel = NavigatorPanel((640, 0, 400, 640), ai_enabled=True)
        panel.open = True
        self.assertEqual(panel.view, 'ai')
        org = w.organisms[0]
        class Client:
            def generate(self, context):
                return INDIVIDUAL
        panel.ai.controller.client = Client()
        panel.draw(self.screen, org, w)
        panel.ai.controller.target = 'individual'
        self.assertTrue(panel.ai.controller.request())
        deadline = time.monotonic() + 2
        while panel.ai.controller.busy and time.monotonic() < deadline:
            panel.draw(self.screen, org, w)
            time.sleep(.001)
        self.assertEqual(panel.ai.controller.comments['individual'].text, INDIVIDUAL)
        panel.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=panel.detail_rect.center), org, w)
        panel.draw(self.screen, org, w)
        self.assertEqual(panel.view, 'overview')
        self.assertEqual(len(panel.layouts), 3)
        panel.close()

    def test_main_annual_progress_controls_f5_menu_resume_and_quit(self):
        for explanation_mode in ('rule', 'ai'):
            np.random.seed(1000)
            w = World()
            frames, stage = 0, 0
            flip = pygame.display.flip
            class Client:
                def generate(self, context):
                    return ANNUAL if context['target'] == 'annual' else INDIVIDUAL
            def key(k):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k))
            def click(rect):
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
            def capture():
                nonlocal frames, stage
                flip()
                frames += 1
                self.assertLess(frames, 80)
                s = inspect.currentframe().f_back.f_locals
                p = s['status_panel']
                if stage == 0:
                    self.assertEqual(p.ai is not None, explanation_mode == 'ai')
                    if p.ai:
                        p.ai.controller.client = Client()
                    key(pygame.K_m)
                    key(pygame.K_n)
                    stage = 1
                elif stage == 1:
                    self.assertTrue(s['paused'])
                    for _ in range(config.SEASON_CYCLE):
                        key(pygame.K_RIGHT)
                    stage = 2
                elif stage == 2:
                    self.assertEqual(w.generation, 13)
                    if p.ai:
                        if p.ai.controller.busy:
                            return
                        self.assertEqual(list(p.ai.controller.annual.entries), [1])
                        self.assertEqual(p.ai.controller.annual.displayed()['text'], ANNUAL)
                    key(pygame.K_F5)
                    key(pygame.K_n)
                    key(pygame.K_e)
                    key(pygame.K_v)
                    key(pygame.K_2)
                    stage = 3
                elif stage == 3:
                    self.assertTrue(save_load.save_exists())
                    self.assertFalse(s['renderer'].show_food)
                    self.assertFalse(s['renderer'].show_season_fx)
                    click(s['menu_rect'])
                    stage = 4
                elif stage == 4:
                    self.assertTrue(s['confirm_menu'])
                    key(pygame.K_ESCAPE)
                    stage = 5
                elif stage == 5:
                    self.assertFalse(s['confirm_menu'])
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    stage = 6
            save_dir = Path(self.tmp.name) / explanation_mode
            save_dir.mkdir(exist_ok=True)
            with patch.object(save_load, 'SAVE_DIR', save_dir), patch.object(save_load, 'SAVE_PATH', save_dir/'savegame.pkl'), patch.object(config, 'MAX_STEPS_PER_GEN', 1), patch.object(pygame.display, 'flip', capture):
                main.run_with_visualization(w, explanation_mode=explanation_mode)
                state = save_load.load_game()
                self.assertEqual(state['world'].generation, 13)
                self.assertEqual(state['step_in_gen'], 0)
            self.assertEqual(stage, 6)

    def test_entrypoint_forwards_start_and_load_selection_without_changing_world(self):
        import settings_screen
        import title_screen
        for action in ('start', 'load'):
            for mode in ('rule', 'ai'):
                np.random.seed(1000)
                w = World()
                payload = default_settings()
                payload['explanation_mode'] = mode
                state = {'world': w, 'step_in_gen': 17, 'extinct': False, 'done': False}
                received = []
                def entered():
                    scope = inspect.currentframe().f_back.f_locals
                    received.append((scope['explanation_mode'], scope['resume']))
                    raise StopIteration('entry captured')
                with patch.object(title_screen, 'show_title_screen', return_value='god'), patch.object(settings_screen, 'show_settings_screen', return_value=(action, payload)), patch.object(settings_screen, 'apply_settings'), patch.object(save_load, 'load_game', return_value=state), patch.object(pygame, 'init', entered):
                    with self.assertRaisesRegex(StopIteration, 'entry captured'):
                        runpy.run_path(str(ROOT/'main.py'), run_name='__main__')
                self.assertEqual(received[0][0], mode)
                self.assertIs(received[0][1], state if action == 'load' else None)


if __name__ == '__main__':
    unittest.main()
