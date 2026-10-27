"""Copy live observations into JSON-safe data; never execute animal actions."""
import math
import config
from navigator_explainer import NavigatorExplainer


COMPARISON_MARGIN = 0.05  # UI description only; not a simulation parameter.


def compare_to_mean(value, mean):
    delta = value - mean
    if abs(delta) >= COMPARISON_MARGIN or math.isclose(abs(delta), COMPARISON_MARGIN, abs_tol=1e-12, rel_tol=0):
        return '高め' if delta > 0 else '低め'
    return '同じくらい'


class EcosystemAIContext:
    def __init__(self):
        self.navigator = NavigatorExplainer()
        self.classifier = self.navigator.classifier

    def _traits(self, values):
        mode = self.classifier.current_mode()
        result = {}
        for stat in self.classifier.stats:
            key = stat['key']
            if stat['source'] != 'gene':
                continue
            level = self.classifier.classify(key, values[key])
            active = mode not in stat.get('inactive_in', [])
            result[key] = {
                'label': stat['label'], 'value': float(values[key]),
                'level': level, 'range': [0, 1], 'thresholds': stat['thresholds'][:],
                'active': active,
                'meaning': stat['descriptions'][level] if active else '現在のNN方式では行動に使われない',
                'strength': stat['strengths'][level] if active else '',
                'caution': stat['weaknesses'][level] if active else '',
            }
        return result

    def _state(self, org, world):
        base = (config.HERBIVORE_BASE_ENERGY_COST if org.org_type == 'herbivore'
                else config.CARNIVORE_BASE_ENERGY_COST) * (0.5 + org.genes['metabolism'])
        return {
            'energy': float(org.energy), 'max_energy': float(org.max_energy),
            'energy_ratio': float(org.energy / org.max_energy), 'age': int(org.age),
            'temperature_cost': float(org._calc_temp_penalty(world)),
            'base_cost': float(base), 'move_cost_per_cell_here': float(org._move_energy_cost(world)),
            'temperature_gap': abs(config.TEMPERATURE / 40 - float(org.genes['cold_resistance'])),
        }

    def build(self, world, target, selected=None):
        if target not in ('herbivore', 'carnivore', 'individual'):
            raise ValueError('解説の対象を選んでね。')
        living = [o for o in world.organisms if o.alive]
        if target == 'individual':
            if selected is None or selected not in living:
                raise ValueError('マップで生きている個体を選んでね。')
            species = selected.org_type
        else:
            species = target
        members = [o for o in living if o.org_type == species]
        if not members:
            raise ValueError('この種類の生物はいないよ。ルール解説を表示するね。')
        report = self.navigator.population(living, species, config.TEMPERATURE)
        states = [self._state(o, world) for o in members]
        means = {key: sum(row[key] for row in states) / len(states) for key in states[0]}
        # A still-alive animal can have negative energy just after paying a move cost.
        means['energy_ratio_level'] = self.classifier.classify('energy_ratio', max(0., min(1., means['energy_ratio'])))
        context = {
            'target': target, 'species': species,
            'species_label': self.classifier.data['species'][species],
            'snapshot': {'generation': int(world.generation), 'step': int(world.step_count),
                         'temperature_c': float(config.TEMPERATURE)},
            'action_mode': self.classifier.current_mode(),
            'counts': {s: sum(o.org_type == s for o in living) for s in ('herbivore', 'carnivore')},
            'population': {'count': len(members), 'mean_traits': self._traits(report['means']),
                           'distribution': report['distribution'], 'mean_state': means,
                           'profile': report['profile'], 'rule_comment': report['text']},
            'rules': {
                'temperature': '温度適性×40℃と現在気温の差が小さいほど温度消費が少ない。高いほど寒さに強いという意味ではない。砂漠は温度消費増。',
                'speed': '値は2マス移動の確率。速さだけで狩りや逃走の成功は決まらない。2マスなら移動消費も2回。',
                'metabolism': '高いほど容量と毎ステップの基本消費の両方が増える。',
                'terrain': '川・山の適応はそれぞれの地形での移動消費を減らす。海は通れない。',
                'hunger_threshold': 'NN方式では未使用。ルール方式のみ充足時の繁殖スコアに使う。',
                'reproduction': '充足率80%以上は必要条件のみ。年齢・行動選択・肉食の密度などの条件もある。',
            },
        }
        if selected is not None and target == 'individual':
            traits = self._traits(selected.genes)
            for key, trait in traits.items():
                delta = trait['value'] - report['means'][key]
                trait['difference_from_mean'] = delta
                trait['comparison'] = compare_to_mean(trait['value'], report['means'][key])
            state = self._state(selected, world)
            state['energy_ratio_level'] = self.classifier.classify('energy_ratio', max(0., min(1., state['energy_ratio'])))
            context['individual'] = {
                'traits': traits, 'state': state,
                'zone': world.get_zone(selected.x, selected.y),
                'comparison_margin': COMPARISON_MARGIN,
                'rule_comment': self.navigator.individual(selected, config.TEMPERATURE)['text'],
            }
        return context
