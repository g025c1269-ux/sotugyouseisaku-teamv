"""Integration through real game events; supports offscreen CI/screenshots."""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/teamv-test-matplotlib')
os.environ.setdefault('XDG_CACHE_HOME', '/tmp/teamv-test-cache')
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pygame
import config
import main
from world import World
from pixel_art import CELL
from status_panel import StatusPanel


class StatusPanelTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_temperature = config.TEMPERATURE

    def tearDown(self):
        pygame.quit()
        config.TEMPERATURE = self.old_temperature
        self.tempdir.cleanup()

    def test_live_refresh_without_editing_organism(self):
        np.random.seed(5)
        world = World()
        org = world.organisms[0]
        pygame.init()
        screen = pygame.display.set_mode((1040, 640))
        panel = StatusPanel((640, 0, 400, 640))
        panel.draw(screen, org, world)
        old = panel.signature
        world.step()
        survivor = next(o for o in world.organisms if o.alive)
        panel.draw(screen, survivor, world)
        self.assertNotEqual(old, panel.signature)
        self.assertIn('エネルギー', ''.join(line for line, _ in panel.lines))
        self.assertTrue(all(panel.font.size(line)[0] <= panel.body.width for line, _ in panel.lines))
        self.assertEqual(panel.signature[1], survivor.energy)
        self.assertEqual(panel.signature[3], survivor.age)

    def test_actual_selection_scroll_close_reopen_and_simulation(self):
        np.random.seed(1000)
        world = World()
        stage = 0
        frames = 0
        initial_age = None
        out = Path(os.environ.get('STATUS_SCREENSHOT_DIR', self.tempdir.name))
        out.mkdir(parents=True, exist_ok=True)
        original_flip = pygame.display.flip

        def key(k):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k))

        def click(pos):
            for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                pygame.event.post(pygame.event.Event(kind, button=1, pos=pos))

        def select(species, renderer):
            for org in world.organisms:
                pos = (org.y * CELL + CELL // 2, org.x * CELL + CELL // 2)
                if org.org_type == species and renderer.find_org(world, *pos) is org:
                    click(pos)
                    return
            self.fail('No selectable organism')

        def save(name):
            pygame.image.save(pygame.display.get_surface(), out / name)

        def flip():
            nonlocal stage, frames, initial_age
            original_flip()
            frames += 1
            if frames > 180:
                self.fail('Integration did not finish')
            scope = inspect.currentframe().f_back.f_locals
            panel = scope['status_panel']
            selected = scope['selected_org']
            if stage == 0:
                key(pygame.K_m)
                select('herbivore', scope['renderer'])
                stage = 1
            elif stage == 1:
                self.assertTrue(scope['paused'] and panel.open)
                self.assertEqual(selected.org_type, 'herbivore')
                save('10_status_herbivore.png')
                pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, y=-8, x=0))
                stage = 2
            elif stage == 2:
                self.assertGreater(panel.scroll, 0)
                save('11_status_summary.png')
                pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, y=-100, x=0))
                stage = 3
            elif stage == 3:
                self.assertEqual(panel.scroll, panel.max_scroll)
                save('12_status_strengths.png')
                click(panel.close_rect.center)
                stage = 4
            elif stage == 4:
                self.assertFalse(panel.open)
                key(pygame.K_e)
                stage = 5
            elif stage == 5:
                self.assertTrue(panel.open)
                select('carnivore', scope['renderer'])
                stage = 6
            elif stage == 6:
                self.assertTrue(panel.open)
                self.assertEqual(panel.scroll, 0)
                self.assertEqual(selected.org_type, 'carnivore')
                save('13_status_carnivore.png')
                initial_age = selected.age
                key(pygame.K_SPACE)
                stage = 7
            elif stage == 7 and selected.age > initial_age:
                self.assertEqual(panel.signature[1], selected.energy)
                self.assertEqual(panel.signature[3], selected.age)
                self.assertGreater(world.step_count, 0)
                pygame.event.post(pygame.event.Event(pygame.QUIT))
                stage = 8

        old_cwd = Path.cwd()
        try:
            os.chdir(self.tempdir.name)
            with patch.object(pygame.display, 'flip', flip), patch.object(pygame.mouse, 'get_pos', return_value=(900, 350)):
                main.run_with_visualization(world)
        finally:
            os.chdir(old_cwd)
        self.assertEqual(stage, 8)
        self.assertFalse(pygame.get_init())
        for name in ['10_status_herbivore.png', '11_status_summary.png', '12_status_strengths.png', '13_status_carnivore.png']:
            path = out / name
            self.assertTrue(path.read_bytes().startswith(b'\x89PNG'))
            self.assertEqual(pygame.image.load(path).get_size(), (1040, 640))


if __name__ == '__main__':
    unittest.main()
