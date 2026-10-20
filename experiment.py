# =============================================
# experiment.py — 気温を変えた自動比較実験
# 複数の気温で実験を自動的に繰り返し実行し、結果をCSVと比較グラフに出力する
# python experiment.py で実行する
# =============================================

import os
import csv
import numpy as np
import matplotlib.pyplot as plt
import japanize_matplotlib
import config
from world import World

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH   = os.path.join(SCRIPT_DIR, "experiment_results.csv")
GRAPH_PATH = os.path.join(SCRIPT_DIR, "experiment_comparison.png")

TEMPERATURES = [5.0, 15.0, 25.0, 35.0]
GENERATIONS  = 50
MAX_RETRIES  = 3   # 絶滅した場合、別シードで最大3回リトライする


# --------------------------------------------------
# 1回分の実験を実行する
# --------------------------------------------------
# 四季は常時有効なので、固定気温の実験ではTEMP_SUMMER=TEMP_WINTER=固定気温にして一時的に無効化する
DEFAULT_TEMP_SUMMER = config.TEMP_SUMMER
DEFAULT_TEMP_WINTER = config.TEMP_WINTER


def _set_fixed_temperature(temp):
    config.TEMP_SUMMER = temp
    config.TEMP_WINTER = temp
    config.TEMPERATURE = temp


def _restore_seasons():
    config.TEMP_SUMMER = DEFAULT_TEMP_SUMMER
    config.TEMP_WINTER = DEFAULT_TEMP_WINTER


def run_once(temp, seed):
    np.random.seed(seed)
    _set_fixed_temperature(temp)
    world = World()
    extinct = False
    try:
        for _ in range(GENERATIONS):
            world.run_generation()
            h = world.history
            if h["herbivore_count"][-1] == 0 or h["carnivore_count"][-1] == 0:
                extinct = True
                break
    finally:
        _restore_seasons()
    return world.history, extinct


# --------------------------------------------------
# 1つの気温条件を実行し、絶滅したら別シードでリトライする
# --------------------------------------------------
def run_temperature(temp_index, temp):
    history, extinct, seed = None, True, None
    for attempt in range(MAX_RETRIES + 1):
        seed = 1000 + temp_index * 100 + attempt
        history, extinct = run_once(temp, seed)
        status = "絶滅" if extinct else "生存"
        print(
            f"  attempt {attempt + 1}/{MAX_RETRIES + 1} (seed={seed}): {status}"
            f" (最終世代 herb={history['herbivore_count'][-1]}"
            f" carn={history['carnivore_count'][-1]})"
        )
        if not extinct:
            break
    return history, extinct, seed


# --------------------------------------------------
# NaNをCSVに書き込みやすい形に変換する
# --------------------------------------------------
def _clean(value):
    if isinstance(value, float) and np.isnan(value):
        return ""
    return value


# --------------------------------------------------
# CSVに保存
# --------------------------------------------------
def save_csv(rows):
    fieldnames = [
        "temperature", "seed", "generation",
        "herbivore_count", "carnivore_count",
        "herb_cold_resistance", "carn_cold_resistance",
        "herb_speed", "carn_speed",
        "herb_metabolism", "carn_metabolism",
        "herb_river_tolerance", "carn_river_tolerance",
        "herb_mountain_tolerance", "carn_mountain_tolerance",
        "extinct",
    ]
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSVを保存しました: {CSV_PATH}")


