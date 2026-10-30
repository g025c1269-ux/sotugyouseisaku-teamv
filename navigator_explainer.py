"""Short, deterministic navigator comments from live values and distributions."""
import hashlib
import json
from pathlib import Path

from status_explainer import StatusExplainer

CORE = ('cold_resistance', 'speed', 'metabolism', 'river_tolerance', 'mountain_tolerance')
PROFILE_ORDER = ('river_tolerance', 'mountain_tolerance', 'speed', 'metabolism', 'cold_resistance')
PROFILE_NAMES = {'river_tolerance':'river', 'mountain_tolerance':'mountain',
                 'speed':'speed', 'metabolism':'metabolism', 'cold_resistance':'cold'}


class NavigatorExplainer:
    def __init__(self, data_path=None):
        self.classifier = StatusExplainer()
        path = data_path or Path(__file__).with_name('data') / 'navigator_text.json'
        self.text = json.loads(Path(path).read_text(encoding='utf-8'))

    def _variant(self, alternatives, key):
        # Stable wording, without touching Python/NumPy's simulation RNG.
        parts = key.split('|')
        style = '|'.join(parts[1:])
        offset = int(parts[0] == 'carnivore')
        i = (hashlib.sha256(style.encode('utf-8')).digest()[0] + offset) % len(alternatives)
        return alternatives[i]

    def _profile(self, rows, distributions):
        n = len(rows)
        if sum(r['speed'] == 'HIGH' and r['river_tolerance'] == 'LOW' for r in rows) / n >= .6:
            return 'speed_river'
        if sum(r['river_tolerance'] == r['mountain_tolerance'] == 'HIGH' for r in rows) / n >= .6:
            return 'terrain'
        if sum(all(r[k] == 'MID' for k in CORE) for r in rows) / n >= .6:
            return 'balanced'
        if any(distributions[k]['LOW'] / n >= .25 and distributions[k]['HIGH'] / n >= .25 for k in CORE):
            return 'mixed'
        candidates = [(distributions[k][level] / n, -i, k, level)
                      for i, k in enumerate(PROFILE_ORDER) for level in ('HIGH', 'LOW')
                      if distributions[k][level] / n >= .6]
        if candidates:
            _, _, key, level = max(candidates)
            return PROFILE_NAMES[key] + '_' + level.lower()
        return 'varied'

    def population(self, organisms, species, temperature):
        members = [o for o in organisms if o.alive and o.org_type == species]
        n = len(members)
        if not n:
            return {'count':0, 'means':{}, 'distribution':{}, 'profile':'empty',
                    'text':self._variant(self.text['empty'], species), 'balanced_fraction':0}
        gene_keys = [s['key'] for s in self.classifier.stats if s['source'] == 'gene']
        means = {k:sum(o.genes[k] for o in members) / n for k in gene_keys}
        rows = [{k:self.classifier.classify(k, o.genes[k]) for k in gene_keys} for o in members]
        distributions = {k:{level:sum(r[k] == level for r in rows) for level in ('LOW','MID','HIGH')}
                         for k in gene_keys}
        profile = self._profile(rows, distributions)
        text = self._variant(self.text['profiles'][profile], species + '|' + profile)
        if n == 1:
            # A lone animal is evidence about itself, not a widespread population trait.
            individual_profile = {'balanced':'individual_balanced', 'varied':'individual_varied'}.get(profile, profile)
            text = self.text['single'] + self._variant(self.text['profiles'][individual_profile], species + '|single')
        elif temperature <= 10 and sum(abs(temperature / 40 - o.genes['cold_resistance']) > .35 for o in members) / n >= .6:
            text += self.text['cold_now']
        elif sum(o.energy / o.max_energy < .4 for o in members) / n >= .6:
            text += self.text['energy_low']
        return {'count':n, 'means':means, 'distribution':distributions, 'profile':profile,
                'balanced_fraction':sum(all(r[k] == 'MID' for k in CORE) for r in rows) / n,
                'text':text}
