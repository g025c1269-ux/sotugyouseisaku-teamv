"""Curated replies against measured fixtures; these are not real model outputs."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import config
from annual_report import AnnualRecorder
from ai_navigator import AINavigator
from ollama_explainer import ANNUAL_PROMPT, SYSTEM_PROMPT, OllamaError, OllamaExplainer


EXAMPLES = (
    '草食たちは100匹から60匹、肉食組も20匹から18匹に減ったね。食べ物も減っていて、蓄えの確保が難しかったのかも。草食の平均代謝は下がり、基本消費を抑えやすい値になったよ。ただ、数が減った理由はまだ確定できないね。来年は食べ物と両方の群れの増減を見守ろう！',
    '草食たちが減った一方で、肉食組の平均川適応は上がったね！川を通る場面なら移動の消費を抑えやすそう。でも実際に川を通った記録はないから、数の変化の原因とはまだ言えないよ。この傾向が続くか、来年の仲間の数と適応に注目してみよう。',
    '草食も肉食も仲間が減ったね。気温も下がったけれど、温度適性が高いほど寒さに強いわけではないよ。草食の平均代謝が下がった分、基本消費は抑えやすいかも。どの変化が数の減少に関係したかはまだ不明だから、来年も食べ物と気温を見比べてみよう！',
)
ECHO = '草食と肉食の両方にそれぞれ、仲間の増減、注目する平均形質の変化、その能力がゲームでどう働くかをつなげて話しています。増減・高低・比較はPythonが確定した結果を使ってください。'


def observations():
    keys = ('cold_resistance', 'speed', 'hunger_threshold', 'metabolism', 'river_tolerance', 'mountain_tolerance')
    def animal(species):
        genes = {k: .5 for k in keys}
        if species == 'herbivore':
            genes['metabolism'] = .6
        return SimpleNamespace(alive=True, org_type=species, genes=genes, energy=50, max_energy=100)
    w = SimpleNamespace(generation=1, step_count=0, land_ratio=.7, food_grid=np.ones((10, 10), dtype=bool),
                        organisms=[animal('herbivore') for _ in range(100)] + [animal('carnivore') for _ in range(20)])
    recorder = AnnualRecorder()
    with patch.object(config, 'TEMPERATURE', 10):
        for generation in range(1, recorder.cycle + 1):
            w.generation = generation
            recorder.before_step(w)
            if generation == recorder.cycle:
                w.organisms = w.organisms[:60] + w.organisms[100:118]
                for a in w.organisms:
                    a.genes['metabolism' if a.org_type == 'herbivore' else 'river_tolerance'] = .4 if a.org_type == 'herbivore' else .8
                w.food_grid.flat[60:] = False
                config.TEMPERATURE = 8
            w.step_count += config.MAX_STEPS_PER_GEN
            context = recorder.after_step(w, True, False, False)
    return context


class AnnualPromptTests(unittest.TestCase):
    def setUp(self):
        self.client = OllamaExplainer()
        self.context = observations()
        self.patch = patch('ollama_explainer.build_opener')
        self.opener = self.patch.start()
        self.addCleanup(self.patch.stop)

    def respond(self, text):
        raw = json.dumps({'done': True, 'message': {'content': json.dumps({'comment': text}, ensure_ascii=False)}}).encode()
        self.opener.return_value.open.return_value.__enter__.return_value.read.return_value = raw

    def test_actual_request_uses_current_model_short_prompt_and_observations(self):
        payload = self.client.build_request(self.context)
        self.assertEqual(payload['model'], 'ecosystem-leaf:latest')
        self.assertEqual(payload['messages'][0], {'role': 'system', 'content': ANNUAL_PROMPT})
        self.assertEqual([m['role'] for m in payload['messages']], ['system', 'user'])
        self.assertFalse(payload['think'])
        self.assertEqual(self.client.settings.timeout_seconds, 120)
        self.assertLess(len(ANNUAL_PROMPT), 400)
        data = json.loads(payload['messages'][1]['content'])
        self.assertEqual(data['changes']['herbivore']['start_count'], 100)
        self.assertEqual(data['changes']['herbivore']['end_count'], 60)
        self.assertEqual(data['changes']['carnivore']['count_delta'], -2)
        self.assertEqual(data['environment']['food_count_delta'], -40)
        self.assertEqual(data['environment']['temperature_delta'], -2)
        self.assertIsNone(data['environment']['events'])
        self.assertNotIn('start', data)

    def test_curated_observation_hypothesis_and_outlook_replies_are_accepted(self):
        for reply in EXAMPLES:
            with self.subTest(reply=reply):
                self.respond(reply)
                self.assertEqual(self.client.generate(self.context), reply)
                self.assertTrue(self.client.last_diagnostics['success'])

    def test_reported_echo_and_paraphrases_fail_with_diagnostics(self):
        replies = (ECHO, ANNUAL_PROMPT,
                   '草食と肉食の両方に触れてください。commentというキーだけのJSONを返してください。観測データを使うように説明しています。',
                   '草食は減り肉食は増えたね。Pythonが計算した高低をそのまま使用してください。')
        for reply in replies:
            self.respond(reply)
            with self.assertRaises(OllamaError) as caught:
                self.client.generate(self.context)
            self.assertEqual(caught.exception.kind, 'instruction_echo')
            self.assertFalse(self.client.last_diagnostics['success'])
            self.assertEqual(self.client.last_diagnostics['error_kind'], 'instruction_echo')
            self.assertTrue(caught.exception.raw_response)

    def test_ordinary_advice_and_shared_rule_words_are_not_false_positives(self):
        for reply in (
            '草食と肉食の両方で仲間が減ったね。平均形質の変化だけでは理由を決められないよ。来年も両方の群れを観察してくださいね！',
            '草食の数は減り、肉食も少し減ったね。増減や高低だけでは原因は分からないよ。次は食べ物の変化と比べてみよう！',
            '草食も肉食も観察できる記録が足りないね。今は理由も今後の変化も分からないから、次の年の記録を待ってみよう！',
        ):
            self.respond(reply)
            self.assertEqual(self.client.generate(self.context), reply)

    def test_echo_is_not_checked_for_individual_and_its_prompt_stays_separate(self):
        self.assertEqual(self.client.build_request({'target': 'individual'})['messages'][0]['content'], SYSTEM_PROMPT)
        reply = '草食の個体と肉食の個体。Pythonが確定した結果を使ってください。今はテスト用の個体紹介だよ。'
        self.respond(reply)
        self.assertEqual(self.client.generate({'target': 'individual'}), reply)

    def test_rejected_echo_uses_existing_fallback_and_persists_reason(self):
        self.respond(ECHO)
        with tempfile.TemporaryDirectory() as tmp:
            nav = AINavigator(self.client, Path(tmp) / 'report.json')
            nav.annual.add(self.context)
            original_fallback = nav.annual.entries[1]['fallback']
            nav.annual.entries[1]['status'] = 'running'
            nav.busy = True
            log = Path(tmp) / 'debug.jsonl'
            nav._generate(self.client, self.context, ('annual', 1, 0), nav._results, log)
            nav.poll()
            entry = nav.annual.displayed()
            self.assertEqual(entry['status'], 'fallback')
            self.assertEqual(entry['text'], '')
            self.assertEqual(entry['fallback'], original_fallback)
            self.assertEqual(entry['error_kind'], 'instruction_echo')
            self.assertEqual(json.loads(log.read_text())['error_kind'], 'instruction_echo')
            self.assertTrue(entry['request'])
            nav.close()


if __name__ == '__main__':
    unittest.main()
