# AI部分だけの配布ファイル

[AIファイルのみのZIPをダウンロード](https://github.com/g025c1269-ux/sotugyouseisaku-teamv/raw/refs/heads/feature/ollama-navigator/downloads/ollama-navigator-ai-only.zip)

抽出元：`feature/ollama-navigator` の `7ae7417`。年間総括は160〜190文字・5〜6文です。

ZIPにはAI用Python5本、設定JSON、組み込み説明書、元ファイルのハッシュ一覧、最新確認main `251470a` 向けの接続参考パッチ2本が入っています。
ゲーム本体・計算・描画・タイトル・設定・セーブのソースやモデル本体は含みません。既存プロジェクトへの組み込み用であり、ZIP単体では起動しません。

まずZIP内の `AI_ONLY_README.md` を読んでください。main.py等を古い版で上書きせず、必要な接続だけを反映できます。パッチの適用、構文、モジュール読込、PygameのAI画面表示、計算/描画ファイルが変わらないことをクラウド上の別コピーで確認しました。実モデルでの生成品質とWindows実機での動作は未確認です。

セーブへ年間履歴を含めて復元する対応は、この部品には含まれていません。詳細はZIPの説明書に記載しています。
