"""Read-only yearly snapshots using the game's existing seasonal calendar."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import config
from navigator_explainer import NavigatorExplainer
from season_effects import season_of, year_of


def annual_fallback(context):
    parts = ['途中までの記録だよ。'] if context['partial'] else []
    for species, label in (('herbivore', '草食たち'), ('carnivore', '肉食組')):
        row = context['changes'][species]
        delta = row['count_delta']
        if row['end_count'] == 0:
            change = '観察の終わりには姿が見えなくなったね' if row['start_count'] else '年初も観察の終わりも姿が見えなかったね'
        else:
            change = '仲間が増えたね' if delta > 0 else '仲間が減ったね' if delta < 0 else '数を保っているね'
        parts.append(label + 'は' + change + '。')
    candidates = context['notable_trait_changes']
    if candidates:
        top = candidates[0]
        direction = '上がった' if top['delta'] > 0 else '下がった'
        parts.append(f"{top['species_label']}の平均{top['label']}が{direction}のも注目だよ。")
    elif any(t['delta'] is not None and t['active'] for row in context['changes'].values() for t in row['traits'].values()):
        parts.append('行動に使う平均形質には、大きな変化が目立たなかったよ。')
    else:
        parts.append('比べられる平均形質がないから、数の変化を見ておこう。')
    parts.append('次の観察でも、両方の群れと蓄えに注目しよう！')
    return ''.join(parts)


class AnnualRecorder:
    def __init__(self):
        self.navigator = NavigatorExplainer()
        self.cycle = max(1, config.SEASON_CYCLE)
        self.starts = {}
        self.samples = {}
        self.records = {}
        self._generation = None
        self._last_step = -1

    def snapshot(self, world, generation):
        species = {}
        for key in ('herbivore', 'carnivore'):
            report = self.navigator.population(world.organisms, key, config.TEMPERATURE)
            species[key] = {k: copy.deepcopy(report[k]) for k in ('count', 'means', 'distribution', 'profile')}
        return {
            'generation': int(generation), 'step': int(world.step_count),
            'temperature_c': float(config.TEMPERATURE),
            'food_count': int(world.food_grid.sum()), 'land_ratio': float(world.land_ratio),
            'species': species,
        }

    def before_step(self, world):
        generation = int(world.generation)
        self._generation = generation
        year = year_of(generation)
        if world.step_count < self._last_step:
            # Rewind only unfinished observations. Completed reports are first-visit history.
            for y in list(self.samples):
                if y not in self.records:
                    self.samples[y] = {g: s for g, s in self.samples[y].items() if s['step'] <= world.step_count}
                    if y > year or self.starts[y]['step'] > world.step_count:
                        self.starts.pop(y, None)
                        self.samples.pop(y, None)
        self._last_step = world.step_count
        if year in self.records:
            return
        if year not in self.starts:
            self.starts[year] = self.snapshot(world, generation)
        sample = {'generation': generation, 'step': int(world.step_count),
                  'temperature_c': float(config.TEMPERATURE), 'season': season_of(generation),
                  'food_spawn_multiplier': float(config.SEASON_FOOD_MULT[season_of(generation)])}
        self.samples.setdefault(year, {})[generation] = sample

    def after_step(self, world, generation_finished, done, extinct):
        generation = self._generation
        year = year_of(generation)
        if year in self.records:
            return None
        boundary = generation_finished and generation % self.cycle == 0
        if not boundary and not done:
            return None
        start = self.starts[year]
        end = self.snapshot(world, generation)
        observations = list(self.samples[year].values())
        changes, notable = {}, []
        labels = {s['key']: s['label'] for s in self.navigator.classifier.stats}
        mode = self.navigator.classifier.current_mode()
        inactive = {s['key'] for s in self.navigator.classifier.stats if mode in s.get('inactive_in', [])}
        for key, label in (('herbivore', '草食'), ('carnivore', '肉食')):
            a, b = start['species'][key], end['species'][key]
            traits = {}
            for trait in sorted(a['means'].keys() | b['means'].keys()):
                first, last = a['means'].get(trait), b['means'].get(trait)
                delta = last - first if first is not None and last is not None else None
                traits[trait] = {'label': labels[trait], 'start': first, 'end': last, 'delta': delta,
                                 'active': trait not in inactive,
                                 'end_level': self.navigator.classifier.classify(trait, last) if last is not None else None}
                if delta is not None and abs(delta) >= .05 and trait not in inactive:
                    notable.append({'species_label': label, 'label': labels[trait], 'delta': delta})
            changes[key] = {'start_count': a['count'], 'end_count': b['count'],
                            'count_delta': b['count'] - a['count'],
                            'count_change_fraction': (b['count'] - a['count']) / a['count'] if a['count'] else None,
                            'traits': traits, 'end_distribution': b['distribution'], 'end_profile': b['profile']}
        notable.sort(key=lambda r: (-abs(r['delta']), r['species_label'], r['label']))
        partial = (not boundary or start['generation'] != (year - 1) * self.cycle + 1
                   or start['step'] % config.MAX_STEPS_PER_GEN != 0)
        temperatures = [s['temperature_c'] for s in observations] + [end['temperature_c']]
        context = {
            'target': 'annual', 'year': year, 'generations_per_year': self.cycle,
            'partial': partial, 'reason': 'extinction' if extinct else 'year_end' if boundary else 'simulation_end',
            'action_mode': mode, 'start': start, 'end': end, 'snapshot': {'generation': generation, 'step': end['step']},
            'changes': changes, 'notable_trait_changes': notable,
            'environment': {'temperature_start': start['temperature_c'], 'temperature_end': end['temperature_c'],
                            'temperature_delta': end['temperature_c'] - start['temperature_c'],
                            'observed_temperature_min': min(temperatures), 'observed_temperature_max': max(temperatures),
                            'generation_observations': observations,
                            'food_count_delta': end['food_count'] - start['food_count'],
                            'events': None, 'event_note': '災害・環境イベントの履歴取得機能はない。演出を災害と解釈しない。'},
            'interpretation': '平均の変化は遺伝の因果証明ではない。絶滅後の平均はnull。温度適性は高いほど寒さに強いという意味ではない。代謝は容量と基本消費の両方を増す。速度は2マス移動の確率、川と山の適応は該当地形での移動消費を減らす。環境と増減の因果は未検証。',
        }
        self.records[year] = copy.deepcopy(context)
        return context


class AnnualHistory:
    def __init__(self, log_path=None):
        self.recorder = AnnualRecorder()
        self.entries = {}
        self.selected_year = None  # None follows the latest completed response.
        self.log_path = Path(log_path) if log_path is not None else Path.cwd() / 'reports' / (
            datetime.now(timezone.utc).strftime('annual_%Y%m%dT%H%M%S_') + uuid.uuid4().hex[:8] + '.json')
        self.save_error = ''

    def add(self, context):
        year = context['year']
        if year in self.entries:
            return False
        self.entries[year] = {'context': copy.deepcopy(context), 'fallback': annual_fallback(context),
                              'status': 'queued', 'text': '', 'error': '', 'raw_response': None, 'request': None}
        self.save()
        return True

    def save(self):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.log_path.with_suffix('.tmp')
            temp.write_text(json.dumps({'calendar': {'generations_per_year': self.recorder.cycle},
                                        'reports': list(self.entries.values())}, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
            temp.replace(self.log_path)
            self.save_error = ''
        except (OSError, ValueError):
            self.save_error = 'レポートを保存できないよ。画面の履歴は引き続き使えるよ。'

    def displayed(self):
        if self.selected_year is not None:
            return self.entries.get(self.selected_year)
        ready = [y for y, r in self.entries.items() if r['status'] in ('ready', 'fallback', 'interrupted')]
        return self.entries[max(ready)] if ready else None

    def navigate(self, direction):
        years = sorted(y for y, r in self.entries.items() if r['status'] in ('ready', 'fallback', 'interrupted'))
        if not years:
            return
        current = self.selected_year if self.selected_year in years else years[-1]
        self.selected_year = years[max(0, min(len(years) - 1, years.index(current) + direction))]
