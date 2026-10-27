"""観察モードのセーブ/ロード (スロットは1つ。saves/ フォルダに保存する)。

保存するもの: World・反映済みの設定値(config)・乱数の状態(np.random / random)・世代内ステップなど。
注意: 保存はpickle形式なので、自分で作ったセーブファイル以外は読み込まないこと。
"""
import os
import pickle
import random
from pathlib import Path

import numpy as np

import config

SAVE_DIR = Path(__file__).resolve().parent / "saves"
SAVE_PATH = SAVE_DIR / "savegame.pkl"
SAVE_VERSION = 1

# セーブ/ロード時にまとめて保存・復元するconfigの値 (設定画面の項目と、そこから決まる気温など)
CONFIG_KEYS = (
    "USE_NEUROEVOLUTION", "RL_LEARNING_RATE", "SEASONS_ENABLED",
    "TEMP_SUMMER", "TEMP_WINTER", "TEMPERATURE", "SEASON_FOOD_MULT",
    "INITIAL_HERBIVORES", "INITIAL_CARNIVORES",
)


class LoadError(Exception):
    """ロードに失敗したときの、画面に出す用のメッセージ付きの例外"""


def save_exists():
    return SAVE_PATH.is_file()


def save_game(world, step_in_gen, extinct, done):
    state = {
        "version": SAVE_VERSION,
        "config": {k: getattr(config, k) for k in CONFIG_KEYS},
        "world": world,
        "np_random_state": np.random.get_state(),
        "py_random_state": random.getstate(),
        "generation": world.generation,
        "step_in_gen": step_in_gen,
        "extinct": extinct,
        "done": done,
    }
    SAVE_DIR.mkdir(exist_ok=True)
    tmp = SAVE_PATH.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, SAVE_PATH)      # 書き込み途中で落ちても、前のセーブを壊さない


def load_game():
    """セーブを読み込み、configと乱数の状態を復元して、再開用の辞書(world, step_in_gen, extinct, done)を返す。
    失敗したときは LoadError (メッセージは画面表示用)。"""
    if not save_exists():
        raise LoadError("セーブデータがありません")
    try:
        with open(SAVE_PATH, "rb") as f:
            state = pickle.load(f)
    except Exception:
        raise LoadError("セーブデータが壊れているため読み込めません")
    try:
        if not isinstance(state, dict) or state.get("version") != SAVE_VERSION:
            raise LoadError("セーブデータの形式が古い(または新しい)ため読み込めません")
        saved_config = state["config"]
        world = state["world"]
        if not all(k in saved_config for k in CONFIG_KEYS) or not hasattr(world, "organisms"):
            raise LoadError("セーブデータの内容が不完全なため読み込めません")
        resume = {"world": world, "step_in_gen": int(state["step_in_gen"]),
                  "extinct": bool(state["extinct"]), "done": bool(state["done"])}
        np_state, py_state = state["np_random_state"], state["py_random_state"]
    except LoadError:
        raise
    except Exception:
        raise LoadError("セーブデータの内容が不完全なため読み込めません")
    # ここまで問題なければ、configと乱数の状態を反映する (途中で失敗して中途半端に反映しないよう最後にまとめて)
    for k, v in saved_config.items():
        setattr(config, k, v)
    np.random.set_state(np_state)
    random.setstate(py_state)
    return resume
