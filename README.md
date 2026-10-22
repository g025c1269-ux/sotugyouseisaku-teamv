# sotugyouseisaku-teamv

## ステータス解説版のダウンロード

対象ブランチは **`feature/status-explainer`** です。

**[このブランチのゲーム一式をZIPでダウンロード](https://github.com/g025c1269-ux/sotugyouseisaku-teamv/archive/refs/heads/feature/status-explainer.zip)**

GitHubの「Code → Download ZIP」を使う場合は、先にブランチ選択を `feature/status-explainer` にしてください。`main` のZIPとは別の内容です。古いフォルダへの上書きではなく、新しい場所にZIPを解凍してください。

`docs/status_combinations.zip` は解説一覧CSVだけのファイルです。ゲーム本体ではありません。

## 起動と解説の表示

1. 解凍先に `main.py`、`status_explainer.py`、`status_panel.py`、`data/status_explanations.json` があることを確認します。
2. そのフォルダで `python main.py` を実行します。このブランチはシミュレーション画面から直接起動します。
3. 最初に **Space** で一時停止すると、移動している生物を選びやすくなります。
4. 盤面の青い草食動物または赤い肉食動物を、**ドラッグせず左クリックして離します**。見づらければ **2** または **3** キーで拡大できます。
5. 右側が「生物のステータス解説」に変わります。数値・LOW/MID/HIGH・総合解説・長所・短所を確認できます。
6. 右側パネル上でホイールを動かすと、下の文章まで読めます。
7. 「閉じる」または **E** で従来の個体詳細へ戻ります。同じ生物を選択した状態で **E** を押すと解説を再表示します。Eだけでは生物を選択できません。

解説を開いても自動では一時停止しません。選択個体が死亡・消失した場合はパネルを閉じるため、別の生存個体を選んでください。

依存パッケージが未導入の場合は、使用するPython環境で次を実行してください。

```bash
python -m pip install numpy matplotlib japanize-matplotlib pygame "setuptools<81"
python main.py
```

## 反映状況の調査結果

- 解説実装のコミット：`2dd252f`。このブランチへのpushを確認済みです。
- `main.py` の `run_with_visualization()` で `StatusPanel` を読み込み・初期化し、`handle_event()` と `draw()` を呼んでいます。
- 後続の `main` の更新 `f8e2911` で、この接続部分が削除されています。このため、`main` をダウンロードしても同じ解説画面にはなりません。
- Ahead/Behindはブランチ間のコミット差です。0であっても、機能が存在しないという意味ではありません。
- 今回、GitHubから対象ブランチのZIPを実際に取得・解凍し、11テストと `main.py` の起動→生物選択→解説表示→Eによる表示切替→正常終了をSDL offscreenで確認しました。実デスクトップの手動操作は未検証です。

今回の調査では対象ブランチの接続は正常であり、ゲームコードの追加修正は不要でした。案内のためこのREADMEだけを更新しています。`main` へのpushや、計算・描画コードの変更はしていません。

[仕様・閾値・検証手順](docs/status_explainer.md) / [解説画面の例](screenshots/11_status_summary.png)
