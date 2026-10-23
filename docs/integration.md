# ゲーム機能の統合記録

## 比較したブランチ

| ブランチ | 調査時コミット | 実装内容 |
| --- | --- | --- |
| main | c97cc9d | 最新のNN一括計算・生涯学習、海辺の移動処理、季節エフェクト、速度3段階ボタン。タイトル・初期の解説ファイルは存在するがmainからの接続なし |
| feature/status-explainer | 7b6eb1b | 草食・肉食の全体傾向、短い個体紹介、葉っぱナビ、詳細解説。旧操作Eを使用し、最新mainの学習・描画更新は未取込 |
| feature/ecosystem-title-screen | 2c2ec18 | タイトル・神様モードへの接続・準備中ミッション・復帰・終了。mainに残るtitle_screen.pyと同じ実装 |
| screenshots/pygame-validation | 1d86e2e | 既存の起動直後・シミュレーション画面画像。追加のゲーム機能なし |

ブランチ名ではなくファイル・差分・履歴を確認しました。調査したリモートの関係ブランチは上記4つです。Ollama/Qwenを呼ぶコードは今回の統合対象にはなく、追加していません。

## 発見した連携不具合と修復

1. mainはWorldを作ってシミュレーションを直接起動しており、タイトルの呼び出しが消えていました。タイトルの戻り値がgodのときだけWorldを作る接続に戻しました。画面なしモードは従来どおり直接実行します。
2. mainに解説ファイルが残っていても、パネルの初期化・イベント委譲・描画がなく、表示されませんでした。feature/status-explainerの完成済みファイルを再利用して接続を復元しました。
3. 旧ナビのEキーが最新mainの季節エフェクト操作と衝突します。ナビをNへ移し、E・WASD・V・F・世代操作・速度ボタンは既存の動作を維持しました。
4. 古い説明はNNをReLU・バイアスあり126パラメータとしていましたが、最新はtanh・バイアスなし112重みです。表示する重み数は実際の個体から読み取り、説明も更新しました。
5. 海へ向かうと即キャンセルという旧説明を、別方向の陸地を探す現在の処理に修正しました。生涯学習した重みの遺伝も説明に含めています。
6. requirementsとWindows起動手順がありませんでした。Python 3.12用の依存ファイルとPowerShell手順を追加しました。

## 変更範囲

最新main c97cc9dから `integration/game-features` を作成しました。古いブランチのmain.pyを丸ごと取り込んでいません。

- `main.py`：タイトルとナビの接続、個体詳細の案内文のみ。
- `navigator_explainer.py` / `navigator_panel.py` / `data/navigator_text.json`：完成済みのナビを再利用。表示切替はN。
- `status_explainer.py` / `status_panel.py` / `data/status_explanations.json`：更新済みの詳細解説を再利用。説明文とキーを現在の仕様に合わせる。
- `requirements.txt` / `README.md` / `.gitignore`：ZIP配布・導入・操作手順。
- `tests/`：最新の生体データと操作、実際のmain.pyの入口を検証。
- `docs/` / `screenshots/`：仕様・検証と実画面。

`config.py`、`organism.py`、`world.py`、`pixel_art.py`、`season_effects.py`、`title_screen.py` は最新mainからバイト単位で変更していません。

## 検証範囲

- 24テスト成功。実際のmain.pyからタイトル→ミッション仮画面→戻る→神様モードを操作。
- 最新のNNと生涯学習を使う1世代200ステップを進め、世代戻しを確認。
- 草食・肉食の値、平均・分布、短い紹介、詳細解説の表示を確認。
- NとTab、選択・追跡、ズーム、速度ボタン、Vの食物表示、Eの季節エフェクト、終了を確認。
- 両行動方式で解説の有無による同じシードの計算結果一致を確認。脳の重みだけでなく学習用状態配列も比較。
- requirementsからクリーンなPython 3.12環境へ導入し、pip check成功。
- 配布するGitスナップショットをZIPとして展開し、別の（空白・日本語を含む）パスと作業ディレクトリから同じテストを実行。
- 主要依存のPython 3.12 / Windows amd64用wheelを取得。japanize-matplotlibは純Pythonのソース配布を利用。

実行環境はLinux/SDL offscreenです。Windows実機の手動確認、長期間の生態系安定性、全条件の科学実験はこの統合の検証範囲外です。

## 未完成機能とマージ

ミッションは準備中の仮画面です。Ollama・Qwen3 4Bの生成AI解説は開発途中であり、今回完成した扱いにはしません。外部AI・ローカルAIのサーバーやAPIキーを要求するコードを追加していません。

このブランチからmain向けPRを作り、Windows起動を含むチームレビュー後にマージしてください。mainへ直接push・強制push・レビュー前のマージは行いません。マージ前は統合ブランチのZIP、マージ後はmainのZIPが対象です。
