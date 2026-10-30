"""Prioritize measured annual changes for the LLM, without touching the recorder.

Rule references describe possible mechanisms, never measured causes of death or
selection. Full snapshots remain in the existing annual audit/history file.
"""
import math


SPECIES = ('herbivore', 'carnivore')
TRAIT_REFERENCES = {
    'metabolism': '低下すると基本消費と容量がともに小さくなる。食料が減る場面では消費を抑える方向だが、低代謝の個体が生き残った証拠ではない。',
    'speed': '高いほど2マス移動の確率が増え、移動消費も増える。狩りや逃走の成否は速度だけでは決まらない。',
    'cold_resistance': '適温は遺伝子値×40℃。現在気温とのずれで消費が増える。高いほど寒さに強い、ではない。',
    'river_tolerance': '低下すると川での移動消費が増える。実際に川を通ったか、魚を捕ったかは未取得。',
    'mountain_tolerance': '高まると山での移動消費を抑えやすい。実際の移動地形は未取得なので、山を使う場合の影響として考える。',
    'hunger_threshold': 'ルール方式で充足時の繁殖選択の重みに使う。NN方式では未使用。',
}


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return round(value, 6)
    return None


def _change(first, last):
    first, last = _number(first), _number(last)
    return {'start': first, 'end': last,
            'delta': round(last - first, 6) if first is not None and last is not None else None}


def build_annual_ai_context(context):
    """Pure projection of completed observations; do not infer missing values."""
    changes = context.get('changes', {})
    environment = context.get('environment', {})
    populations, notable, temperature_fit = {}, [], {}
    for species in SPECIES:
        row = changes.get(species, {})
        population = _change(row.get('start_count'), row.get('end_count'))
        population['change_fraction'] = (round(population['delta'] / population['start'], 6)
                                         if population['start'] and population['delta'] is not None else None)
        populations[species] = population
        traits = row.get('traits', {})
        for key, trait in traits.items():
            values = _change(trait.get('start'), trait.get('end'))
            if trait.get('active') is True and values['delta'] is not None and abs(values['delta']) >= .05:
                notable.append({'species': species, 'trait': key, 'label': trait['label'], **values})
        cold = traits.get('cold_resistance', {})
        fit = {}
        for endpoint in ('start', 'end'):
            gene = _number(cold.get(endpoint))
            air = _number(environment.get('temperature_' + endpoint))
            preferred = round(gene * 40, 6) if gene is not None else None
            fit[endpoint] = {
                'air_c': air, 'mean_preferred_c': preferred,
                'gap_of_means_c': round(abs(preferred - air), 6)
                if air is not None and preferred is not None else None,
            }
        temperature_fit[species] = fit

    notable.sort(key=lambda item: (-abs(item['delta']), item['species'], item['trait']))
    notable = notable[:2]
    temperature = _change(environment.get('temperature_start'), environment.get('temperature_end'))
    temperature.update(observed_min=_number(environment.get('observed_temperature_min')),
                       observed_max=_number(environment.get('observed_temperature_max')))
    food = _change(context.get('start', {}).get('food_count'), context.get('end', {}).get('food_count'))
    if food['delta'] is None:
        food['delta'] = _number(environment.get('food_count_delta'))

    references = {item['trait']: TRAIT_REFERENCES[item['trait']]
                  for item in notable if item['trait'] in TRAIT_REFERENCES}
    if temperature['delta'] or (temperature['observed_min'] is not None
                                and temperature['observed_min'] != temperature['observed_max']):
        references['cold_resistance'] = TRAIT_REFERENCES['cold_resistance']
    references['food_chain'] = '草食は食物を食べ、肉食は草食を捕食して蓄えを得る。肉食には川での魚捕りもあり、草食数だけで餓死を断定できない。'

    return {
        'target': 'annual', 'year': context.get('year'), 'partial': context.get('partial'),
        'observations': {
            'populations': populations, 'notable_traits': notable,
            'food_cells': food, 'temperature_c': temperature,
            'temperature_fit': temperature_fit,
            'zero_at_end': [species for species, row in populations.items() if row['end'] == 0],
        },
        'reference_for_observed_changes': references,
        'limits': [
            '平均の変化から個々の死亡・繁殖・遺伝の原因は確定できない。',
            'gap_of_means_cは平均適温と気温の差で、個体ごとの消耗の平均ではない。',
            '食物は存在するマス数の開始/終了比較で、年内の摂食量ではない。',
            '災害、捕食成功数、移動地形は未取得。年末0匹の種の自然な復活は仮定しない。',
        ],
    }


def is_rule_recital(text):
    """Reject clear manuals only; a normal observed change prevents rejection.

    Intentionally conservative. This does not prove factuality or require every
    valid response to use particular hypothesis/future keywords.
    """
    import re
    rules = (
        r'代謝(?:は|が高いほど).{0,25}(?:容量|基本消費)',
        r'(?:移動)?速度(?:は|が高いほど).{0,25}(?:2マス|確率)',
        r'(?:温度適性|温度適応).{0,25}(?:寒さに強い|解釈されない|ずれ.*消費)',
        r'(?:川|山)適応(?:は|が高いほど).{0,25}(?:移動|コスト|消費)',
        r'環境と(?:増減|形質変化)の因果.{0,10}未検証',
    )
    definitions = sum(bool(re.search(rule, text)) for rule in rules)
    observation = re.search(
        r'増えた|減った|増えて|減って|増加し|減少し|低下し|上昇し|上がっ|下がっ|'
        r'高まった|低くなった|高くなった|変わら(?:ず|ない|なかった)|横ばい|数を保|'
        r'ゼロ|0匹|全滅|姿が見えなく|いなくなった|\d+匹|\d+(?:\.\d+)?\s*(?:→|から)\s*\d+', text)
    return definitions >= 2 and observation is None
