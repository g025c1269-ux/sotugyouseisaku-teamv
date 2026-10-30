"""Seven observation fixtures and curated replies, not model quality evidence."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import config
from ai_navigator import AINavigator
from annual_ai_context import build_annual_ai_context, is_rule_recital
from annual_report import AnnualRecorder
from ollama_explainer import ANNUAL_DATA_MARKER, ANNUAL_PROMPT, OllamaError, OllamaExplainer, OllamaSettings


# Input endpoints are observed by the real recorder, without executing game actions.
CASES = {
    'food_metabolism': {'counts': (60, 18), 'food': 60, 'traits': {'herbivore': ('metabolism', .6, .4)}},
    'cold': {'counts': (90, 19), 'temperature': (20, 8),
             'traits': {'herbivore': ('cold_resistance', .5, .2), 'carnivore': ('cold_resistance', .5, .3)}},
    'both_decline': {'counts': (60, 10)},
    'mountain': {'counts': (100, 22), 'traits': {'carnivore': ('mountain_tolerance', .3, .8)}},
    'river': {'counts': (95, 19), 'traits': {'herbivore': ('river_tolerance', .8, .3)}},
    'stable': {'counts': (101, 20)},
    'zero': {'counts': (0, 0)},
}

# Authored examples reviewed against the fixture values. No example is sent to the model.
REPLIES = {
    'food_metabolism': '今年は草食が100匹から60匹、肉食も20匹から18匹に減っちゃったね。食べ物のあるマスも減り、エネルギーを確保しにくかったのかもしれないよ。草食の平均代謝は0.6から0.4へ下がっていて、消費を抑えやすい方向だね！燃費のいい個体が残った可能性もあるけど、繁殖や遺伝、集団の入れ替わりでも平均は変わるよ。もし草食の減少が続けば、肉食も獲物探しに苦労するかも。来年は食べ物と両方の群れの数を一緒に追いかけてみよう！',
    'cold': '気温が20℃から8℃へ下がり、草食の平均温度適性も0.5から0.2へ動いたね。平均の適温と気温の差は小さいままで、寒くなる中でも温度による消費の増加を抑えたのかもしれないよ！ただし、これは平均同士の比較で、一匹ずつの消耗を測った結果ではないんだ。草食も肉食も少し減っているけれど、寒さだけが理由とはまだ言えないね。この先さらに冷えるなら、肉食の温度適性も合わせて、数と気温の動きを一緒に見比べていきたいな！',
    'both_decline': '草食が100匹から60匹、肉食も20匹から10匹へ減ったね。草食は肉食にとって獲物だから、草食が減って蓄えを得にくくなったことが肉食の減少にも関係したのかもしれないよ。ただ、実際に何匹を捕食したかや死亡理由の記録はないし、肉食には魚を捕る道もあるんだ。だから、餌不足だけが原因とはまだ決められないね。このまま両方の群れが減るなら、来年も草食の数と肉食の変化を一緒に追うと、つながりが少し見えてくるかもしれないね！',
    'mountain': '肉食の平均山適応が0.3から0.8へ上がって、仲間も20匹から22匹に増えたね！山を通る場面では移動の消費を抑えやすくなったことが、蓄えの確保に関係したのかもしれないよ。でも、どの地形を通ったかは記録されていないから、山適応が増加の決め手だったとは言えないんだ。草食チームは100匹を保っているね！もし山をよく使う環境なら、この適応が肉食の暮らしにどう響くか、来年の数の変化と合わせて見ていきたいな！',
    'river': '草食の平均川適応が0.8から0.3へ下がり、数も100匹から95匹へ少し減ったね。川を渡る場面なら消費が増える方向だから、蓄えに余裕がなくなった可能性はありそうだよ。ただ、実際に川を通った記録はないので、川適応の低下が減少の原因とはまだ言えないね。肉食も20匹から19匹になったけれど、捕食の回数は不明なんだ。この傾向が続くなら、来年も両方の数と川適応を比べて、変化のつながりをこれからも一緒に探してみよう！',
    'stable': '草食は100匹から101匹、肉食は20匹のままで、今年はほぼ数を保ったね！食べ物のあるマス数も年初と年末で変わっていないよ。食べることと消費の釣り合いが保たれたのかもしれないけれど、年内の摂食や誕生、死亡の回数は分からないんだ。だから、変化が少なく見えても、ずっと同じ暮らしだったとは限らないね。もし食べ物や気温が変われば両方の群れの関係も動くかも。来年も安定が続くか、ここが生態系の面白いところだね！',
    'zero': '年初にいた草食100匹と肉食20匹は、年末にはどちらも0匹になったね。草食が減ると獲物を得にくくなることが、肉食の減少にも関係したのかもしれないよ。ただし捕食や死亡の記録はなく、どちらが先に減ったかも、この年初と年末の比較だけでは分からないんだ。平均形質も年末は比べられないから、能力がゼロになったという話ではないよ。繁殖する親も残っていないので、このまま自然に群れが復活するとは期待できないね。この記録は大事に残しておこう。',
}
BAD_MANUAL = '草食の代謝は容量と基本消費の両方を増やす。肉食の移動速度は2マス移動の確率を高める。温度適応は寒さに強いと解釈されない。環境と増減の因果は未検証。'
BAD_ECHO = '草食と肉食の両方にそれぞれ、仲間の増減、注目する平均形質の変化、その能力がゲームでどう働くかをつなげて話しています。増減・高低・比較はPythonが確定した結果を使ってください。'


def annual_fixture(name):
    case = CASES[name]
    keys = ('metabolism', 'speed', 'cold_resistance', 'river_tolerance', 'mountain_tolerance', 'hunger_threshold')
    def members(species, n, end=False):
        genes = {k: .5 for k in keys}
        if species in case.get('traits', {}):
            key, start, last = case['traits'][species]
            genes[key] = last if end else start
        return [SimpleNamespace(alive=True, org_type=species, genes=genes.copy(), energy=50., max_energy=100.)
                for _ in range(n)]
    w = SimpleNamespace(generation=1, step_count=0, land_ratio=.7, food_grid=np.ones((10, 10), dtype=bool),
                        organisms=members('herbivore', 100) + members('carnivore', 20))
    temperatures = case.get('temperature', (20, 20))
    recorder = AnnualRecorder()
    with patch.object(config, 'TEMPERATURE', temperatures[0]):
        for g in range(1, recorder.cycle + 1):
            w.generation = g
            recorder.before_step(w)
            if g == recorder.cycle:
                h, c = case['counts']
                w.organisms = members('herbivore', h, True) + members('carnivore', c, True)
                w.food_grid.flat[case.get('food', 100):] = False
                config.TEMPERATURE = temperatures[1]
            w.step_count += config.MAX_STEPS_PER_GEN
            context = recorder.after_step(w, True, False, False)
    return context


class AnnualInputTests(unittest.TestCase):
    def test_population_food_and_changed_traits_are_exact_and_input_is_immutable(self):
        for case in CASES:
            context = annual_fixture(case)
            before = copy.deepcopy(context)
            projected = build_annual_ai_context(context)
            self.assertEqual(context, before)
            obs = projected['observations']
            self.assertEqual(obs['populations']['herbivore']['start'], 100)
            self.assertEqual(obs['populations']['herbivore']['end'], CASES[case]['counts'][0])
            self.assertEqual(obs['populations']['carnivore']['end'], CASES[case]['counts'][1])
            self.assertLessEqual(len(obs['notable_traits']), 2)
            self.assertNotIn('interpretation', projected)
            self.assertNotIn('generation_observations', projected)
            self.assertNotIn('end_distribution', json.dumps(projected))
        food = build_annual_ai_context(annual_fixture('food_metabolism'))['observations']
        self.assertEqual(food['food_cells'], {'start': 100, 'end': 60, 'delta': -40})
        self.assertEqual(food['notable_traits'][0]['trait'], 'metabolism')
        self.assertEqual(food['notable_traits'][0]['delta'], -.2)

    def test_temperature_alignment_is_a_proxy_not_average_individual_cost(self):
        obs = build_annual_ai_context(annual_fixture('cold'))['observations']
        fit = obs['temperature_fit']['herbivore']
        self.assertEqual(fit['start'], {'air_c': 20, 'mean_preferred_c': 20, 'gap_of_means_c': 0})
        self.assertEqual(fit['end'], {'air_c': 8, 'mean_preferred_c': 8, 'gap_of_means_c': 0})
        # Nonlinear absolute differences cannot be reconstructed from the mean.
        self.assertNotIn('average_temperature_cost', fit)
        self.assertEqual(obs['temperature_c']['delta'], -12)

    def test_inactive_traits_are_not_used_and_references_follow_each_year(self):
        source = annual_fixture('mountain')
        source['changes']['carnivore']['traits']['hunger_threshold'].update(start=0., end=1., delta=1., active=False)
        data = build_annual_ai_context(source)
        self.assertEqual([t['trait'] for t in data['observations']['notable_traits']], ['mountain_tolerance'])
        self.assertIn('mountain_tolerance', data['reference_for_observed_changes'])
        self.assertNotIn('metabolism', data['reference_for_observed_changes'])
        other = build_annual_ai_context(annual_fixture('food_metabolism'))
        self.assertIn('metabolism', other['reference_for_observed_changes'])
        self.assertNotIn('mountain_tolerance', other['reference_for_observed_changes'])

    def test_zero_unknown_and_no_observations_are_not_replaced_with_fake_values(self):
        zero = build_annual_ai_context(annual_fixture('zero'))['observations']
        self.assertEqual(zero['zero_at_end'], ['herbivore', 'carnivore'])
        self.assertEqual(zero['notable_traits'], [])
        self.assertIsNone(zero['temperature_fit']['herbivore']['end']['mean_preferred_c'])
        missing = build_annual_ai_context({'target': 'annual', 'year': 1})['observations']
        self.assertIsNone(missing['populations']['carnivore']['end'])
        self.assertIsNone(missing['food_cells']['delta'])
        self.assertEqual(missing['zero_at_end'], [])
        source = annual_fixture('food_metabolism')
        source['changes']['carnivore']['start_count'] = None
        source['changes']['carnivore']['end_count'] = None
        missing_carnivore = build_annual_ai_context(source)['observations']['populations']['carnivore']
        self.assertEqual(missing_carnivore, {'start': None, 'end': None, 'delta': None, 'change_fraction': None})

    def test_request_preserves_model_system_and_is_self_contained_for_other_models(self):
        for model in ('ecosystem-leaf:latest', 'qwen3:1.7b', 'qwen3:4b'):
            client = OllamaExplainer(OllamaSettings(model=model, timeout_seconds=120))
            source = annual_fixture('food_metabolism')
            request = client.build_request(source)
            self.assertEqual(request['model'], model)
            self.assertEqual([m['role'] for m in request['messages']], ['user'])
            instruction, data = request['messages'][0]['content'].split(ANNUAL_DATA_MARKER)
            self.assertEqual(instruction, ANNUAL_PROMPT)
            self.assertIn('研究員「リーフ」', instruction)
            self.assertIn('200〜350', instruction)
            self.assertEqual(json.loads(data), build_annual_ai_context(source))
            self.assertFalse(request['think'])
            self.assertEqual(request['format']['required'], ['comment'])


class AnnualReplyTests(unittest.TestCase):
    def setUp(self):
        self.client = OllamaExplainer()
        self.patch = patch('ollama_explainer.build_opener')
        self.opener = self.patch.start()
        self.addCleanup(self.patch.stop)

    def response(self, text):
        envelope = {'done': True, 'message': {'content': json.dumps({'comment': text}, ensure_ascii=False)}}
        self.opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()

    def test_all_seven_curated_replies_are_retained_without_truncation(self):
        for name, reply in REPLIES.items():
            with self.subTest(case=name):
                self.assertTrue(200 <= len(reply) <= 350)
                self.response(reply)
                self.assertEqual(self.client.generate(annual_fixture(name)), reply)
                self.assertTrue(self.client.last_diagnostics['success'])

    def test_reported_manual_and_instruction_echo_are_not_success(self):
        for text, kind in ((BAD_MANUAL, 'rule_recital'), (BAD_MANUAL.replace('。', '、'), 'rule_recital'),
                           (BAD_ECHO, 'instruction_echo'),
                           ('草食と肉食の解説では観測事実と仮説と展望を順に説明します。明るく話す文章にまとめてください。', 'instruction_echo'),
                           (ANNUAL_PROMPT, 'instruction_echo')):
            self.response(text)
            with self.assertRaises(OllamaError) as caught:
                self.client.generate(annual_fixture('food_metabolism'))
            self.assertEqual(caught.exception.kind, kind)
            self.assertEqual(self.client.last_diagnostics['error_kind'], kind)
            self.assertFalse(self.client.last_diagnostics['success'])
            self.assertTrue(caught.exception.raw_response)

    def test_legitimate_rules_bound_to_observations_and_cautious_advice_are_not_rejected(self):
        texts = (
            '草食と肉食の両方で仲間が減ったね。代謝は容量と基本消費の両方に関わるから、代謝が下がった草食には消費を抑える方向かも。速度は2マス移動の確率を上げるけれど、今年の数の変化の理由とは決められないよ。',
            '草食も肉食も観察記録が足りないね。分からない数値から原因や未来は推測できないから、まず次の記録を待とう！',
            '草食と肉食の両方を来年も観察してくださいね！数がほとんど変わらなかった理由はまだ分からないけれど、食べ物と消費の釣り合いが関係したのかもしれないよ。',
        )
        for text in texts:
            self.response(text)
            self.assertEqual(self.client.generate(annual_fixture('stable')), text)
        self.assertFalse(is_rule_recital('今年は草食も肉食も0匹。代謝は容量と基本消費を増やす。速度は2マス移動の確率を上げる。'))

    def test_rejection_reuses_existing_fallback_history_and_diagnostics(self):
        for reply, kind in ((BAD_MANUAL, 'rule_recital'), (BAD_ECHO, 'instruction_echo')):
            self.response(reply)
            with tempfile.TemporaryDirectory() as tmp:
                context = annual_fixture('food_metabolism')
                nav = AINavigator(self.client, Path(tmp) / 'annual.json')
                nav.annual.add(context)
                fallback = nav.annual.entries[1]['fallback']
                nav.annual.entries[1]['status'] = 'running'
                nav.busy = True
                log = Path(tmp) / 'annual.debug.jsonl'
                nav._generate(self.client, context, ('annual', 1, 0), nav._results, log)
                nav.poll()
                entry = nav.annual.displayed()
                self.assertEqual(entry['status'], 'fallback')
                self.assertEqual(entry['text'], '')
                self.assertEqual(entry['fallback'], fallback)
                self.assertEqual(entry['error_kind'], kind)
                self.assertEqual(json.loads(log.read_text())['error_kind'], kind)
                self.assertEqual(entry['request']['messages'][0]['role'], 'user')
                self.assertEqual(entry['context'], context)
                nav.close()


if __name__ == '__main__':
    unittest.main()
