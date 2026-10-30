"""Shared yearly cadence; model calls are mocked, never sent to a real Ollama."""
import copy
import inspect
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('MPLBACKEND', 'Agg')

import numpy as np
import pygame
import config
import main
from annual_report import annual_population_reports
from navigator_panel import NavigatorPanel
from test_annual_report import world, advance_generation, SlowClient, TEXT


class AnnualCadenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd, self.temperature = Path.cwd(), config.TEMPERATURE
        os.chdir(self.tmp.name)
        pygame.init()
        self.screen = pygame.display.set_mode((1040, 640))
        self.w = world()
        self.panels, self.clients = [], []

    def tearDown(self):
        for client in self.clients:
            client.release.set()
        for panel in self.panels:
            if panel.ai:
                self.settle(panel.ai.controller)
            panel.close()
        config.TEMPERATURE = self.temperature
        pygame.quit()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def panel(self, ai=False):
        p = NavigatorPanel((640, 0, 400, 640), ai_enabled=ai)
        p.open = True
        self.panels.append(p)
        if ai:
            client = SlowClient()
            self.clients.append(client)
            p.ai.controller.client = client
        return p

    def settle(self, controller):
        deadline = time.monotonic() + 2
        while controller.busy and time.monotonic() < deadline:
            controller.poll()
            time.sleep(.001)
        self.assertFalse(controller.busy)

    def generations(self, panel, count, w=None):
        for _ in range(count):
            panel.advance(w or self.w, advance_generation, 0, False, False)

    def test_normal_publishes_once_per_year_and_never_on_redraw_or_status_change(self):
        p = self.panel()
        original = copy.deepcopy(p.cards)
        with patch('urllib.request.build_opener', side_effect=AssertionError('normal mode HTTP')), \
                patch('annual_report.annual_population_reports', wraps=annual_population_reports) as build:
            self.generations(p, config.SEASON_CYCLE - 1)
            for _ in range(20):
                self.w.organisms[0].genes['speed'] = .9
                self.w.step_count += 1
                p.draw(self.screen, None, self.w)
            self.assertEqual(p.cards, original)
            self.assertEqual(build.call_count, 0)
            self.generations(p, 1)
            p.draw(self.screen, None, self.w)
            frozen = copy.deepcopy(p.cards)
            self.assertEqual(build.call_count, 1)
            self.w.organisms[0].genes['speed'] = .1
            config.TEMPERATURE += 20
            self.generations(p, config.SEASON_CYCLE - 1)
            for _ in range(30):
                p.draw(self.screen, None, self.w)
                p.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n), None, self.w)
            self.assertEqual(p.cards, frozen)
            self.assertEqual(build.call_count, 1)
            self.generations(p, 1)
            p.open = True
            p.draw(self.screen, None, self.w)
            self.assertEqual(build.call_count, 2)
            self.assertNotEqual(p.cards, frozen)
            self.assertEqual(list(p.annual.entries), [1, 2])

    def test_both_modes_use_identical_completed_year_snapshots(self):
        normal, ai = self.panel(), self.panel(True)
        self.clients[-1].release.set()
        w2 = copy.deepcopy(self.w)
        for generation in range(1, config.SEASON_CYCLE * 2 + 1):
            config.TEMPERATURE = 5 + generation
            for p, w in ((normal, self.w), (ai, w2)):
                w.organisms[0].genes['speed'] = generation / 30
                self.generations(p, 1, w)
        self.settle(ai.ai.controller)
        for year in (1, 2):
            a, b = normal.annual.entries[year], ai.annual.entries[year]
            self.assertEqual(a['context'], b['context'])
            self.assertEqual(a['population_reports'], b['population_reports'])
        self.assertEqual([c['year'] for c in self.clients[-1].calls], [1, 2])

    def test_ai_overview_holds_last_completed_report_while_next_year_is_pending(self):
        p = self.panel(True)
        client = self.clients[-1]
        self.generations(p, config.SEASON_CYCLE)
        self.assertTrue(client.entered.wait(1))
        p.view = 'overview'
        p.draw(self.screen, None, self.w)
        self.assertIsNone(p.cards['herbivore']['count'])
        client.release.set()
        self.settle(p.ai.controller)
        p.draw(self.screen, None, self.w)
        frozen = copy.deepcopy(p.cards)
        client.release.clear()
        self.w.organisms[0].genes['speed'] = .1
        self.generations(p, config.SEASON_CYCLE)
        for _ in range(20):
            p.draw(self.screen, None, self.w)
            self.assertFalse(hasattr(p.ai.controller, 'request'))
        self.assertEqual(p.cards, frozen)
        self.assertEqual(p.annual.displayed()['context']['year'], 1)
        client.release.set()
        self.settle(p.ai.controller)
        p.draw(self.screen, None, self.w)
        self.assertNotEqual(p.cards, frozen)
        self.assertEqual([c['year'] for c in client.calls], [1, 2])

    def test_revisiting_completed_year_and_new_world_object_does_not_regenerate(self):
        for ai in (False, True):
            with self.subTest(ai=ai):
                p = self.panel(ai)
                if ai:
                    self.clients[-1].release.set()
                w = world()
                start = copy.deepcopy(w)
                self.generations(p, config.SEASON_CYCLE, w)
                if ai:
                    self.settle(p.ai.controller)
                before = copy.deepcopy(p.annual.entries[1])
                w = start
                self.generations(p, config.SEASON_CYCLE, w)
                if ai:
                    self.settle(p.ai.controller)
                    self.assertEqual(len(self.clients[-1].calls), 1)
                self.assertEqual(p.annual.entries[1], before)

    def test_midyear_completion_or_extinction_saves_only_data_without_comment_update(self):
        for ai in (False, True):
            for extinct in (False, True):
                with self.subTest(ai=ai, extinct=extinct):
                    p = self.panel(ai)
                    w = world()
                    def finish(w, step, ex, done):
                        w.step_count += 1
                        return 0, extinct, True
                    result = p.advance(w, finish, 0, False, False)
                    self.assertEqual(result, (0, extinct, True))
                    entry = p.annual.entries[1]
                    self.assertFalse(entry['context']['year_completed'])
                    self.assertEqual(entry['status'], 'incomplete')
                    self.assertEqual(entry['fallback'], '')
                    self.assertIsNone(p.annual.displayed())
                    if ai:
                        self.assertFalse(self.clients[-1].calls)
                    p.advance(w, lambda *a: self.fail('done stepped again'), *result)
                    saved = json.loads(p.annual.log_path.read_text(encoding='utf-8'))
                    self.assertEqual(saved['reports'][0]['context']['reason'], 'extinction' if extinct else 'simulation_end')

    def test_extinction_early_in_last_month_is_not_a_completed_year(self):
        p = self.panel(True)
        self.generations(p, config.SEASON_CYCLE - 1)
        def extinct(w, *args):
            w.step_count += 1
            w.organisms.clear()
            return 0, True, True
        p.advance(self.w, extinct, 0, False, False)
        self.assertEqual(p.annual.entries[1]['status'], 'incomplete')
        self.assertFalse(self.clients[-1].calls)

    def test_existing_calendar_setting_and_midyear_loaded_game(self):
        with patch.object(config, 'SEASON_CYCLE', 4):
            p = self.panel()
            self.w.generation = 3
            self.generations(p, 1)
            self.assertIsNone(p.annual.displayed())
            self.generations(p, 1)
            entry = p.annual.displayed()
            self.assertTrue(entry['context']['partial'])
            self.assertTrue(entry['context']['year_completed'])
            self.assertEqual(entry['context']['generations_per_year'], 4)
            self.assertEqual(entry['context']['start']['generation'], 3)
            p.draw(self.screen, None, self.w)
            self.assertEqual(p.cards, entry['population_reports'])

    def test_frozen_population_does_not_prevent_numeric_inspection(self):
        p = self.panel()
        self.generations(p, config.SEASON_CYCLE)
        org = self.w.organisms[0]
        p.draw(self.screen, org, self.w)
        frozen = copy.deepcopy(p.cards)
        self.assertFalse(hasattr(p, "individual"))
        org.genes['speed'], org.genes['river_tolerance'] = .9, .1
        org.energy = .1 * org.max_energy
        p.draw(self.screen, org, self.w)
        self.assertEqual(p.cards, frozen)
        p.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB), org, self.w)
        p.draw(self.screen, org, self.w)
        self.assertEqual(p.view, 'detail')

    def test_normal_summary_counts_traits_environment_no_unknown_events_or_inactive_traits(self):
        p = self.panel()
        config.TEMPERATURE = 5
        self.generations(p, 1)
        self.w.organisms.append(copy.deepcopy(self.w.organisms[0]))
        for org in self.w.organisms:
            org.genes['speed'] = .8
            org.genes['hunger_threshold'] = 1
        config.TEMPERATURE = 30
        self.generations(p, config.SEASON_CYCLE - 1)
        row = p.annual.displayed()
        self.assertEqual(row['context']['changes']['herbivore']['count_delta'], 1)
        self.assertAlmostEqual(row['context']['changes']['herbivore']['traits']['speed']['delta'], .3)
        text = row['population_reports']['herbivore']['text']
        self.assertIn('増えた', text)
        self.assertIn('平均移動速度が上がった', text)
        self.assertIn('気温', text)
        self.assertNotIn('繁殖意欲', text)
        self.assertNotIn('災害', text)

    def test_bubbles_and_mascot_stay_in_sidebar(self):
        p = self.panel()
        self.generations(p, 1)
        for org in self.w.organisms:
            org.genes['mountain_tolerance'] = .9
        self.generations(p, config.SEASON_CYCLE - 1)
        self.screen.fill((81, 28, 67))
        before = pygame.surfarray.array3d(self.screen)[:640].copy()
        p.draw(self.screen, None, self.w)
        np.testing.assert_array_equal(before, pygame.surfarray.array3d(self.screen)[:640])
        self.assertEqual(len(p.layouts), 2)
        for bubble, font, lines, line_height in p.layouts:
            self.assertLessEqual(len(lines) * line_height, bubble.height - 18)
            self.assertTrue(all(font.size(line)[0] <= bubble.width - 20 for line in lines))

    def test_real_simulation_and_rng_match_without_explanations_in_both_modes(self):
        import pickle
        from world import World
        def run(panel=None):
            np.random.seed(1000)
            w = World()
            w.generation = 1
            state = (0, False, False)
            for _ in range(16):
                w.update_temperature()
                state = (panel.advance(w, main._step_simulation, *state) if panel is not None
                         else main._step_simulation(w, *state))
            return pickle.dumps(w), pickle.dumps(np.random.get_state()), state
        with patch.object(config, 'SEASON_CYCLE', 4), patch.object(config, 'MAX_STEPS_PER_GEN', 2):
            reference = run()
            for ai in (False, True):
                p = self.panel(ai)
                if ai:
                    self.clients[-1].release.set()
                self.assertEqual(run(p), reference)
                self.assertEqual(list(p.annual.entries), [1, 2])


