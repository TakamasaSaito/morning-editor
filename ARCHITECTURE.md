# ARCHITECTURE.md — AI Morning Editor

## 構成図

```mermaid
flowchart LR
    subgraph Actions["GitHub Actions"]
        cron_daily["cron 毎朝 5:00 JST\nmorning.yml"]
        cron_weekly["cron 日曜 6:00 JST\nweekly.yml"]
    end

    subgraph Daily["日次パイプライン"]
        main["src/main.py"]
        claude_api["Claude API\nclaude-sonnet-4-6\n(web検索ツール)"]
        link_check["src/link_check.py\n(HTTP並列チェック)"]
        json["brief.json"]
        jinja["Jinja2\ntemplates/"]
        html["index.html"]
        playwright["Playwright\n(Chromium)"]
        png["brief.png"]
    end

    subgraph Weekly["週次パイプライン"]
        weekly["src/weekly.py"]
        claude_weekly["Claude API\n(web検索なし)"]
        weekly_out["docs/weekly/\nindex.html"]
    end

    subgraph LocalAudio["ローカル音声生成(手動)"]
        audio["src/audio.py"]
        voicevox["VOICEVOX Engine\nlocalhost:50021"]
        mp3["docs/YYYY-MM-DD/\nbrief.mp3"]
    end

    subgraph MangaFlow["漫画イラスト取り込み"]
        iphone["iPhone Safari\n紙面ボタン"]
        issue["GitHub Issue\n(manga ラベル)"]
        manga_wf["manga.yml\n(issues: opened/edited)"]
        attach["src/attach_manga.py\nPillow WebP圧縮"]
        webp["docs/YYYY-MM-DD/\nmanga/NN.webp"]
    end

    subgraph Output["出力先"]
        pages["GitHub Pages\ntakamasasaito.github.io\n/morning-editor/"]
        ntfy["ntfy.sh\niPhone通知"]
        gmail["Gmail\nsend_mail.py"]
    end

    cron_daily --> main
    main --> claude_api
    claude_api --> link_check
    link_check -->|"デッドリンク時\n再検索"| claude_api
    link_check --> json
    json --> jinja --> html
    html --> playwright --> png
    html --> pages
    png --> pages
    pages --> ntfy
    pages --> gmail

    cron_weekly --> weekly
    weekly --> claude_weekly
    claude_weekly --> weekly_out
    weekly_out --> pages
    pages --> ntfy

    audio --> voicevox --> mp3
    mp3 --> pages

    iphone --> issue --> manga_wf --> attach --> webp
    webp --> jinja
    manga_wf --> ntfy
```

## 技術スタック

| 層 | 技術 |
|---|---|
| 言語 | Python 3.12 |
| LLM | Anthropic Claude API (`claude-sonnet-4-6`) |
| テンプレート | Jinja2 |
| スクリーンショット | Playwright (Chromium) |
| 音声合成 | VOICEVOX Engine (ローカル) |
| 画像圧縮 | Pillow (WebP, 最大1200px/300KB) |
| CI/CD | GitHub Actions |
| ホスティング | GitHub Pages |
| 通知 | ntfy.sh / Gmail |

## デプロイ先URL

- **本番**: https://takamasasaito.github.io/morning-editor/
- **週次号**: https://takamasasaito.github.io/morning-editor/weekly/

## 外部依存

| 依存先 | 用途 | 認証 |
|---|---|---|
| Anthropic Claude API | ニュース収集・編集・web検索 | `ANTHROPIC_API_KEY` (Secret) |
| GitHub Pages | 静的HTMLホスティング | リポジトリ設定 |
| ntfy.sh | プッシュ通知 (iPhone) | `NTFY_TOPIC` (Secret) |
| Gmail SMTP | メール配信 | `GMAIL_USER` / `GMAIL_APP_PASS` (Secret) |
| VOICEVOX Engine | 音声合成(ローカル手動のみ) | なし (localhost:50021) |

## データの流れ

```
1. Claude API が web検索で当日ニュースを収集・選定・ファクトチェック
2. 全ソースURLをHTTP並列チェック(HEAD→GET)
   - 404/410/DNS失敗 → dead(リンク切れ): Claudeに再検索・差し替え依頼(1回)
   - 差し替え後も解決しない場合: ソースを「ソース確認中」に変更
   - 403/429 → unverifiable(ボット遮断の可能性): ログ記録のみ、リンク切れ扱いしない
3. JSON形式(brief.json)で構造化 → docs/YYYY-MM-DD/ に保存
4. Jinja2テンプレートでHTMLを生成
5. Playwright が #brief-card をスクリーンショット → brief.png
6. GitHub Actions が docs/ をコミット & push → Pages 自動デプロイ
7. ntfy.sh / Gmail で読者へ通知

週次号: 直近7日分の brief.json を読み込み → Claude でまとめ号編集(web検索なし)
音声版: brief.json のテキストを VOICEVOX で合成 → brief.mp3 (手動)

漫画取り込み:
  iPhone の紙面ボタン → GitHub Issue (manga ラベル) へ画像添付
  → manga.yml が起動 → src/attach_manga.py が画像ダウンロード・WebP圧縮
  → docs/YYYY-MM-DD/manga/NN.webp 保存 → 日付ページ・トップページ再描画 → push
  → Issue を自動クローズ + ntfy 通知
  描画時に manga/ ディレクトリを走査してサムネイル有無を判定(brief.json には書かない)
```
