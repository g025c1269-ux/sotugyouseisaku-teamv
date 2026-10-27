import copy
import inspect
import json
import os
from pathlib import Path
import pickle
import random
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/teamv-ai-mpl')

import numpy as np
import pygame
import config
from ai_navigator import AINavigator
from ecosystem_ai_context import EcosystemAIContext, compare_to_mean
from navigator_panel import NavigatorPanel
from ollama_explainer import OllamaError
from world import World

COMMENT = '足の速さと川への適応がいい感じだね！移動の幅を広げやすいけど、たくさん動いた時の蓄えには気をつけよう。'
ANNUAL_COMMENT = '草食たちは年初より仲間が減ったけれど、平均の川適応は上がっているね。川を移動するときの負担を抑えやすい集団になっているのが、注目ポイントだよ！肉食組は数をほぼ保ち、平均の山適応が高めになったみたい。山での移動のしやすさを見てみよう。今年は気温にも変化があったけれど、仲間の増減の理由を気温だけで決めることはできないよ。来年も両方の群れの数と、地形への適応を追いかけていこう！'


class ControlledClient:
    def __init__(self):
        self.entered = Event()
        self.release = Event()
        self.calls = []
        self.error = False

    def generate(self, context):
        self.calls.append(context)
        self.entered.set()
        self.release.wait()  # Deterministic gate; teardown always releases the daemon worker.
        if self.error:
            raise OllamaError('Ollamaにつながらないよ。起動してね。')
        return ANNUAL_COMMENT if context.get('target') == 'annual' else COMMENT