# --------------------------------------------------
# 4条件を重ねた比較グラフを保存
# --------------------------------------------------
def save_graph(all_histories):
    colors = {5.0: "#1976d2", 15.0: "#388e3c", 25.0: "#f57c00", 35.0: "#d32f2f"}
    fig, axes = plt.subplots(8, 2, figsize=(13, 33))
    fig.suptitle("気温別 比較実験結果", fontsize=14)

    for temp, h in all_histories.items():
        color = colors.get(temp)
        label = f"{int(temp)}°C"
        axes[0, 0].plot(h["generation"], h["herbivore_count"], color=color, label=label, linewidth=1.8)
        axes[0, 1].plot(h["generation"], h["carnivore_count"], color=color, label=label, linewidth=1.8)
        axes[1, 0].plot(h["generation"], h["herb_cold_resistance"], color=color, label=label, linewidth=1.8)
        axes[1, 1].plot(h["generation"], h["carn_cold_resistance"], color=color, label=label, linewidth=1.8)
        axes[2, 0].plot(h["generation"], h["herb_speed"], color=color, label=label, linewidth=1.8)
        axes[2, 1].plot(h["generation"], h["carn_speed"], color=color, label=label, linewidth=1.8)
        axes[3, 0].plot(h["generation"], h["herb_metabolism"], color=color, label=label, linewidth=1.8)
        axes[3, 1].plot(h["generation"], h["carn_metabolism"], color=color, label=label, linewidth=1.8)
        axes[4, 0].plot(h["generation"], h["herb_river_tolerance"], color=color, label=label, linewidth=1.8)
        axes[4, 1].plot(h["generation"], h["carn_river_tolerance"], color=color, label=label, linewidth=1.8)
        axes[5, 0].plot(h["generation"], h["herb_mountain_tolerance"], color=color, label=label, linewidth=1.8)
        axes[5, 1].plot(h["generation"], h["carn_mountain_tolerance"], color=color, label=label, linewidth=1.8)

        # ゾーン適応の比較: 全体平均(実線) vs ゾーン内平均(破線)
        axes[6, 0].plot(h["generation"], h["herb_mountain_tolerance"], color=color,
                         linestyle="-", linewidth=1.8, label=f"{label} 全体")
        axes[6, 0].plot(h["generation"], h["herb_mountain_tolerance_in_zone"], color=color,
                         linestyle="--", linewidth=1.8, label=f"{label} 山ゾーン内")
        axes[6, 1].plot(h["generation"], h["carn_mountain_tolerance"], color=color,
                         linestyle="-", linewidth=1.8, label=f"{label} 全体")
        axes[6, 1].plot(h["generation"], h["carn_mountain_tolerance_in_zone"], color=color,
                         linestyle="--", linewidth=1.8, label=f"{label} 山ゾーン内")
        axes[7, 0].plot(h["generation"], h["herb_river_tolerance"], color=color,
                         linestyle="-", linewidth=1.8, label=f"{label} 全体")
        axes[7, 0].plot(h["generation"], h["herb_river_tolerance_in_zone"], color=color,
                         linestyle="--", linewidth=1.8, label=f"{label} 川ゾーン内")
        axes[7, 1].plot(h["generation"], h["carn_river_tolerance"], color=color,
                         linestyle="-", linewidth=1.8, label=f"{label} 全体")
        axes[7, 1].plot(h["generation"], h["carn_river_tolerance_in_zone"], color=color,
                         linestyle="--", linewidth=1.8, label=f"{label} 川ゾーン内")

    axes[0, 0].set_title("草食動物の個体数")
    axes[0, 1].set_title("肉食動物の個体数")
    axes[1, 0].set_title("草食動物の耐寒性(平均)")
    axes[1, 1].set_title("肉食動物の耐寒性(平均)")
    axes[2, 0].set_title("草食動物のspeed(平均)")
    axes[2, 1].set_title("肉食動物のspeed(平均)")
    axes[3, 0].set_title("草食動物のmetabolism(平均)")
    axes[3, 1].set_title("肉食動物のmetabolism(平均)")
    axes[4, 0].set_title("草食動物のriver_tolerance(平均)")
    axes[4, 1].set_title("肉食動物のriver_tolerance(平均)")
    axes[5, 0].set_title("草食動物のmountain_tolerance(平均)")
    axes[5, 1].set_title("肉食動物のmountain_tolerance(平均)")
    axes[6, 0].set_title("草食動物の山耐性: 全体 vs 山ゾーン内")
    axes[6, 1].set_title("肉食動物の山耐性: 全体 vs 山ゾーン内")
    axes[7, 0].set_title("草食動物の川耐性: 全体 vs 川ゾーン内")
    axes[7, 1].set_title("肉食動物の川耐性: 全体 vs 川ゾーン内")

    axes[0, 0].set_ylabel("個体数")
    axes[0, 1].set_ylabel("個体数")
    for row in range(1, 8):
        axes[row, 0].set_ylabel("遺伝子の値 (0〜1)")
        axes[row, 1].set_ylabel("遺伝子の値 (0〜1)")
        axes[row, 0].set_ylim(0, 1)
        axes[row, 1].set_ylim(0, 1)

    for ax in axes.flat:
        ax.set_xlabel("世代")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(GRAPH_PATH, dpi=150, bbox_inches="tight")
    print(f"比較グラフを保存しました: {GRAPH_PATH}")


# --------------------------------------------------
# エントリーポイント
# --------------------------------------------------
def main():
    all_rows = []
    all_histories = {}

    for temp_index, temp in enumerate(TEMPERATURES):
        print(f"\n=== 気温 {temp}°C の実験開始 ===")
        history, extinct, seed = run_temperature(temp_index, temp)
        all_histories[temp] = history

        for i, gen in enumerate(history["generation"]):
            all_rows.append({
                "temperature":          temp,
                "seed":                 seed,
                "generation":           gen,
                "herbivore_count":      history["herbivore_count"][i],
                "carnivore_count":      history["carnivore_count"][i],
                "herb_cold_resistance": _clean(history["herb_cold_resistance"][i]),
                "carn_cold_resistance": _clean(history["carn_cold_resistance"][i]),
                "herb_speed":           _clean(history["herb_speed"][i]),
                "carn_speed":           _clean(history["carn_speed"][i]),
                "herb_metabolism":      _clean(history["herb_metabolism"][i]),
                "carn_metabolism":      _clean(history["carn_metabolism"][i]),
                "herb_river_tolerance": _clean(history["herb_river_tolerance"][i]),
                "carn_river_tolerance": _clean(history["carn_river_tolerance"][i]),
                "herb_mountain_tolerance": _clean(history["herb_mountain_tolerance"][i]),
                "carn_mountain_tolerance": _clean(history["carn_mountain_tolerance"][i]),
                "extinct":              extinct,
            })

        if extinct:
            print(f"-> 気温{temp}°C: {MAX_RETRIES + 1}回試行してもすべて絶滅 (絶滅として記録)")
        else:
            print(
                f"-> 気温{temp}°C: 生存 (最終世代 "
                f"herb={history['herbivore_count'][-1]} "
                f"carn={history['carnivore_count'][-1]})"
            )

    save_csv(all_rows)
    save_graph(all_histories)


