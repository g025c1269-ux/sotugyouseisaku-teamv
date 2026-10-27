# ゲーム画面のスクリーンショット

## Ollama AIナビのUI確認（通信モック）

以下は `feature/ollama-navigator` の実際のmain.pyをSDL offscreenで動かし、Ollamaの代わりに固定文を返す通信モックで撮影した1040×640 PNGです。**本物のqwen3:4bが生成した文章ではありません。** マップ・個体・操作は通常のゲーム処理を使用しています。

- [生成待ち中も操作・シミュレーションが続く画面](27_ai_game_pending_mock.png)
- [草食全体のAI画面](28_ai_game_herbivore_mock.png)
- [肉食全体のAI画面](29_ai_game_carnivore_mock.png)
- [選択個体のAI画面](30_ai_game_individual_mock.png)

[Windows実機でqwen3:4bを確認する手順](../docs/ollama_navigator.md)を使って、実際の生成時間と文章を確認してください。

以下はこれまでの開発時点の記録です。

Pygameの実際の描画内容を、画面接続のないクラウド環境でSDLの `offscreen` ドライバーを使って保存しました。ゲームのソースコードや計算処理は変更していません。

## 起動直後・操作パネル

現在の実装には独立した設定画面はありません。速度調整スライダー、モード表示、操作説明を含む起動直後の画面です。

![起動直後・操作パネル](01_initial.png)

[PNGを開く](01_initial.png) — 1000×600、115,816バイト

## シミュレーション進行後

第1世代の200ステップ終了後、第2世代になった画面です。草食77個体、肉食18個体。

![シミュレーション進行後](02_simulation.png)

[PNGを開く](02_simulation.png) — 1000×600、105,815バイト

## 撮影条件

- Python 3.12 / Pygame 2.6.1
- NumPy乱数シード: 1000
- 初期個体数: 草食320、肉食25
- 気温: 15°C、1世代200ステップ
- 画像サイズ: 両方1000×600ピクセル

GitHubの画像ページで表示できない場合は、Raw表示またはダウンロードを利用してください。

## タイトル画面（新規）

`python main.py` で表示されます（`config.VISUALIZE=True` の場合）。

![タイトル画面](03_title.png)

[タイトル画面PNG](03_title.png)

## ミッションモード仮画面（新規）

![ミッションモード仮画面](04_mission.png)

[ミッションモードPNG](04_mission.png)

## 神様モードの接続確認

![神様モードから起動した既存シミュレーション](05_god_mode.png)

タイトルからミッションへの遷移と復帰、神様モードへの遷移、既存シミュレーションの第1世代200ステップ完了、終了ボタン、ウィンドウの閉じる操作、ホバー、キーボード操作をSDL offscreenで検証しました。実デスクトップ上での手動操作は未検証です。

追加画面は `title_screen.py` に分離されています。日本語フォントはシステムの日本語フォントを優先し、見つからない場合は既存依存の `japanize_matplotlib` 付属フォントを使用します。新しいGUIフレームワークは使用していません。

## main.pyへ統合したドット絵版

![統合後のドット絵シミュレーション](06_pixel_simulation.png)

`main(pixel).py` の描画・操作を `main.py` へ移行し、タイトルから神様モードへ接続しました。画像は季節変化の確認中、2倍ズーム・1世代ごとモードで撮影した1040×640のPNGです。ズーム、カメラ移動、ミニマップ、世代送り・巻き戻しに伴う気温更新、画面なし実行を確認しています。

## 最新mainの画面（358f801から撮影）

ソース・設定を変更せず `main.py` のタイトルから神様モードへ進み、標準設定（15°C）で撮影しました。乱数シード1000、SDL offscreenを使用しています。

- [タイトル画面](07_current_title.png)
- [起動直後の俯瞰画面](08_current_overview.png)
- [第2世代・2倍ズーム画面](09_current_zoom.png)

## ステータス組み合わせ解説

生物を選択すると右側に数値・3段階評価・総合解説・長所・注意点を表示します。パネル上でホイールスクロール、「閉じる」またはEで従来表示に戻ります。

- [草食動物・現在値と評価](10_status_herbivore.png)
- [組み合わせ総合解説](11_status_summary.png)
- [長所と短所・注意点](12_status_strengths.png)
- [肉食動物・現在値と評価](13_status_carnivore.png)

[設計・閾値・検証手順](../docs/status_explainer.md) / [全4,374件の解説CSV（ZIP）](../docs/status_combinations.zip)


## 最新mainとの統合確認

- [統合版タイトル](18_integrated_title.png)
- [準備中のミッション仮画面](19_integrated_mission.png)
- [季節エフェクトと観察ナビ](20_integrated_navigator.png)
- [最新の速度ボタン・表示切替](21_integrated_controls.png)
- [選択個体のナビ](22_integrated_selected.png)

最新mainとの統合版では、Nがナビ切替、Eは季節エフェクトの切替です。過去の画像にある旧キー案内は現行の操作ではありません。[現行の起動・操作手順](../README.md)を参照してください。