class ContextTests(unittest.TestCase):
    def setUp(self):
        np.random.seed(1000)
        self.world = World()
        self.world.generation = 1
        self.builder = EcosystemAIContext()
        self.temperature = config.TEMPERATURE
        self.mode = config.USE_NEUROEVOLUTION

    def tearDown(self):
        config.TEMPERATURE = self.temperature
        config.USE_NEUROEVOLUTION = self.mode

    def test_live_counts_means_distributions_and_individual_comparisons(self):
        org = self.world.organisms[0]
        org.alive = False
        for species in ('herbivore', 'carnivore'):
            members = [o for o in self.world.organisms if o.alive and o.org_type == species]
            c = self.builder.build(self.world, species)
            self.assertEqual(c['population']['count'], len(members))
            self.assertEqual(c['counts'][species], len(members))
            for key, trait in c['population']['mean_traits'].items():
                self.assertAlmostEqual(trait['value'], sum(o.genes[key] for o in members) / len(members))
                self.assertEqual(sum(c['population']['distribution'][key].values()), len(members))
            selected = members[0]
            selected.genes['speed'] = 1.
            c = self.builder.build(self.world, 'individual', selected)
            self.assertEqual(c['individual']['traits']['speed']['comparison'], '高め')
            self.assertEqual(c['individual']['state']['energy'], selected.energy)
            self.assertEqual(c['individual']['zone'], self.world.get_zone(selected.x, selected.y))
            self.assertTrue(json.dumps(c, ensure_ascii=False, allow_nan=False))

    def test_thresholds_inactive_gene_temperature_and_costs_match_main(self):
        org = self.world.organisms[0]
        org.genes.update(cold_resistance=.9, river_tolerance=.8, speed=.4, hunger_threshold=.9)
        config.TEMPERATURE = 5
        c = self.builder.build(self.world, 'individual', org)
        traits = c['individual']['traits']
        self.assertEqual(traits['river_tolerance']['level'], 'HIGH')
        self.assertEqual(traits['speed']['level'], 'MID')
        self.assertFalse(traits['hunger_threshold']['active'])
        state = c['individual']['state']
        self.assertAlmostEqual(state['temperature_gap'], .775)
        self.assertEqual(state['temperature_cost'], org._calc_temp_penalty(self.world))
        self.assertEqual(state['move_cost_per_cell_here'], org._move_energy_cost(self.world))
        config.USE_NEUROEVOLUTION = False
        c = self.builder.build(self.world, 'individual', org)
        self.assertTrue(c['individual']['traits']['hunger_threshold']['active'])

    def test_none_dead_removed_and_extinct_are_not_sent(self):
        org = self.world.organisms[0]
        for candidate in (None, copy.deepcopy(org)):
            with self.assertRaises(ValueError):
                self.builder.build(self.world, 'individual', candidate)
        org.alive = False
        with self.assertRaises(ValueError):
            self.builder.build(self.world, 'individual', org)
        self.world.organisms.clear()
        for target in ('herbivore', 'carnivore'):
            with self.assertRaises(ValueError):
                self.builder.build(self.world, target)

    def test_mean_comparison_boundaries(self):
        for value, expected in ((.55, '高め'), (.45, '低め'), (.5499, '同じくらい'),
                                (.4501, '同じくらい'), (.5, '同じくらい')):
            self.assertEqual(compare_to_mean(value, .5), expected)

    def test_negative_energy_after_move_is_depleted_not_a_context_error(self):
        org = self.world.organisms[0]
        org.energy = -.1
        context = self.builder.build(self.world, 'individual', org)
        self.assertEqual(context['individual']['state']['energy'], -.1)
        self.assertEqual(context['individual']['state']['energy_ratio_level'], 'LOW')

    def test_snapshot_detaches_from_world_and_does_not_mutate_rng_or_brains(self):
        org = self.world.organisms[0]
        before = pickle.dumps(self.world)
        py_rng, np_rng = random.getstate(), np.random.get_state()
        for target in ('herbivore', 'carnivore', 'individual'):
            context = self.builder.build(self.world, target, org)
        self.assertEqual(pickle.dumps(self.world), before)
        self.assertEqual(random.getstate(), py_rng)
        now = np.random.get_state()
        np.testing.assert_array_equal(now[1], np_rng[1])
        self.assertEqual(now[2:], np_rng[2:])
        serialized = json.dumps(context, sort_keys=True)
        self.world.step()
        org.genes['speed'] = .123
        self.assertEqual(json.dumps(context, sort_keys=True), serialized)

    def test_simulation_and_rng_match_with_context_reads_each_step(self):
        # Recreate with the same seed: deepcopy may reorder the existing food bucket sets.
        np.random.seed(1000)
        reference = World()
        reference.generation = self.world.generation
        rng = np.random.get_state()
        for _ in range(12):
            self.builder.build(self.world, 'herbivore')
            self.builder.build(self.world, 'carnivore')
            self.builder.build(self.world, 'individual', self.world.organisms[0])
            self.world.step()
        final_rng = np.random.get_state()
        np.random.set_state(rng)
        for _ in range(12):
            reference.step()
        np.testing.assert_array_equal(self.world.food_grid, reference.food_grid)
        self.assertEqual(self.world.zone_map, reference.zone_map)
        self.assertEqual(self.world.history, reference.history)
        self.assertEqual(self.world.step_count, reference.step_count)
        self.assertEqual(len(self.world.organisms), len(reference.organisms))
        for actual, expected in zip(self.world.organisms, reference.organisms):
            for key, value in vars(actual).items():
                if key == 'brain':
                    for p, q in zip(actual.brain.params(), expected.brain.params()):
                        np.testing.assert_array_equal(p, q)
                elif isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, vars(expected)[key])
                else:
                    self.assertEqual(value, vars(expected)[key])
        np.testing.assert_array_equal(np.random.get_state()[1], final_rng[1])
        self.assertEqual(np.random.get_state()[2:], final_rng[2:])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        np.random.seed(1000)
        self.world = World()
        self.client = ControlledClient()
        self.nav = AINavigator(self.client)
        self.nav.target = 'herbivore'  # legacy client entry point; UI uses annual/individual
        self.nav.sync(self.world, self.world.organisms[0])

    def tearDown(self):
        self.client.release.set()
        self.nav.close()

    def finish(self):
        self.client.release.set()
        deadline = time.monotonic() + 3
        while self.nav.busy and time.monotonic() < deadline:
            self.nav.poll()
            time.sleep(.002)
        self.assertFalse(self.nav.busy)

    def test_manual_only_single_request_and_background_generation(self):
        for _ in range(10):
            self.nav.sync(self.world, self.world.organisms[0])
        self.assertFalse(self.client.calls)
        self.assertTrue(self.nav.request())
        self.assertTrue(self.client.entered.wait(1))
        self.assertFalse(self.nav.request())
        start = self.world.step_count
        for _ in range(3):
            self.world.step()
            self.nav.sync(self.world, self.world.organisms[0])
        self.assertGreater(self.world.step_count, start)
        self.assertTrue(self.nav.busy)
        self.finish()
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.nav.comments['herbivore'].text, COMMENT)
        self.assertEqual(self.nav.comments['herbivore'].stamp[1], start)

    def test_target_switch_routes_result_without_showing_other_target(self):
        self.nav.request()
        self.nav.target = 'carnivore'
        self.finish()
        self.assertNotIn('carnivore', self.nav.comments)
        self.assertEqual(self.nav.comments['herbivore'].text, COMMENT)

    def test_selection_changed_away_and_back_discards_late_result(self):
        original, other = self.world.organisms[:2]
        self.nav.target = 'individual'
        self.nav.request()
        self.nav.sync(self.world, other)
        self.nav.sync(self.world, original)
        self.finish()
        self.assertNotIn('individual', self.nav.comments)

    def test_death_removal_and_world_rewind_discard_results(self):
        for invalidation in ('death', 'removal', 'rewind'):
            org = self.world.organisms[0]
            self.client.release.clear()
            self.nav.target = 'individual'
            self.nav.sync(self.world, org)
            self.nav.request()
            if invalidation == 'death':
                org.alive = False
            elif invalidation == 'removal':
                self.world.organisms.remove(org)
            else:
                self.world = copy.deepcopy(self.world)
            self.nav.sync(self.world, org)
            self.finish()
            self.assertNotIn('individual', self.nav.comments)
            self.world.organisms = [o for o in self.world.organisms if o.alive]

    def test_error_fallback_and_close_without_waiting(self):
        self.client.error = True
        self.nav.request()
        self.finish()
        self.assertIn('つながらない', self.nav.comments['herbivore'].error)
        self.client.release.clear()
        self.nav.request()
        self.assertTrue(self.client.entered.wait(1))
        start = time.monotonic()
        self.nav.close()
        self.assertLess(time.monotonic() - start, .1)
        self.assertFalse(self.nav.request())
        self.finish()
        self.assertFalse(self.nav.comments)

    def test_no_selection_and_empty_population_do_not_start_worker(self):
        self.nav.sync(self.world, None)
        self.nav.target = 'individual'
        self.assertFalse(self.nav.request())
        self.world.organisms.clear()
        self.nav.target = 'carnivore'
        self.assertFalse(self.nav.request())
        self.assertFalse(self.client.calls)

    def test_bad_settings_do_not_block_startup_and_fall_back_on_manual_request(self):
        self.nav.client = None
        with patch('ollama_explainer.OllamaSettings.load', side_effect=OllamaError('AI設定を確認してね。')) as load:
            self.nav.sync(self.world, None)
            load.assert_not_called()
            self.assertTrue(self.nav.request())
            self.finish()
            self.assertIn('AI設定', self.nav.comments['herbivore'].error)
            load.assert_called_once()


class AIPanelTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = pygame.display.set_mode((1040, 640))
        np.random.seed(1000)
        self.world = World()
        self.panel = NavigatorPanel((640, 0, 400, 640))
        self.client = ControlledClient()
        self.panel.ai.controller.client = self.client
        self.out = tempfile.TemporaryDirectory()
        self.panel.ai.controller.annual.log_path = Path(self.out.name) / 'annual.json'

    def tearDown(self):
        self.client.release.set()
        self.panel.close()
        pygame.quit()
        self.out.cleanup()

    def click(self, rect, selected=None):
        self.panel.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center), selected, self.world)

    def draw(self, selected=None):
        self.panel.draw(self.screen, selected, self.world)

    def test_ui_individual_pending_fallback_wrap_and_map_untouched(self):
        self.screen.fill((30, 75, 48))
        before = pygame.surfarray.array3d(self.screen)[:640].copy()
        self.panel.open = True
        self.click(self.panel.ai_rect)
        self.draw()
        self.assertEqual(self.panel.ai.controller.target, 'annual')
        self.assertFalse(self.client.calls)
        org = self.world.organisms[0]
        self.click(self.panel.ai.tabs['individual'], org)
        self.draw(org)
        self.click(self.panel.ai.update_rect, org)
        self.assertTrue(self.client.entered.wait(1))
        for _ in range(4):
            self.world.step()
            self.draw(org)
            pygame.event.pump()
        self.assertTrue(self.panel.ai.controller.busy)
        for target in ('annual', 'individual'):
            self.click(self.panel.ai.tabs[target], org)
            self.draw(org)
            for bubble, font, lines, line_height in self.panel.layouts:
                self.assertLessEqual(len(lines) * line_height, bubble.height - 18)
                self.assertTrue(all(font.size(line)[0] <= bubble.width - 20 for line in lines))
        np.testing.assert_array_equal(before, pygame.surfarray.array3d(self.screen)[:640])
        self.client.release.set()
        deadline = time.monotonic() + 2
        while self.panel.ai.controller.busy and time.monotonic() < deadline:
            self.draw(org)
            time.sleep(.002)
        self.assertEqual(self.panel.ai.controller.comments['individual'].text, COMMENT)
        self.client.error = True
        self.click(self.panel.ai.update_rect, org)
        deadline = time.monotonic() + 2
        while self.panel.ai.controller.busy and time.monotonic() < deadline:
            self.draw(org)
            time.sleep(.002)
        self.assertIn('つながらない', self.panel.ai.controller.comments['individual'].error)
        self.click(self.panel.detail_rect, org)
        self.assertEqual(self.panel.view, 'overview')

    def test_history_buttons_keep_previous_while_next_year_pending(self):
        from annual_report import AnnualRecorder
        self.world.generation = 1
        recorder = AnnualRecorder()
        recorder.before_step(self.world)
        self.world.generation = config.SEASON_CYCLE
        recorder.before_step(self.world)
        c = recorder.after_step(self.world, True, False, False)
        history = self.panel.ai.controller.annual
        for year in (1, 2):
            context = copy.deepcopy(c)
            context['year'] = year
            history.add(context)
            history.entries[year].update(status='ready', text=ANNUAL_COMMENT)
        self.panel.open = True
        self.click(self.panel.ai_rect)
        self.draw()
        self.assertEqual(history.displayed()['context']['year'], 2)
        self.click(self.panel.ai.previous_rect)
        self.draw()
        self.assertEqual(history.displayed()['context']['year'], 1)
        self.click(self.panel.ai.next_rect)
        self.assertEqual(history.displayed()['context']['year'], 2)
        self.click(self.panel.ai.latest_rect)
        self.assertIsNone(history.selected_year)
        context = copy.deepcopy(c)
        context['year'] = 3
        history.add(context)
        self.draw()
        self.assertEqual(history.displayed()['context']['year'], 2)
        for bubble, font, lines, line_height in self.panel.layouts:
            self.assertLessEqual(len(lines) * line_height, bubble.height - 18)
        # The expanded annual comment must fit at the maximum accepted length too.
        self.panel.layouts = []
        self.panel._card(self.screen, 225, 240, '年間総括', '', '草食と肉食' + 'あ' * 185, (173, 209, 138))
        for bubble, font, lines, line_height in self.panel.layouts:
            self.assertLessEqual(len(lines) * line_height, bubble.height - 18)
            self.assertTrue(all(font.size(line)[0] <= bubble.width - 20 for line in lines))


