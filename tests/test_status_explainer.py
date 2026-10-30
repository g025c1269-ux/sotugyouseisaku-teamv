"""The shared LOW/MID/HIGH classifier remains; individual prose is removed."""
import math
import unittest
from unittest.mock import patch

import config
from organism import Organism
from status_explainer import StatusExplainer


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.classifier = StatusExplainer()

    def test_all_thresholds_and_boundaries(self):
        for stat in self.classifier.stats:
            low, high = stat['thresholds']
            examples = [(0, 'LOW'), (math.nextafter(low, 0), 'LOW'), (low, 'MID'),
                        (math.nextafter(low, 1), 'MID'), (math.nextafter(high, 0), 'MID'),
                        (high, 'HIGH'), (math.nextafter(high, 1), 'HIGH'), (1, 'HIGH')]
            for value, expected in examples:
                with self.subTest(key=stat['key'], value=value):
                    self.assertEqual(self.classifier.classify(stat['key'], value), expected)
            for value in [-.1, 1.1, float('nan'), float('inf')]:
                with self.assertRaises(ValueError):
                    self.classifier.classify(stat['key'], value)

    def test_real_gene_inventory_and_modes(self):
        declared = {s['key'] for s in self.classifier.stats if s['source'] == 'gene'}
        for species in ('herbivore', 'carnivore'):
            self.assertEqual(set(Organism(0, 0, species).genes), declared)
        for enabled, expected in ((True, 'nn'), (False, 'rule')):
            with patch.object(config, 'USE_NEUROEVOLUTION', enabled):
                self.assertEqual(self.classifier.current_mode(), expected)

    def test_individual_prose_and_export_apis_are_removed(self):
        for name in ('explain_values', 'explain_organism', 'combinations', 'export_csv'):
            self.assertFalse(hasattr(self.classifier, name))
        for name in ('relations', 'special', 'text', 'context'):
            self.assertNotIn(name, self.classifier.data)


if __name__ == '__main__':
    unittest.main()
