"""Explicit Windows/local-PC smoke test. No requests are sent by importing it."""
import argparse
import json
import sys

from ecosystem_ai_context import EcosystemAIContext
from ollama_explainer import OllamaError, OllamaExplainer
from world import World


def main():
    parser = argparse.ArgumentParser(description='実機のOllamaで3種類のAIナビを確認（ゲームの保存データは変更しません）')
    parser.add_argument('--target', choices=('all', 'herbivore', 'carnivore', 'individual'), default='all')
    parser.add_argument('--context-only', action='store_true', help='送信せず、Pythonで整理したデータだけ表示')
    args = parser.parse_args()
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
