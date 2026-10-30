"""Preserve selection and read-only numeric inspection, without individual prose."""
import copy
import inspect
import os
from pathlib import Path
import pickle
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('MPLBACKEND', 'Agg')

import numpy as np
import pygame
import config
import main
from navigator_panel import NavigatorPanel
from organism import Organism
from status_panel import StatusPanel
from world import World


class NumericPanelTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = pygame.display.set_mode((1040, 640))
        self.org = Organism(0, 0, 'herbivore')
        self.w = SimpleNamespace(organisms=[self.org], get_zone=lambda x, y: 'grassland')
        self.panel = StatusPanel((640, 0, 400, 640))

    def tearDown(self):
        pygame.quit()

    def test_selected_status_values_refresh_without_commentary(self):
        self.panel.draw(self.screen, self.org, self.w)
        text = '\n'.join(t for t, _ in self.panel.lines)
        self.assertIn(f'{self.org.energy:.3f}', text)
        self.assertIn(f'{self.org.genes["speed"]:.6f}', text)
        for prohibited in ('総合解説', '長所', '短所', 'この個体', '環境との関係'):
            self.assertNotIn(prohibited, text)
        self.org.energy -= 1
        self.panel.draw(self.screen, self.org, self.w)
        self.assertEqual(self.panel.signature[1], self.org.energy)
        self.assertNotEqual(text, '\n'.join(t for t, _ in self.panel.lines))
        for _ in range(5):
            with patch.object(pygame.mouse, 'get_pos', return_value=(900, 400)):
                self.panel.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1), self.org)
        self.assertGreater(self.panel.scroll, 0)
        self.assertLessEqual(self.panel.scroll, self.panel.max_scroll)

    def test_reading_status_does_not_modify_animal_brain_or_rng(self):
        before, rng = pickle.dumps(self.org), pickle.dumps(np.random.get_state())
        self.panel.draw(self.screen, self.org, self.w)
        self.assertEqual(pickle.dumps(self.org), before)
        self.assertEqual(pickle.dumps(np.random.get_state()), rng)

    def test_both_navigators_leave_click_selection_to_main_and_keep_numeric_tab(self):
        for ai in (False, True):
            p = NavigatorPanel((640, 0, 400, 640), ai_enabled=ai)
            self.w.step_count = 0
            p.draw(self.screen, self.org, self.w)
            self.assertFalse(p.open)
            p.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB), self.org, self.w)
            p.draw(self.screen, self.org, self.w)
            self.assertTrue(p.open)
            self.assertEqual(p.view, 'detail')
            self.assertEqual(p.detail.signature[1], self.org.energy)
            self.assertFalse(hasattr(p, 'individual'))
            if ai:
                self.assertFalse(p.ai.controller.busy)
            p.close()


class MainSelectionTests(unittest.TestCase):
    def test_actual_click_numeric_status_follow_controls_and_quit_in_both_modes(self):
        for mode in ('rule', 'ai'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                previous, temperature = Path.cwd(), config.TEMPERATURE
                os.chdir(tmp)
                np.random.seed(1000)
                w = World()
                selected, phase, frames = None, 0, 0
                flip = pygame.display.flip
                def key(k): pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k))
                def capture():
                    nonlocal phase, selected, frames
                    flip()
                    frames += 1
                    self.assertLess(frames, 40)
                    scope = inspect.currentframe().f_back.f_locals
                    p, renderer = scope['status_panel'], scope['renderer']
                    if phase == 0:
                        self.assertFalse(p.open)
                        key(pygame.K_SPACE)
                        for org in w.organisms:
                            pos = (org.y*renderer.zoom+renderer.zoom//2-renderer.off_x,
                                   org.x*renderer.zoom+renderer.zoom//2-renderer.off_y)
                            if 16 < pos[0] < 620 and 32 < pos[1] < 620 and renderer.minimap_hit(*pos) is None and renderer.find_org(w, *pos) is org:
                                selected = org
                                break
                        self.assertIsNotNone(selected)
                        for t in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                            pygame.event.post(pygame.event.Event(t, button=1, pos=pos))
                    elif phase == 1:
                        self.assertIs(scope['selected_org'], selected)
                        self.assertFalse(p.open)  # original main numeric panel stays visible
                        key(pygame.K_f)
                        key(pygame.K_TAB)
                    elif phase == 2:
                        self.assertTrue(scope['follow'])
                        self.assertEqual(p.view, 'detail')
                        self.assertEqual(p.detail.signature[1], selected.energy)
                        self.assertFalse(any('総合解説' in line for line, _ in p.detail.lines))
                        key(pygame.K_TAB)
                    elif phase == 3:
                        self.assertEqual(p.view, 'overview')
                        self.assertEqual(len(p.layouts), 2)
                        key(pygame.K_n)
                        key(pygame.K_v)
                        key(pygame.K_e)
                        key(pygame.K_m)
                        key(pygame.K_RIGHT)
                    elif phase == 4:
                        self.assertEqual(w.generation, 2)
                        self.assertFalse(scope['renderer'].show_food)
                        self.assertFalse(scope['renderer'].show_season_fx)
                        self.assertIs(scope['selected_org'], selected)
                        if p.ai:
                            self.assertFalse(p.ai.controller.busy)
                            self.assertEqual(p.ai.controller.annual.entries, {})
                        pygame.event.post(pygame.event.Event(pygame.QUIT))
                    phase += 1
                try:
                    with patch.object(config, 'MAX_STEPS_PER_GEN', 2), patch.object(pygame.display, 'flip', capture):
                        main.run_with_visualization(w, explanation_mode=mode)
                    self.assertEqual(phase, 6)
                finally:
                    pygame.quit()
                    config.TEMPERATURE = temperature
                    os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
