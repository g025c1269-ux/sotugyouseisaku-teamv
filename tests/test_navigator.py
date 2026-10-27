import copy
import random
import re
from types import SimpleNamespace
import unittest

import numpy as np

from navigator_explainer import NavigatorExplainer, CORE


def animal(species='herbivore', **genes):
    values = {k:.5 for k in (*CORE, 'hunger_threshold')}
    values.update(genes)
    return SimpleNamespace(org_type=species, alive=True, genes=values,
                           energy=60., max_energy=100., age=0, x=0, y=0)


class NavigatorTests(unittest.TestCase):
    def setUp(self):
        self.engine = NavigatorExplainer()

    def test_means_distribution_and_dead_exclusion(self):
        members = [animal(river_tolerance=.9) for _ in range(8)] + [animal(river_tolerance=.2) for _ in range(2)]
        dead = animal(river_tolerance=0)
        dead.alive = False
        r = self.engine.population(members + [dead, animal('carnivore')], 'herbivore', 20)
        self.assertEqual(r['count'], 10)
        self.assertAlmostEqual(r['means']['river_tolerance'], .76)
        self.assertEqual(r['distribution']['river_tolerance'], {'LOW':2, 'MID':0, 'HIGH':8})
        # Two LOW animals do not meet the 25% mixed-population rule.
        self.assertEqual(r['profile'], 'river_high')

    def test_polarized_average_is_not_balance(self):
        members = [animal(speed=v) for v in [.1]*5 + [.9]*5]
        r = self.engine.population(members, 'herbivore', 20)
        self.assertAlmostEqual(r['means']['speed'], .5)
        self.assertEqual(r['profile'], 'mixed')
        self.assertEqual(r['balanced_fraction'], 0)
        r = self.engine.population([animal() for _ in range(10)], 'herbivore', 20)
        self.assertEqual(r['profile'], 'balanced')
        self.assertEqual(r['balanced_fraction'], 1)

    def test_joint_relationship_needs_same_animals(self):
        members = [animal(speed=.9, river_tolerance=.5) for _ in range(4)]
        members += [animal(speed=.5, river_tolerance=.1) for _ in range(4)]
        members += [animal(speed=.9, river_tolerance=.1) for _ in range(2)]
        r = self.engine.population(members, 'herbivore', 20)
        self.assertNotEqual(r['profile'], 'speed_river')
        r = self.engine.population([animal(speed=.9, river_tolerance=.1) for _ in range(10)], 'herbivore', 20)
        self.assertEqual(r['profile'], 'speed_river')

    def test_extinction_single_and_no_selection(self):
        self.assertEqual(self.engine.population([], 'herbivore', 20)['count'], 0)
        r = self.engine.population([animal()], 'herbivore', 20)
        self.assertIn('1匹', r['text'])
        self.assertEqual(self.engine.individual(None, 20)['profile'], 'none')
        dead = animal()
        dead.alive = False
        self.assertEqual(self.engine.individual(dead, 20)['profile'], 'none')

    def test_short_text_all_profiles_and_variations(self):
        for variants in self.engine.text['profiles'].values():
            self.assertGreaterEqual(len(variants), 2)
            for text in variants:
                sentences = [s for s in re.split('[。！？]', text) if s.strip()]
                self.assertGreaterEqual(len(sentences), 2)
                self.assertLessEqual(len(sentences), 4)
                self.assertLessEqual(len(text), 120)
        a = self.engine.population([animal(river_tolerance=.9)]*10, 'herbivore', 20)
        b = self.engine.population([animal('carnivore', river_tolerance=.9)]*10, 'carnivore', 20)
        self.assertNotEqual(a['text'], b['text'])
        self.assertEqual(a, self.engine.population([animal(river_tolerance=.9)]*10, 'herbivore', 20))

    def test_temperature_and_unused_gene_do_not_invent_advantages(self):
        a = animal(cold_resistance=.9, hunger_threshold=.1)
        b = animal(cold_resistance=.9, hunger_threshold=.9)
        first = self.engine.individual(a, 5)
        self.assertEqual(first['text'], self.engine.individual(b, 5)['text'])
        self.assertIn('寒い今', first['text'])
        self.assertNotIn('寒さに強い', first['text'])
        self.assertNotIn('逃げるのが得意', first['text'])
        self.assertNotIn('最優先', first['text'])

    def test_reads_do_not_mutate_state_or_rng(self):
        members = [animal(), animal('carnivore')]
        before = copy.deepcopy(members)
        py_rng, np_rng = random.getstate(), np.random.get_state()
        for species in ('herbivore', 'carnivore'):
            self.engine.population(members, species, 5)
            self.engine.individual(members[0], 5)
        self.assertEqual([vars(a) for a in members], [vars(a) for a in before])
        self.assertEqual(random.getstate(), py_rng)
        after = np.random.get_state()
        np.testing.assert_array_equal(np_rng[1], after[1])
        self.assertEqual(np_rng[2:], after[2:])