# =============================================
# 季節変化モードの実験 (python experiment.py seasons)
# 季節変化(TEMP_SUMMER/WINTERそのまま)で100世代走らせ、固定気温(15℃・35℃)と比較する
# =============================================
SEASON_GENERATIONS = 100
SEASON_SEEDS       = 5
SEASON_CSV_PATH    = os.path.join(SCRIPT_DIR, "experiment_seasons.csv")
SEASON_GRAPH_PATH  = os.path.join(SCRIPT_DIR, "experiment_seasons.png")
SEASON_CONDITIONS  = [("季節変化", None), ("固定15°C", 15.0), ("固定35°C", 35.0)]
SEASON_COLORS      = {"季節変化": "#d81b60", "固定15°C": "#388e3c", "固定35°C": "#d32f2f"}


def run_season_once(temp, seed):
    """temp=Noneなら季節変化ON、数値なら固定気温。戻り値: (history, 絶滅したか)"""
    np.random.seed(seed)
    if temp is not None:
        _set_fixed_temperature(temp)
    world = World()
    extinct = False
    try:
        for _ in range(SEASON_GENERATIONS):
            world.run_generation()
            h = world.history
            if h["herbivore_count"][-1] == 0 or h["carnivore_count"][-1] == 0:
                extinct = True
                break
    finally:
        _restore_seasons()
    return world.history, extinct


def _mean_over_seeds(histories, key):
    arr = np.full((len(histories), SEASON_GENERATIONS), np.nan)
    for i, h in enumerate(histories):
        vals = h[key]
        arr[i, :len(vals)] = vals
    with np.errstate(all="ignore"):
        return np.nanmean(arr, axis=0)


def season_main():
    rows = []
    results = {}
    original_temp = config.TEMPERATURE
    for name, temp in SEASON_CONDITIONS:
        print(f"\n=== {name} ({SEASON_GENERATIONS}世代 x {SEASON_SEEDS}シード) ===")
        histories, survived = [], 0
        for s in range(SEASON_SEEDS):
            seed = 5000 + s
            history, extinct = run_season_once(temp, seed)
            histories.append(history)
            survived += (not extinct)
            print(f"  seed={seed}: {'絶滅' if extinct else '共存'}"
                  f" (最終 herb={history['herbivore_count'][-1]} carn={history['carnivore_count'][-1]}"
                  f" / {len(history['generation'])}世代)")
            for i, gen in enumerate(history["generation"]):
                rows.append({
                    "condition": name, "seed": seed, "generation": gen,
                    "temperature": round(history["temperature"][i], 3),
                    "herbivore_count": history["herbivore_count"][i],
                    "carnivore_count": history["carnivore_count"][i],
                    "herb_cold_resistance": _clean(history["herb_cold_resistance"][i]),
                    "carn_cold_resistance": _clean(history["carn_cold_resistance"][i]),
                    "extinct": extinct,
                })
        results[name] = histories
        print(f"-> {name}: 共存率 {survived}/{SEASON_SEEDS} ({survived / SEASON_SEEDS * 100:.0f}%)")
    config.TEMPERATURE = original_temp

    with open(SEASON_CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSVを保存しました: {SEASON_CSV_PATH}")

    gens = np.arange(1, SEASON_GENERATIONS + 1)
    fig, axes = plt.subplots(4, 1, figsize=(11, 16), sharex=True)
    fig.suptitle(f"季節変化 vs 固定気温 (平均, {SEASON_SEEDS}シード)", fontsize=14)
    panels = [
        ("temperature", "気温 (°C)", axes[0]),
        ("herbivore_count", "草食動物の個体数", axes[1]),
        ("carnivore_count", "肉食動物の個体数", axes[2]),
    ]
    for name, histories in results.items():
        color = SEASON_COLORS[name]
        for key, ylabel, ax in panels:
            ax.plot(gens, _mean_over_seeds(histories, key), color=color, label=name, linewidth=1.8)
            ax.set_ylabel(ylabel)
        axes[3].plot(gens, _mean_over_seeds(histories, "herb_cold_resistance"), color=color,
                     linestyle="-", label=f"{name} 草食", linewidth=1.8)
        axes[3].plot(gens, _mean_over_seeds(histories, "carn_cold_resistance"), color=color,
                     linestyle="--", label=f"{name} 肉食", linewidth=1.8)
    axes[3].set_ylabel("耐寒性(平均)")
    axes[3].set_ylim(0, 1)
    axes[3].set_xlabel("世代")
    for ax in axes:
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SEASON_GRAPH_PATH, dpi=150, bbox_inches="tight")
    print(f"グラフを保存しました: {SEASON_GRAPH_PATH}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "seasons":
        season_main()
    else:
        main()