class GameAITests(unittest.TestCase):
    def test_finished_simulation_stays_open_for_pending_report_until_user_quits(self):
        import main
        np.random.seed(1000)
        world = World()
        client = ControlledClient()
        real_flip = pygame.display.flip
        frames, done_frames = 0, 0
        old_cwd, old_temperature = Path.cwd(), config.TEMPERATURE
        with tempfile.TemporaryDirectory() as tmp:
            def capture():
                nonlocal frames, done_frames
                real_flip()
                frames += 1
                self.assertLess(frames, 80)
                scope = inspect.currentframe().f_back.f_locals
                controller = scope['status_panel'].ai.controller
                controller.client = client
                if scope['done']:
                    done_frames += 1
                    if done_frames == 4:
                        self.assertTrue(controller.busy)
                        client.release.set()
                    if done_frames > 4 and not controller.busy:
                        self.assertTrue(controller.annual.displayed()['context']['partial'])
                        pygame.event.post(pygame.event.Event(pygame.QUIT))
            try:
                os.chdir(tmp)
                with patch.object(config, 'MAX_STEPS_PER_GEN', 1), patch.object(config, 'MAX_GENERATIONS', 1), patch.object(pygame.display, 'flip', capture):
                    main.run_with_visualization(world)
            finally:
                client.release.set()
                config.TEMPERATURE = old_temperature
                os.chdir(old_cwd)
                pygame.quit()
        self.assertGreater(done_frames, 4)

    def test_actual_game_annual_boundary_controls_individual_and_exit(self):
        import main
        np.random.seed(1000)
        world = World()
        client = ControlledClient()
        stage, frames, pending_frames = 0, 0, 0
        start_step = 0
        real_flip = pygame.display.flip
        old_temperature = config.TEMPERATURE
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            def click(rect):
                pos = rect.center if isinstance(rect, pygame.Rect) else rect
                for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                    pygame.event.post(pygame.event.Event(kind, button=1, pos=pos))

            def key(k):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k))

            def save(name):
                out = Path(os.environ.get('AI_SCREENSHOT_DIR', tmp))
                out.mkdir(parents=True, exist_ok=True)
                pygame.image.save(pygame.display.get_surface(), out / name)

            def capture():
                nonlocal stage, frames, pending_frames, start_step
                real_flip()
                frames += 1
                self.assertLess(frames, 160)
                scope = inspect.currentframe().f_back.f_locals
                panel = scope['status_panel']
                controller = panel.ai.controller
                if stage == 0:
                    controller.client = client
                    key(pygame.K_n)
                    click(panel.ai_rect)
                    key(pygame.K_m)
                    stage = 1
                elif stage == 1:
                    self.assertFalse(client.calls)
                    self.assertTrue(scope['paused'])
                    for _ in range(config.SEASON_CYCLE):
                        key(pygame.K_RIGHT)
                    stage = 2
                elif stage == 2:
                    self.assertTrue(controller.busy)
                    self.assertEqual(list(controller.annual.entries), [1])
                    start_step = world.step_count
                    key(pygame.K_e)
                    key(pygame.K_v)
                    key(pygame.K_2)
                    key(pygame.K_SPACE)
                    stage = 3
                elif stage == 3:
                    pending_frames += 1
                    self.assertTrue(controller.busy, str((world.step_count, start_step, scope['paused'], scope['done'], controller.annual.entries)))
                    if pending_frames >= 6 and world.step_count > start_step:
                        self.assertFalse(scope['renderer'].show_food)
                        self.assertFalse(scope['renderer'].show_season_fx)
                        save('31_annual_pending_mock.png')
                        if not scope['paused']:
                            key(pygame.K_SPACE)
                        client.release.set()
                        stage = 4
                elif stage == 4 and not controller.busy:
                    self.assertEqual(controller.annual.displayed()['text'], ANNUAL_COMMENT)
                    self.assertEqual(controller.annual.displayed()['context']['year'], 1)
                    save('32_annual_completed_mock.png')
                    renderer = scope['renderer']
                    for org in world.organisms:
                        pos = (org.y * renderer.zoom + renderer.zoom // 2 - renderer.off_x,
                               org.x * renderer.zoom + renderer.zoom // 2 - renderer.off_y)
                        if (20 < pos[0] < 620 and 35 < pos[1] < 620
                                and renderer.minimap_hit(*pos) is None and renderer.find_org(world, *pos) is org):
                            click(pos)
                            break
                    else:
                        self.fail('No selectable organism')
                    stage = 5
                elif stage == 5:
                    self.assertIsNotNone(scope['selected_org'])
                    click(panel.ai.tabs['individual'])
                    click(panel.ai.update_rect)
                    stage = 6
                elif stage == 6 and not controller.busy:
                    self.assertEqual(controller.comments['individual'].text, COMMENT)
                    save('33_annual_individual_mock.png')
                    client.release.clear()
                    client.entered.clear()
                    click(panel.ai.update_rect)
                    stage = 7
                elif stage == 7 and client.entered.is_set():
                    self.assertTrue(controller.busy)
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    stage = 8
            try:
                os.chdir(tmp)
                # Shorten steps per generation only in this test; retain the real 12-generation year.
                with patch.object(config, 'MAX_STEPS_PER_GEN', 2), patch.object(main, 'MAX_STEPS_PER_FRAME', 1), patch.object(pygame.display, 'flip', capture):
                    main.run_with_visualization(world)
            finally:
                client.release.set()
                config.TEMPERATURE = old_temperature
                os.chdir(old_cwd)
                pygame.quit()
        self.assertEqual(stage, 8)
        self.assertEqual(client.calls[0]['target'], 'annual')
        self.assertEqual(sum(c['target'] == 'annual' for c in client.calls), 1)
        self.assertFalse(pygame.get_init())


if __name__ == '__main__':
    unittest.main()
