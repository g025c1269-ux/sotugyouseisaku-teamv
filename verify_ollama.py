"""Explicit Windows/local-PC smoke test. No requests are sent by importing it."""
import argparse
import json
from pathlib import Path
import sys

from ecosystem_ai_context import EcosystemAIContext
from ollama_explainer import OllamaError, OllamaExplainer
from world import World


def main():
    parser = argparse.ArgumentParser(description='実機のOllamaで3種類のAIナビを確認（ゲームの保存データは変更しません）')
    parser.add_argument('--target', choices=('all', 'herbivore', 'carnivore', 'individual'), default='all')
    parser.add_argument('--context-only', action='store_true', help='送信せず、Pythonで整理したデータだけ表示')
    parser.add_argument('--annual-report', type=Path, help='保存したreports/annual_*.jsonから年間総括を再確認（元ファイルは変更しない）')
    parser.add_argument('--year', type=int, help='確認する年。省略時は保存された最新年')
    args = parser.parse_args()
    if args.annual_report:
        try:
            reports = json.loads(args.annual_report.read_text(encoding='utf-8'))['reports']
            rows = [r for r in reports if args.year is None or r['context']['year'] == args.year]
            if not rows:
                raise ValueError('指定した年の記録がありません。')
            context = max(rows, key=lambda r: r['context']['year'])['context']
            if args.context_only:
                print(json.dumps(context, ensure_ascii=False, indent=2))
            else:
                text = OllamaExplainer().generate(context)
                print(f"{context['year']}年目の総括（保存済み入力の再送信）\n{text}\n文字数: {len(text)}")
        except (OllamaError, OSError, ValueError, KeyError, TypeError) as exc:
            print(f'確認できませんでした: {exc}', file=sys.stderr)
            return 1
        return 0
    world = World()
    world.generation = 1
    world.update_temperature()
    selected = next(o for o in world.organisms if o.alive and o.org_type == 'herbivore')
    builder = EcosystemAIContext()
    targets = ('herbivore', 'carnivore', 'individual') if args.target == 'all' else (args.target,)
    try:
        client = None if args.context_only else OllamaExplainer()
        if client:
            print(f'接続先: {client.settings.base_url} / モデル: {client.settings.model} / think=False')
        for target in targets:
            context = builder.build(world, target, selected)
            print(f'\n対象: {target}')
            if args.context_only:
                print(json.dumps(context, ensure_ascii=False, indent=2))
            else:
                text = client.generate(context)
                print(f'{text}\n文字数: {len(text)}（40〜80文字を検証済み）')
    except (OllamaError, ValueError) as exc:
        print(f'確認できませんでした: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
