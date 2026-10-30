"""No individual commentary in either mode; annual history and selection survive."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
from navigator_panel import NavigatorPanel
from ollama_explainer import OllamaError, OllamaExplainer
from test_annual_report import world, advance_generation


class IndividualRemovalTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = pygame.display.set_mode((1040, 640))

    def tearDown(self):
        pygame.quit()

    def test_both_views_render_no_individual_commentary_controls(self):
        for ai in (False, True):
            p = NavigatorPanel((640, 0, 400, 640), ai_enabled=ai)
            p.open = True
            rendered = []
            class Font:
                def __init__(self, original): self.original = original
                def render(self, text, *args):
                    rendered.append(text)
                    return self.original.render(text, *args)
                def __getattr__(self, name): return getattr(self.original, name)
            for name in ('heading', 'small', 'font'):
                setattr(p, name, Font(getattr(p, name)))
            w = world()
            p.draw(self.screen, w.organisms[0], w)
            self.assertEqual(len(p.layouts), 1 if ai else 2)
            for removed in ('選択個体', '個体は手動', 'AI解説を更新', '個体の解説'):
                self.assertFalse(any(removed in text for text in rendered), removed)
            self.assertFalse(hasattr(p, 'individual'))
            if ai:
                for name in ('tabs', 'update_rect'):
                    self.assertFalse(hasattr(p.ai, name))
            p.close()

    def test_selection_and_old_controls_do_not_send_requests_and_history_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = NavigatorPanel((640, 0, 400, 640), ai_enabled=True)
            p.open = True
            p.annual.log_path = Path(tmp) / 'report.json'
            calls = []
            class Client:
                def generate(self, context):
                    calls.append(context)
                    return f"草食と肉食の{context['year']}年目の観測コメントだよ。"
            p.ai.controller.client = Client()
            w = world()
            def settle():
                end = time.monotonic() + 2
                while p.ai.controller.busy and time.monotonic() < end:
                    p.ai.controller.poll()
                    time.sleep(.001)
                self.assertFalse(p.ai.controller.busy)
            def select_and_click():
                for org in w.organisms:
                    p.draw(self.screen, org, w)
                    for pos in ((900, 92), (850, 140)):
                        p.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos), org, w)
            select_and_click()
            self.assertEqual(calls, [])
            for _ in range(p.annual.recorder.cycle * 2):
                p.advance(w, advance_generation, 0, False, False)
            settle()
            self.assertEqual([c['target'] for c in calls], ['annual', 'annual'])
            self.assertEqual([c['year'] for c in calls], [1, 2])
            select_and_click()
            self.assertEqual(len(calls), 2)
            def click(rect):
                p.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center), w.organisms[0], w)
            click(p.ai.latest_rect)
            self.assertEqual(p.annual.displayed()['context']['year'], 2)
            click(p.ai.previous_rect)
            self.assertEqual(p.annual.displayed()['context']['year'], 1)
            click(p.ai.next_rect)
            self.assertEqual(p.annual.displayed()['context']['year'], 2)
            click(p.ai.latest_rect)
            self.assertIsNone(p.annual.selected_year)
            p.close()

    def test_individual_and_legacy_nonannual_backend_targets_never_open_http(self):
        client = OllamaExplainer()
        with patch('ollama_explainer.build_opener') as opener:
            for target in ('individual', 'herbivore', 'carnivore', None):
                with self.assertRaises(OllamaError) as caught:
                    client.generate({'target': target})
                self.assertEqual(caught.exception.kind, 'unsupported_target')
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