class NavigatorLayoutTests(unittest.TestCase):
    def setUp(self):
        import os
        os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        import pygame
        from navigator_panel import NavigatorPanel
        pygame.init()
        self.pg = pygame
        self.screen = pygame.display.set_mode((1040, 640))
        self.panel = NavigatorPanel((640, 0, 400, 640))
        self.assertFalse(self.panel.open)  # latest main opens the legacy panel first
        self.panel.open = True
        self.world = SimpleNamespace(organisms=[animal(), animal('carnivore')], step_count=0)

    def tearDown(self):
        self.pg.quit()

    def test_unselected_three_cards_refresh_and_map_preservation(self):
        self.screen.fill((85, 25, 60))
        before = self.pg.surfarray.array3d(self.screen)[:640].copy()
        self.panel.draw(self.screen, None, self.world)
        self.assertTrue(self.panel.open)
        self.assertEqual(len(self.panel.layouts), 3)
        self.assertEqual(self.panel.individual['profile'], 'none')
        np.testing.assert_array_equal(before, self.pg.surfarray.array3d(self.screen)[:640])
        self.world.organisms.clear()
        self.world.step_count += 1
        self.panel.draw(self.screen, None, self.world)
        self.assertTrue(all(r['count'] == 0 for r in self.panel.cards.values()))
        # A rewound/replaced world with the same step count must refresh too.
        replacement = SimpleNamespace(organisms=[animal()], step_count=1)
        self.panel.draw(self.screen, None, replacement)
        self.assertEqual(self.panel.cards['herbivore']['count'], 1)

    def test_all_wordings_fit_speech_bubbles(self):
        for variants in self.panel.explainer.text['profiles'].values():
            for text in variants:
                self.panel.layouts = []
                self.panel._card(self.screen, 78, 173, 'テスト', '', text + self.panel.explainer.text['energy_low'], (180,210,140))
                for bubble, font, lines, line_height in self.panel.layouts:
                    self.assertLessEqual(len(lines) * line_height, bubble.height - 18)
                    self.assertTrue(all(font.size(line)[0] <= bubble.width - 20 for line in lines))
                    self.assertGreaterEqual(bubble.left, 640)
                    self.assertLessEqual(bubble.right, 1040)

    def test_keys_and_wheel_do_not_steal_map_controls(self):
        from unittest.mock import patch
        pg = self.pg
        self.assertFalse(self.panel.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_d), None))
        self.assertFalse(self.panel.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_v), None))
        self.assertFalse(self.panel.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_e), None))
        event = pg.event.Event(pg.MOUSEWHEEL, y=1, x=0)
        with patch.object(pg.mouse, 'get_pos', return_value=(320, 200)):
            self.assertFalse(self.panel.handle_event(event, None))
        with patch.object(pg.mouse, 'get_pos', return_value=(900, 200)):
            self.assertTrue(self.panel.handle_event(event, None))
        self.assertTrue(self.panel.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_n), None))
        self.assertFalse(self.panel.open)
        self.panel.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_n), None)
        self.assertTrue(self.panel.open)


if __name__ == '__main__':
    unittest.main()
