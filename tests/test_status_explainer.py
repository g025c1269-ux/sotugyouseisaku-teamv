import copy
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import config
from organism import Organism
from world import World
from status_explainer import StatusExplainer, LEVELS, DATA_PATH


class ExplainerTests(unittest.TestCase):
    def setUp(self):
        self.explainer = StatusExplainer()
        self.genes = {s['key']: .5 for s in self.explainer.stats if s['source'] == 'gene'}
        self.saved_temperature = config.TEMPERATURE

    def tearDown(self):
        config.TEMPERATURE = self.saved_temperature

    def test_all_thresholds_and_boundaries(self):
        for stat in self.explainer.stats:
            key = stat['key']
            low, high = stat['thresholds']
            examples = [(0, 'LOW'), (math.nextafter(low, 0), 'LOW'),
                        (low, 'MID'), (math.nextafter(low, 1), 'MID'),
                        (math.nextafter(high, 0), 'MID'), (high, 'HIGH'),
                        (math.nextafter(high, 1), 'HIGH'), (1, 'HIGH')]
            for value, expected in examples:
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.explainer.classify(key, value), expected)
            for value in [-.1, 1.1, float('nan'), float('inf')]:
                with self.assertRaises(ValueError):
                    self.explainer.classify(key, value)

    def test_every_combination_for_both_species(self):
        summaries = set()
        for species in ['herbivore', 'carnivore']:
            rows = list(self.explainer.combinations(species))
            self.assertEqual(len(rows), 3 ** 7)
            self.assertEqual(len({r['key'] for r in rows}), 3 ** 7)
            for r in rows:
                self.assertTrue(r['summary'].strip())
                self.assertEqual(set(r['values']), set(self.explainer.keys))
                self.assertEqual(set(r['levels']), set(self.explainer.keys))
                self.assertEqual(len(r['relationships']), len(set(r['relationships'])))
                self.assertEqual(len(r['relationships']), 5)  # four disjoint pair groups + species
                self.assertTrue(r['strengths'] and r['weaknesses'])
                summaries.add(r['summary'])
            self.assertFalse(any('魚' in r['summary'] for r in rows if species == 'herbivore'))
        self.assertEqual(len(summaries), 4374)

    def test_special_and_fallback(self):
        exact = self.explainer.explain_values('herbivore', self.genes, .6)
        self.assertTrue(exact['summary'].startswith(self.explainer.data['special'][exact['key']]))
        changed = self.explainer.explain_values('herbivore', {**self.genes, 'speed': .9}, .6)
        self.assertNotEqual(exact['summary'], changed['summary'])
        self.assertNotIn(changed['key'], self.explainer.data['special'])

    def test_real_gene_inventory_and_unknown_fields(self):
        org = Organism(0, 0)
        declared = {s['key'] for s in self.explainer.stats if s['source'] == 'gene'}
        self.assertEqual(set(org.genes), declared)
        for species in ['herbivore', 'carnivore']:
            org = Organism(0, 0, species)
            self.assertEqual(set(org.genes), declared)
        r = self.explainer.explain_values('herbivore', {**self.genes, 'attack': .9}, .5)
        self.assertNotIn('attack', r['levels'])
        self.assertNotIn('attack', r['summary'])
        self.assertNotIn('攻撃力', r['summary'])
        self.assertEqual(r['unclassified_genes'], ['attack'])
        with self.assertRaises(KeyError):
            self.explainer.explain_values('herbivore', {}, .5)
        with self.assertRaises(ValueError):
            self.explainer.explain_values('unknown', self.genes, .5)

    def test_current_state_costs_and_no_mutation_or_rng_consumption(self):
        np.random.seed(123)
        w = World()
        for species in ['herbivore', 'carnivore']:
            o = Organism(0, 0, species, genes=self.genes)
            before = copy.deepcopy(vars(o))
            rng = np.random.get_state()
            config.TEMPERATURE = 5
            r = self.explainer.explain_organism(o, w)
            self.assertEqual(vars(o), before)
            after = np.random.get_state()
            self.assertEqual(rng[0], after[0])
            np.testing.assert_array_equal(rng[1], after[1])
            self.assertEqual(rng[2:], after[2:])
            self.assertEqual(r['costs']['temperature'], o._calc_temp_penalty(w))
            self.assertEqual(r['costs']['move'], o._move_energy_cost(w))
            o.energy = .9 * o.max_energy
            config.TEMPERATURE = 35
            updated = self.explainer.explain_organism(o, w)
            self.assertEqual(updated['levels']['energy_ratio'], 'HIGH')
            self.assertNotEqual(r['context'], updated['context'])
            self.assertNotEqual(r['key'], updated['key'])
            o.alive = False
            o.energy = -.1
            dead = self.explainer.explain_organism(o, w)
            self.assertEqual(dead['levels']['energy_ratio'], 'LOW')
            self.assertIn('生存していません', ''.join(dead['context']))

    def test_fishing_boundary_and_actual_temperature_formula(self):
        w = World()
        for tolerance, expected in [(.79, '確率は0'), (.8, '確率は0'),
                                    (math.nextafter(.8, 1), '抽選が発生')]:
            genes = {**self.genes, 'river_tolerance': tolerance}
            o = Organism(0, 0, 'carnivore', genes)
            self.assertIn(expected, ''.join(self.explainer.explain_organism(o, w)['context']))
            o.org_type = 'herbivore'
            self.assertNotIn('魚', ''.join(self.explainer.explain_organism(o, w)['context']))
        for cold in [.1, .5, .9]:
            o = Organism(0, 0, genes={**self.genes, 'cold_resistance': cold})
            config.TEMPERATURE = 40 * cold
            self.assertAlmostEqual(self.explainer.explain_organism(o, w)['costs']['temperature'], 0)

    def test_simulation_matches_without_explanations(self):
        def run(with_explanations):
            np.random.seed(1000)
            w = World()
            for _ in range(2):
                w.run_generation()
                if with_explanations:
                    for org in w.organisms:
                        self.explainer.explain_organism(org, w)
            return w
        baseline = run(False)
        explained = run(True)
        np.testing.assert_array_equal(baseline.food_grid, explained.food_grid)
        self.assertEqual([vars(o) for o in baseline.organisms], [vars(o) for o in explained.organisms])
        for k in baseline.history:
            np.testing.assert_array_equal(baseline.history[k], explained.history[k])
        self.assertEqual(explained.generation, 2)
        self.assertEqual(explained.step_count, 400)

    def test_export_full_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'catalog.csv'
            self.explainer.export_csv(path)
            with path.open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4374)
            self.assertEqual(len({r['key'] for r in rows}), 4374)
            self.assertTrue(all(r['summary'] and r['strengths'] and r['weaknesses'] for r in rows))

    def test_data_validation_and_adding_declared_gene(self):
        data = json.loads(DATA_PATH.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.json'
            bad = copy.deepcopy(data)
            bad['relations'][0]['when']['nonexistent'] = 'HIGH'
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                StatusExplainer(path)
            data['special'] = {}
            extra = copy.deepcopy(data['stats'][1])
            extra['key'] = 'future_gene'
            data['stats'].append(extra)
            path.write_text(json.dumps(data))
            extended = StatusExplainer(path)
            r = extended.explain_values('herbivore', {**self.genes, 'future_gene': .9}, .5)
            self.assertEqual(r['levels']['future_gene'], 'HIGH')
            self.assertEqual(len(r['key'].split('|')), 9)


if __name__ == '__main__':
    unittest.main()