class MainSpeedTests(unittest.TestCase):
    def test_actual_main_speed_changes_and_multiple_years_in_one_frame(self):
        """Use the real 25-steps/frame loop; only shorten months in this test."""
        from world import World
        class Clock:
            def get_time(self): return 0 if phase == 0 else 5000
            def get_fps(self): return 60
            def tick(self, *args): return 1000
        for mode in ('rule', 'ai'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                old_cwd, temperature = Path.cwd(), config.TEMPERATURE
                os.chdir(tmp)
                np.random.seed(1000)
                w = World()
                frames, phase = 0, 0
                captured = []
                class Client:
                    def generate(self, context):
                        captured.append(copy.deepcopy(context))
                        return TEXT
                flip = pygame.display.flip
                def capture():
                    nonlocal frames, phase
                    flip()
                    frames += 1
                    self.assertLess(frames, 40)
                    scope = inspect.currentframe().f_back.f_locals
                    p = scope['status_panel']
                    if phase == 0:
                        if p.ai:
                            p.ai.controller.client = Client()
                        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                          pos=scope['speed_button_rects']['high'].center))
                        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n))
                        phase = 1
                    elif phase == 1:
                        self.assertEqual(scope['speed_level'], 'high')
                        self.assertGreaterEqual(len(p.annual.entries), 2)
                        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
                        phase = 2
                    elif phase == 2:
                        self.assertTrue(scope['paused'])
                        frozen = len(p.annual.entries)
                        p.draw(pygame.display.get_surface(), None, w)
                        self.assertEqual(len(p.annual.entries), frozen)
                        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
                        phase = 3
                    elif phase == 3:
                        self.assertFalse(scope['paused'])
                        self.assertGreaterEqual(len(p.annual.entries), 4)
                        pygame.event.post(pygame.event.Event(pygame.QUIT))
                        phase = 4
                try:
                    with patch.object(config, 'MAX_STEPS_PER_GEN', 1), \
                            patch.object(config, 'MAX_GENERATIONS', 1000), \
                            patch.object(pygame.time, 'Clock', Clock), \
                            patch.object(pygame.display, 'flip', capture):
                        main.run_with_visualization(w, explanation_mode=mode)
                    self.assertEqual(phase, 4)
                    years = [c['year'] for c in captured]
                    self.assertEqual(years, sorted(set(years)))
                finally:
                    pygame.quit()
                    config.TEMPERATURE = temperature
                    os.chdir(old_cwd)


if __name__ == '__main__':
    unittest.main()
