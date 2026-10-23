"""Actual main.py entry point, including the retained title and mission stub."""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/teamv-integration-mpl')
os.environ.setdefault('XDG_CACHE_HOME', '/tmp/teamv-integration-cache')
import inspect
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pygame
import config
import world as world_module
from pixel_art import ZOOM_LEVELS

ROOT = Path(__file__).resolve().parents[1]


class GameIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_cwd = Path.cwd()
        os.chdir(self.tempdir.name)
        self.temperature = config.TEMPERATURE
        self.visualize = config.VISUALIZE
        config.VISUALIZE = True

    def tearDown(self):
        os.chdir(self.old_cwd)
        config.TEMPERATURE = self.temperature
        config.VISUALIZE = self.visualize
        pygame.quit()
        self.tempdir.cleanup()

    def test_main_title_mission_god_controls_generation_and_quit(self):
        np.random.seed(1000)
        out = Path(os.environ.get('STATUS_SCREENSHOT_DIR', self.tempdir.name))
        out.mkdir(parents=True, exist_ok=True)
        flip = pygame.display.flip
        stage = 0
        frames = 0

        def key(k):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k))

        def click(pos):
            for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                pygame.event.post(pygame.event.Event(kind, button=1, pos=pos))

        def save(name):
            pygame.image.save(pygame.display.get_surface(), out / name)

        def capture():
            nonlocal stage, frames
            flip()
            frames += 1
            self.assertLess(frames, 240)
            scope = inspect.currentframe().f_back.f_locals
            if stage == 0:
                self.assertEqual(scope['menu'].page, 'title')
                save('18_integrated_title.png')
                click((500, 319))
            elif stage == 1:
                self.assertEqual(scope['menu'].page, 'mission')
                save('19_integrated_mission.png')
                click((500, 455))
            elif stage == 2:
                self.assertEqual(scope['menu'].page, 'title')
                click((500, 395))
            elif stage == 3:
                panel = scope['status_panel']
                self.assertTrue(panel.open)
                self.assertGreater(panel.cards['herbivore']['count'], 0)
                self.assertGreater(panel.cards['carnivore']['count'], 0)
                save('20_integrated_navigator.png')
                key(pygame.K_m)
                key(pygame.K_n)
            elif stage == 4:
                self.assertTrue(scope['paused'])
                self.assertFalse(scope['status_panel'].open)
                click(scope['speed_button_rects']['high'].center)
                key(pygame.K_e)
                key(pygame.K_v)
                key(pygame.K_2)
            elif stage == 5:
                r = scope['renderer']
                self.assertEqual(scope['speed_level'], 'high')
                self.assertFalse(r.show_season_fx)
                self.assertFalse(r.show_food)
                self.assertEqual(r.zoom, ZOOM_LEVELS[1])
                save('21_integrated_controls.png')
                w = scope['world']
                for org in w.organisms:
                    pos = (org.y*r.zoom+r.zoom//2-r.off_x, org.x*r.zoom+r.zoom//2-r.off_y)
                    if (16 < pos[0] < 620 and 32 < pos[1] < 620
                            and r.minimap_hit(*pos) is None and r.find_org(w, *pos) is org):
                        click(pos)
                        break
                else:
                    self.fail('No visible selectable organism')
            elif stage == 6:
                self.assertIsNotNone(scope['selected_org'])
                self.assertTrue(scope['status_panel'].open)
                save('22_integrated_selected.png')
                key(pygame.K_f)
                key(pygame.K_TAB)
            elif stage == 7:
                self.assertTrue(scope['follow'])
                panel = scope['status_panel']
                self.assertEqual(panel.view, 'detail')
                org = scope['selected_org']
                self.assertEqual(panel.detail.signature[1], org.energy)
                self.assertEqual(panel.detail.signature[3], org.age)
                key(pygame.K_TAB)
                key(pygame.K_RIGHT)
            elif stage == 8:
                self.assertEqual(scope['world'].generation, 2)
                self.assertEqual(scope['world'].history['generation'], [1])
                self.assertEqual(scope['world'].step_count, config.MAX_STEPS_PER_GEN)
                key(pygame.K_LEFT)
            elif stage == 9:
                self.assertEqual(scope['world'].generation, 1)
                self.assertEqual(scope['world'].step_count, 0)
                key(pygame.K_1)
            elif stage == 10:
                self.assertEqual(scope['renderer'].zoom, ZOOM_LEVELS[0])
                pygame.event.post(pygame.event.Event(pygame.QUIT))
            stage += 1

        with patch.object(pygame.display, 'flip', capture):
            runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
        self.assertGreaterEqual(stage, 11)
        self.assertFalse(pygame.get_init())

    def test_title_exit_does_not_initialize_simulation(self):
        flip = pygame.display.flip
        def exit_frame():
            flip()
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(500, 471)))
        with patch.object(world_module, 'World', side_effect=AssertionError('World created before God mode')):
            with patch.object(pygame.display, 'flip', exit_frame):
                runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
        self.assertFalse(pygame.get_init())


if __name__ == '__main__':
    unittest.main()
