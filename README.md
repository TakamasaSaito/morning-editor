# AI Morning Editor

「朝起きたら、世界はもう編集されている。」

毎朝5時(JST)にGitHub Actionsが起動し、Claudeがweb検索でニュースを収集・選定・ファクトチェックし、Today's Brief(1枚画像+HTML)を生成、iPhoneにプッシュ通知する。**毎日プロンプトを書く必要は一切ない。**

## 仕組み

```
GitHub Actions (cron 5:00 JST)
  → src/main.py
      → Claude API(web検索ツール付き)で収集・編集・2ソース照合
      → brief.json → index.html(藍×金茶の朝刊デザイン)
      → Playwrightで #brief-card をスクリーンショット → brief.png
  → docs/ にcommit & push(GitHub Pagesで公開)
  → ntfy.sh でiPhoneへ通知(タップで当日のBriefが開く)
```

## セットアップ(初回のみ・約10分)

1. **リポジトリ作成**: このフォルダを `morning-editor` としてGitHubにpush
2. **Secrets登録**(Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY`: AnthropicのAPIキー
   - `NTFY_TOPIC`: 推測されにくいランダム文字列(例: `morning-takamasa-x7k2p`)
3. **Variables登録**(同じ画面のVariablesタブ):
   - `PAGE_URL`: `https://<ユーザー名>.github.io/morning-editor/`
4. **GitHub Pages有効化**: Settings → Pages → Source: `Deploy from a branch`、Branch: `main` / `docs`
5. **iPhoneにntfyアプリ**を入れ、`NTFY_TOPIC` と同じ名前のトピックを購読
6. **config.yaml** の `site.page_url` と読者プロファイルを自分用に編集

## テスト実行

Actionsタブ → Morning Brief → Run workflow(手動実行)。
成功すればiPhoneに通知が届き、タップするとBriefが開く。

ローカル(WSL)での確認:
```bash
pip install -r requirements.txt && playwright install chromium
export ANTHROPIC_API_KEY=sk-ant-...
python src/main.py
# docs/index.html をブラウザで開く
```

## 音声版(聴ける朝刊)

VOICEVOXを使ってbrief.jsonを読み上げmp3に変換する。**ローカル手動実行のみ**。GitHub Actionsでは生成しない。

**前提**
- Windows側でVOICEVOX Engineを起動済み(localhost:50021でアクセス可)
- WSL2 portproxyが設定済み(`netsh interface portproxy add ...`)
- ffmpegがインストール済み(`sudo apt install ffmpeg`)、なければwavとして出力

**生成手順**
```bash
# 最新日付の音声を生成
python src/audio.py

# 日付を指定
python src/audio.py 2026-07-23
```

生成物は `docs/YYYY-MM-DD/brief.mp3` に配置され、該当日の紙面に再生リンクが表示される。

**話者の切り替え**(`config.yaml` の `audio:` セクションを編集)
```yaml
audio:
  speaker_id: 3    # 3=ずんだもんノーマル / 1=ずんだもんあまあま / 2=四国めたんノーマル
  speed_scale: 1.1
```

## パーソナライズ

`config.yaml` を編集するだけ。興味分野・職業・深さ・本数を変えると翌朝から編集方針が変わる。編集長の振る舞い自体を変えたいときは `src/prompts/editor.md` を修正する。

## ファクトチェック方針

- 中核事実は独立2ソース以上で照合できたものだけ掲載
- 各記事に確度(高/中)とソースURLを明示
- 憶測と確定事実を文中で区別

## 出力

- `docs/index.html` — 最新のBrief(カード+深掘り解説)
- `docs/brief.png` — Today's Brief 1枚画像
- `docs/YYYY-MM-DD/` — 日付別アーカイブ(json含む)

## コスト目安

Claude Sonnet 1回/日 + web検索12回以内。GitHub Actions・Pages・ntfyは無料枠内。

## MVP検証項目(コンセプト資料より)

- 毎朝、本当に最初に開くか
- 画像(Level0)だけで十分か、深掘り(Level2)はどれくらい見るか
- どんなニュースをもっと知りたくなるか → config.yamlに反映して育てる
