"""Annual boundaries, detached inputs, ordered requests, persistence and replay."""
import copy
import json
from pathlib import Path
import random
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import config
from ai_navigator import AINavigator
from annual_report import AnnualRecorder, annual_fallback
from organism import Organism
from ollama_explainer import OllamaError


TEXT = '草食たちは年初より仲間が減ったけれど、平均の川適応は上がっているね。川を移動するときの負担を抑えやすい集団になっているのが、注目ポイントだよ！肉食組は数をほぼ保ち、平均の山適応が高めになったみたい。山での移動のしやすさを見てみよう。今年は気温にも変化があったけれど、仲間の増減の理由を気温だけで決めることはできないよ。来年も両方の群れの数と、地形への適応を追いかけていこう！'


def world():
    genes = {k: .5 for k in ('cold_resistance', 'speed', 'metabolism', 'hunger_threshold', 'river_tolerance', 'mountain_tolerance')}
    return SimpleNamespace(generation=1, step_count=0, land_ratio=.7, food_grid=np.ones((2, 2), dtype=bool),
                           organisms=[Organism(0, 0, s, genes) for s in ('herbivore', 'carnivore')],
                           get_zone=lambda x, y: 'grassland')


def advance_generation(w, step, extinct, done):
    w.step_count += config.MAX_STEPS_PER_GEN
    w.generation += 1
    return 0, False, False


class SlowClient:
    def __init__(self):
        self.entered = Event()
        self.release = Event()
        self.calls = []
        self.error = False
        self.active, self.max_active = 0, 0

    def generate(self, context):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append(copy.deepcopy(context))
        self.entered.set()
        try:
            if not self.release.wait(5):
                raise OllamaError('時間切れ')
            if self.error:
                raise OllamaError('Ollama未起動')
            return TEXT
        finally:
            self.active -= 1


class AnnualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.temperature = config.TEMPERATURE
        self.w = world()
        self.client = SlowClient()
        self.nav = AINavigator(self.client, Path(self.tmp.name) / 'report.json')

    def tearDown(self):
        self.client.release.set()
        self.nav.close()
        self.finish()  # Drain the finished worker before removing its diagnostic directory.
        config.TEMPERATURE = self.temperature
        self.tmp.cleanup()

    def year(self, n=1):
        for _ in range(config.SEASON_CYCLE * n):
            config.TEMPERATURE = 5 + self.w.generation
            self.nav.advance(self.w, advance_generation, 0, False, False)

    def finish(self):
        self.client.release.set()
        deadline = time.monotonic() + 2
        while self.nav.busy and time.monotonic() < deadline:
            self.nav.poll()
            time.sleep(.002)
        self.assertFalse(self.nav.busy)

    def test_existing_twelve_generation_year_boundary_no_frame_pause_duplicates(self):
        for _ in range(config.SEASON_CYCLE - 1):
            self.nav.advance(self.w, advance_generation, 0, False, False)
            self.nav.poll()
        self.assertFalse(self.client.calls)
        self.nav.advance(self.w, advance_generation, 0, False, False)
        self.assertTrue(self.client.entered.wait(1))
        for _ in range(40):
            self.nav.poll()
            self.assertFalse(hasattr(self.nav, 'request'))  # no manual/individual request API
        self.assertEqual(len(self.client.calls), 1)
        c = self.client.calls[0]
        self.assertEqual(c['year'], 1)
        self.assertEqual(c['start']['generation'], 1)
        self.assertEqual(c['end']['generation'], config.SEASON_CYCLE)
        self.assertEqual(c['end']['step'], config.SEASON_CYCLE * config.MAX_STEPS_PER_GEN)
        self.assertFalse(c['partial'])

    def test_exact_counts_trait_deltas_distribution_and_temperature(self):
        recorder = self.nav.annual.recorder
        config.TEMPERATURE = 5
        recorder.before_step(self.w)
        self.w.organisms[0].genes['speed'] = .9
        self.w.organisms[0].genes['hunger_threshold'] = .9
        self.w.organisms.append(copy.deepcopy(self.w.organisms[0]))
        self.w.organisms[1].alive = False
        self.w.generation = config.SEASON_CYCLE
        self.w.step_count = 200
        config.TEMPERATURE = 30
        recorder.before_step(self.w)
        context = recorder.after_step(self.w, True, False, False)
        herbs, carns = context['changes']['herbivore'], context['changes']['carnivore']
        self.assertEqual((herbs['start_count'], herbs['end_count'], herbs['count_delta']), (1, 2, 1))
        self.assertAlmostEqual(herbs['traits']['speed']['delta'], .4)
        self.assertEqual(herbs['end_distribution']['speed']['HIGH'], 2)
        self.assertEqual((carns['start_count'], carns['end_count'], carns['count_delta']), (1, 0, -1))
        self.assertIsNone(carns['traits']['speed']['end'])
        self.assertIsNone(carns['traits']['speed']['delta'])
        self.assertEqual(context['environment']['temperature_delta'], 25)
        self.assertEqual(context['environment']['observed_temperature_min'], 5)
        self.assertEqual(context['environment']['observed_temperature_max'], 30)
        self.assertIsNone(context['environment']['events'])
        self.assertFalse(any('繁殖' in r['label'] for r in context['notable_trait_changes']))
        text = annual_fallback(context)
        self.assertIn('草食', text)
        self.assertIn('肉食', text)

    def test_slow_ai_queues_three_years_without_mixing_and_one_request_at_a_time(self):
        self.year(3)
        self.assertTrue(self.client.entered.wait(1))
        self.assertEqual(list(self.nav.annual.entries), [1, 2, 3])
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.w.generation, 37)
        self.w.organisms.clear()
        self.finish()
        self.assertEqual([c['year'] for c in self.client.calls], [1, 2, 3])
        self.assertEqual([c['changes']['herbivore']['start_count'] for c in self.client.calls], [1, 1, 1])
        self.assertEqual(self.client.max_active, 1)
        self.assertEqual(self.nav.annual.displayed()['context']['year'], 3)

    def test_keep_previous_until_new_response_ready_and_navigate_history(self):
        self.year()
        self.finish()
        self.client.release.clear()
        self.year()
        self.assertEqual(self.nav.annual.displayed()['context']['year'], 1)
        self.finish()
        self.assertEqual(self.nav.annual.displayed()['context']['year'], 2)
        self.nav.annual.navigate(-1)
        self.assertEqual(self.nav.annual.displayed()['context']['year'], 1)
        self.nav.annual.navigate(1)
        self.assertEqual(self.nav.annual.displayed()['context']['year'], 2)

    def test_rewind_completed_year_does_not_regenerate_or_destroy_pending_result(self):
        initial = copy.deepcopy(self.w)
        self.year()
        self.w = initial
        self.nav.poll()
        self.year()
        self.finish()
        self.assertEqual([c['year'] for c in self.client.calls], [1])
        self.assertEqual(self.nav.annual.displayed()['context']['year'], 1)

    def test_partial_extinction_and_max_generation_records_once(self):
        for extinct in (True, False):
            recorder = AnnualRecorder()
            w = world()
            recorder.before_step(w)
            w.step_count += 10
            w.organisms.clear()
            c = recorder.after_step(w, False, True, extinct)
            self.assertTrue(c['partial'])
            self.assertEqual(c['reason'], 'extinction' if extinct else 'simulation_end')
            self.assertEqual(c['changes']['herbivore']['end_count'], 0)
            self.assertIn('途中', annual_fallback(c))
            self.assertIn('比べられる平均形質がない', annual_fallback(c))
            self.assertIsNone(recorder.after_step(w, True, True, extinct))

    def test_failed_model_falls_back_and_audit_json_contains_exact_input_and_answer(self):
        self.client.error = True
        self.year()
        self.finish()
        row = self.nav.annual.displayed()
        self.assertEqual(row['status'], 'fallback')
        self.assertTrue(row['fallback'])
        data = json.loads(self.nav.annual.log_path.read_text(encoding='utf-8'))
        self.assertEqual(data['reports'][0]['context'], self.client.calls[0])
        self.assertEqual(data['reports'][0]['error'], 'Ollama未起動')
        self.client.error = False
        self.year()
        self.finish()
        data = json.loads(self.nav.annual.log_path.read_text(encoding='utf-8'))
        self.assertEqual(data['reports'][1]['text'], TEXT)
        self.assertEqual(data['reports'][1]['raw_response'], TEXT)
        self.assertEqual(data['reports'][1]['request']['context'], self.client.calls[1])

    def test_no_individual_request_state_or_api(self):
        for name in ('context', 'target', 'comments', '_selected', 'request', 'sync'):
            self.assertFalse(hasattr(self.nav, name), name)

    def test_close_records_pending_fallback_without_waiting(self):
        self.year(2)
        start = time.monotonic()
        self.nav.close()
        self.assertLess(time.monotonic() - start, .2)
        data = json.loads(self.nav.annual.log_path.read_text(encoding='utf-8'))
        self.assertTrue(all(r['status'] == 'interrupted' and r['fallback'] for r in data['reports']))

    def test_unwritable_log_keeps_game_history_and_fallback_available(self):
        blocked = Path(self.tmp.name) / 'blocked'
        blocked.write_text('file, not directory')
        self.nav.annual.log_path = blocked / 'annual.json'
        self.client.error = True
        self.year()
        self.finish()
        self.assertTrue(self.nav.annual.save_error)
        self.assertEqual(self.nav.annual.displayed()['status'], 'fallback')

    def test_recorder_reads_do_not_mutate_world_genes_or_rng(self):
        from world import World
        import pickle
        w = World()
        w.generation = 1
        before = pickle.dumps(w)
        np_rng, py_rng = np.random.get_state(), random.getstate()
        self.nav.annual.recorder.before_step(w)
        self.assertEqual(pickle.dumps(w), before)
        np.testing.assert_array_equal(np.random.get_state()[1], np_rng[1])
        self.assertEqual(np.random.get_state()[2:], np_rng[2:])
        self.assertEqual(random.getstate(), py_rng)

    def test_changed_calendar_and_midyear_start_are_not_assumed_one_generation_per_year(self):
        with patch.object(config, 'SEASON_CYCLE', 4):
            recorder = AnnualRecorder()
            self.w.generation = 2
            recorder.before_step(self.w)
            self.w.generation = 4
            recorder.before_step(self.w)
            c = recorder.after_step(self.w, True, False, False)
            self.assertEqual(c['generations_per_year'], 4)
            self.assertTrue(c['partial'])

    def test_actual_main_step_results_match_with_and_without_annual_observer(self):
        from world import World
        from main import _step_simulation
        def run(observe):
            np.random.seed(1000)
            w = World()
            w.generation = 1
            step = 0
            for _ in range(12):
                w.update_temperature()
                if observe:
                    step, _, _ = self.nav.advance(w, _step_simulation, step, False, False)
                else:
                    step, _, _ = _step_simulation(w, step, False, False)
            return w, np.random.get_state()
        self.client.release.set()
        with patch.object(config, 'SEASON_CYCLE', 4), patch.object(config, 'MAX_STEPS_PER_GEN', 2):
            # Construct the observer after choosing this test's shortened calendar.
            self.nav.annual.recorder = AnnualRecorder()
            reference, rng = run(False)
            observed, actual_rng = run(True)
        np.testing.assert_array_equal(reference.food_grid, observed.food_grid)
        self.assertEqual(reference.history, observed.history)
        self.assertEqual(len(reference.organisms), len(observed.organisms))
        for a, b in zip(reference.organisms, observed.organisms):
            for key, value in vars(a).items():
                if key == 'brain':
                    for p, q in zip(a.brain.params(), b.brain.params()):
                        np.testing.assert_array_equal(p, q)
                elif isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, vars(b)[key])
                else:
                    self.assertEqual(value, vars(b)[key])
        np.testing.assert_array_equal(rng[1], actual_rng[1])
        self.assertEqual(rng[2:], actual_rng[2:])


if __name__ == '__main__':
    unittest.main()
