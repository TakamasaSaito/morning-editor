# Status

## 実装済み機能

| 機能 | 状態 | Issue |
|------|------|-------|
| 毎朝の自動ブリーフ生成 | ✅ 稼働中 | — |
| 週次まとめ号生成 | ✅ 実装済み | #1 |

## 週次まとめ号 (#1)

- `src/weekly.py` — 直近7日分の brief.json を素材に Claude API で週次編集(web検索なし)
- `src/prompts/weekly_editor.md` — 週次編集プロンプト
- `templates/weekly.html.j2` — 週刊号テンプレート(藍×金茶・「週刊」バッジ・今週の展開・来週の注目点)
- `.github/workflows/weekly.yml` — 日曜 6:00 JST 自動実行 / 手動実行対応
- 出力先: `docs/weekly/YYYY-MM-DD/`
- ntfy 通知: 「週刊号が届きました」(毎朝版と区別)
- トップページに週刊アーカイブ一覧を追加(`docs/weekly/index.html`)

## 実行方法

```bash
# 毎朝ブリーフ
python src/main.py

# 週次まとめ号
python src/weekly.py

# GitHub Actions から手動実行
gh workflow run weekly.yml
```
