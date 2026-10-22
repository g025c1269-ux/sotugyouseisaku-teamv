# =============================================
# config.py — 実験パラメータの設定ファイル
# ここの数値を変えるだけで実験条件を切り替えられる
# =============================================

# --- 世界の設定 ---
# グリッドを60→80に拡大し、初期個体数・食物も面積比(約1.78倍)でスケール。
# 密度を保ったまま絶対個体数を増やすことで、少数個体による偶発的な
# 共倒れ(特に肉食動物が0になるリスク)を減らす狙い
GRID_SIZE          = 160     # グリッドのサイズ (160x160)
INITIAL_HERBIVORES = 960    # 草食動物の初期個体数
INITIAL_CARNIVORES = 150    # 肉食動物の初期個体数
INITIAL_FOOD       = 600    # 食物の初期数
MAX_FOOD           = 5600   # 食物の上限 (爆発的な増加を防ぐ)

# --- 環境変数 (実験で変える値) ---
TEMPERATURE      = 15.0     # 気温 (°C)  ← ここを変えて実験する

# ニューロエボリューション (Trueで行動選択をルールベースからNNに切り替える)
USE_NEUROEVOLUTION = True

# 季節変化 (常時有効: 世代ごとに気温をsin波で更新する)
SEASON_CYCLE = 20           # 何世代で1サイクル(春夏秋冬)
TEMP_SUMMER  = 35.0         # 夏の最高気温
TEMP_WINTER  = 5.0          # 冬の最低気温

# 寿命と若年繁殖制限
MAX_AGE           = 300     # この年齢(ステップ数)を超えると死亡
MIN_REPRODUCE_AGE = 10      # この年齢未満の個体は繁殖できない (NNモード)

FOOD_SPAWN_RATE  = 1.0      # 毎ターン食物が生まれる確率
FOOD_SPAWN_COUNT = 48       # 1ターンに生まれる食物の個数 (グリッド拡大に合わせてスケール)

# 地形: マップを5x5のゾーンに分割し、ゾーンごとに食物出現率や移動コストを変える
# (個体側はゾーンを意識せず、視野内の食物・天敵だけを見て行動する)
GRASSLAND_FOOD_RATE = 0.8   # 草原の食物出現率
DESERT_FOOD_RATE    = 0.1   # 砂漠の食物出現率
MOUNTAIN_FOOD_RATE  = 0.4   # 山の食物出現率
RIVER_FOOD_RATE     = 0.6   # 川(川沿い)の食物出現率

DESERT_TEMP_PENALTY_MULTIPLIER = 1.3   # 砂漠は暑いので気温ペナルティを増幅
CARNIVORE_ENERGY_FROM_FISH     = 5.0   # 肉食動物が川で魚を捕れたときのエネルギー(15だと魚で食いつなぎ増えすぎたため引き下げ)

# 気温ペナルティの係数 (種ごとに別々に調整できるようにする)
# 気温変化 → 草食動物が減る → 肉食動物が連鎖的に餓死する、という
# 不安定さを緩和するため、肉食動物側は係数を低めにしてある
HERBIVORE_TEMP_PENALTY_COEF = 0.5
CARNIVORE_TEMP_PENALTY_COEF = 1.2

# --- 遺伝子の設定 ---
GENE_COLD_RESISTANCE_RANGE  = [0.0, 1.0]
GENE_SPEED_RANGE            = [0.2, 0.8]
GENE_HUNGER_THRESHOLD_RANGE = [0.3, 0.7]
GENE_METABOLISM_RANGE       = [0.0, 1.0]
GENE_RIVER_TOLERANCE_RANGE    = [0.0, 1.0]
GENE_MOUNTAIN_TOLERANCE_RANGE = [0.0, 1.0]

MUTATION_RATE     = 0.05
MUTATION_STRENGTH = 0.1

# --- 草食動物のエネルギー設定 ---
HERBIVORE_INITIAL_ENERGY    = 50.0
HERBIVORE_MAX_ENERGY        = 100.0
HERBIVORE_ENERGY_FROM_FOOD  = 20.0
HERBIVORE_BASE_ENERGY_COST  = 0.4
HERBIVORE_MOVE_ENERGY_COST  = 0.2
HERBIVORE_REPRODUCTION_ENERGY = 80.0  # 繁殖に必要な最低エネルギー(高めに設定)
HERBIVORE_REPRODUCTION_COST   = 40.0

# --- 肉食動物のエネルギー設定 ---
CARNIVORE_INITIAL_ENERGY    = 150.0
CARNIVORE_MAX_ENERGY        = 120.0
CARNIVORE_ENERGY_FROM_PREY  = 30.0   # 高カロリーな肉を食べる想定(20は少なすぎ、40は多すぎたため中間の30)
CARNIVORE_BASE_ENERGY_COST  = 0.55   # 維持コストを下げ、獲物不足時の連鎖絶滅を緩和
CARNIVORE_MOVE_ENERGY_COST  = 0.25
CARNIVORE_REPRODUCTION_ENERGY = 95.0  # 繁殖の閾値(増えすぎて草食を狩り尽くさない程度に調整)
CARNIVORE_REPRODUCTION_COST   = 65.0

# --- シミュレーション設定 ---
MAX_STEPS_PER_GEN = 200     # 1世代あたりの最大ステップ数
MAX_GENERATIONS   = 100

# --- 可視化設定 ---
VISUALIZE        = True
DISPLAY_INTERVAL = 5
