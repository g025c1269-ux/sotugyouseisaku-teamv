"""ステージの初期設定 (data/stages.json) から世界を作る。ゲーム画面はまだ作らない。

build_world(stage): ステージの設定を config に反映してから World() を作って返す。
restore(): build_world が書き換えた config を、build_world を呼ぶ前の値に戻す (ステージを抜けるときに呼ぶ)。

ステージの設定項目 (すべて任意。null または省略なら、config.py の既定値を使う):
  initial_herbivores / initial_carnivores / initial_food : 初期の草食数・肉食数・食料の数
  food_mult        : 食料の季節倍率。数値1つ(4季節とも同じ)か、季節名のdict
  fixed_temperature: 数値なら季節をオフにして気温を固定する (設定画面の季節オフと同じ扱い。0〜40に丸める)
  gene_ranges      : 初期の生き物の遺伝子の範囲の上書き。例 {"cold_resistance": [0.0, 0.4]}
  terrain_seed     : 地形を作るシード。nullならランダム
  warmup_generations: 準備運転の世代数 (通常の季節倍率で回してから、food_mult などを反映してプレイ開始)。nullなら準備運転なし
  preset           : 準備運転を終えた世界のファイル (tools/make_preset.py で作る)。読めればそれを使い、読めなければ従来の作り方
  warmup_seed      : 世界の生き物の初期値と準備運転の乱数のシード (これを入れると毎回同じ準備運転後の世界になる)
  clear_generations: クリアに必要な世代数 (build_worldでは使わない。ゲーム側が読む)
"""
import copy
import importlib.util
import os
import pickle
import sys
from pathlib import Path

import numpy as np

import config
import world as world_module
from world import World

SEASONS = ("spring", "summer", "autumn", "winter")
# 遺伝子名 → configの範囲の名前 (脳(ニューラルネット)は範囲を持たず、今までどおりランダム)
GENE_RANGE_KEYS = {
    "cold_resistance": "GENE_COLD_RESISTANCE_RANGE",
    "speed": "GENE_SPEED_RANGE",
    "metabolism": "GENE_METABOLISM_RANGE",
    "river_tolerance": "GENE_RIVER_TOLERANCE_RANGE",
    "mountain_tolerance": "GENE_MOUNTAIN_TOLERANCE_RANGE",
}
# build_worldが書き換える可能性のあるconfigの値。ステージごとに、config.pyの既定値から作り直す
MANAGED_KEYS = (
    "INITIAL_HERBIVORES", "INITIAL_CARNIVORES", "INITIAL_FOOD",
    "SEASON_FOOD_MULT", "SEASONS_ENABLED", "TEMP_SUMMER", "TEMP_WINTER", "TEMPERATURE",
    "USE_NEUROEVOLUTION", "RL_LEARNING_RATE",
    "GENE_COLD_RESISTANCE_RANGE", "GENE_SPEED_RANGE", "GENE_HUNGER_THRESHOLD_RANGE",
    "GENE_METABOLISM_RANGE", "GENE_RIVER_TOLERANCE_RANGE", "GENE_MOUNTAIN_TOLERANCE_RANGE",
)

PRESET_VERSION = 1     # プリセットファイルの形式のバージョン (保存する中身を変えたら上げる)

_saved = None          # build_world を呼ぶ前のconfigの値 (restoreで戻す)
_pristine = None       # config.py に書かれている既定値


def _pristine_config():
    """config.py をファイルから読み直した既定値。観察モードの設定画面などで config が書き換わっていても、
    ステージは必ず既定値から始めるために使う。"""
    global _pristine
    if _pristine is None:
        spec = importlib.util.spec_from_file_location("config_pristine", config.__file__)
        _pristine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_pristine)
    return _pristine


def _number(stage, key, lo=None, hi=None, integer=False):
    value = stage.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"ステージ'{stage.get('id')}'の {key} は数値にしてください: {value!r}")
    value = int(round(value)) if integer else float(value)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def apply_stage_config(stage):
    """ステージの設定を config に反映する (World() を作る前に呼ぶこと)。"""
    default = _pristine_config()
    for key in MANAGED_KEYS:                           # まず既定値に揃える (前に遊んだ設定を引きずらない)
        setattr(config, key, copy.deepcopy(getattr(default, key)))

    for key, name in (("initial_herbivores", "INITIAL_HERBIVORES"), ("initial_carnivores", "INITIAL_CARNIVORES"),
                      ("initial_food", "INITIAL_FOOD")):
        value = _number(stage, key, lo=0, integer=True)
        if value is not None:
            setattr(config, name, value)

    # 食料の季節倍率: 数値1つ(4季節とも同じ) か 季節名のdict(書かなかった季節は既定値のまま)
    mult = stage.get("food_mult")
    if isinstance(mult, dict):
        unknown = set(mult) - set(SEASONS)
        if unknown:
            raise ValueError(f"ステージ'{stage.get('id')}'の food_mult に知らない季節があります: {sorted(unknown)}")
        config.SEASON_FOOD_MULT = {**config.SEASON_FOOD_MULT, **{k: float(v) for k, v in mult.items()}}
    elif mult is not None:
        config.SEASON_FOOD_MULT = {k: float(_number(stage, "food_mult", lo=0.0)) for k in SEASONS}

    # 気温を固定する = 季節をオフにする (設定画面の季節オフと同じ。食料倍率の指定がなければ全季節1.0)
    fixed = _number(stage, "fixed_temperature", lo=0.0, hi=40.0)
    if fixed is not None:
        config.SEASONS_ENABLED = False
        config.TEMP_SUMMER = config.TEMP_WINTER = fixed      # 両者が同じなら update_temperature は固定気温になる
        config.TEMPERATURE = fixed
        if mult is None:
            config.SEASON_FOOD_MULT = {k: 1.0 for k in SEASONS}

    # 初期の遺伝子の範囲 (そのステージの間は有効のまま。あとから補充する個体も同じ範囲で生まれる)
    ranges = stage.get("gene_ranges")
    if ranges:
        unknown = set(ranges) - set(GENE_RANGE_KEYS)
        if unknown:
            raise ValueError(f"ステージ'{stage.get('id')}'の gene_ranges に知らない遺伝子があります: {sorted(unknown)}")
        for gene, pair in ranges.items():
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise ValueError(f"gene_ranges の {gene} は [最小, 最大] にしてください: {pair!r}")
            lo, hi = sorted(max(0.0, min(1.0, float(v))) for v in pair)
            setattr(config, GENE_RANGE_KEYS[gene], [lo, hi])


def _seeded_terrain(seed):
    """generate_zone_map を、地形を作る間だけシードを固定して呼ぶ関数に包む (呼んだあとは乱数を元の状態に戻す)。"""
    original = world_module.generate_zone_map

    def generate(n):
        state = np.random.get_state()
        np.random.seed(seed)
        try:
            return original(n)
        finally:
            np.random.set_state(state)       # 生き物の動きなどの乱数は、元の(ランダムな)状態のまま
    return generate


def _warm_up(world, generations):
    """準備運転: 画面を出さずに、通常の季節倍率 (config.py の既定値) で世代を回す。
    終わったら、プレイの1世代目が「1年目の春」になるように世代の数え方と記録を最初に戻す。"""
    stage_mult = config.SEASON_FOOD_MULT
    config.SEASON_FOOD_MULT = copy.deepcopy(_pristine_config().SEASON_FOOD_MULT)
    try:
        for _ in range(generations):
            if not world.run_generation():       # 全滅したら、そこで止める
                break
    finally:
        config.SEASON_FOOD_MULT = stage_mult     # ステージの食料倍率を反映
    world.generation = 0
    world.history = {key: [] for key in world.history}
    world.update_temperature()


def save_preset(world, path, stage_id):
    """準備運転を終えた世界と、反映済みのconfigの値を保存する (tools/make_preset.py から呼ぶ)。乱数の状態は保存しない。"""
    state = {
        "version": PRESET_VERSION,
        "stage_id": stage_id,
        "config": {key: copy.deepcopy(getattr(config, key)) for key in MANAGED_KEYS},
        "world": world,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)                    # 書き込み途中で落ちても、前のファイルを壊さない


def _load_preset(stage):
    """stage の preset を読み込み、configに反映して World を返す。読めなければログを出して None (従来の作り方に切り替える)。
    注意: pickle形式なので、自分で作ったプリセット以外は読み込まないこと。"""
    path = stage.get("preset")
    if not path:
        return None
    path = Path(path) if Path(path).is_absolute() else Path(__file__).resolve().parent / path
    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
        if not isinstance(state, dict) or state.get("version") != PRESET_VERSION:
            raise ValueError("形式のバージョンが違います")
        saved_config, world = state["config"], state["world"]
        if not all(key in saved_config for key in MANAGED_KEYS) or not hasattr(world, "organisms"):
            raise ValueError("内容が不完全です")
    except Exception as e:
        print(f"[stage_setup] プリセット {path} を読めません ({type(e).__name__}: {e})。"
              f"シードから世界を作り直します (時間がかかります)", file=sys.stderr)
        return None
    for key in MANAGED_KEYS:                 # 問題なければ、最後にまとめて反映する
        setattr(config, key, copy.deepcopy(saved_config[key]))
    np.random.seed(None)                     # 読み込んだあとの乱数は、毎回ランダム
    return world


def build_world(stage):
    """ステージの設定を config に反映して、World() を作って返す。ステージを抜けるときは restore() を呼ぶ。
    stage に preset があり読めれば、準備運転を終えた世界をそのファイルから読み込む (数秒)。
    なければ、warmup_generations があれば、世界を作ったあとに準備運転をする (warmup_seed があれば、世界の生き物の
    初期値と準備運転の乱数を固定する)。準備運転が終わったら乱数はランダムに戻る。"""
    global _saved
    if _saved is None:                       # 二重に呼ばれても、いちばん最初の状態へ戻せるようにする
        _saved = {key: copy.deepcopy(getattr(config, key)) for key in MANAGED_KEYS}
    world = _load_preset(stage)
    if world is not None:
        return world
    apply_stage_config(stage)
    seed = _number(stage, "terrain_seed", integer=True)
    warmup = _number(stage, "warmup_generations", lo=0, integer=True) or 0
    warmup_seed = _number(stage, "warmup_seed", integer=True) if warmup else None
    original = world_module.generate_zone_map
    if seed is not None:
        world_module.generate_zone_map = _seeded_terrain(seed)
    try:
        if warmup_seed is not None:
            np.random.seed(warmup_seed)
        world = World()
        if warmup:
            _warm_up(world, warmup)
    finally:
        world_module.generate_zone_map = original
        if warmup_seed is not None:
            np.random.seed(None)             # プレイ中の乱数は、毎回ランダム
    return world


def restore():
    """build_world が書き換えた config を、build_world を呼ぶ前の値に戻す。何度呼んでも安全。"""
    global _saved
    if _saved is not None:
        for key, value in _saved.items():
            setattr(config, key, copy.deepcopy(value))
        _saved = None
