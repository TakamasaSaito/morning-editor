# 002: 音声版はローカル手動生成(GitHub Actions不採用)

日付: 2026-07-25
状態: 採用

## 決定

VOICEVOX音声生成はローカルWSLからの手動実行専用とし、GitHub Actionsには組み込まない。

## 理由

- VOICEVOX EngineはWindows側のGUIアプリで、Actions(ubuntu-latest)では起動できない
- 代替(VPS常駐化・Docker化)はMVP段階では管理コストが割に合わない
- 朝刊音声は「聴きたいときだけ生成」の運用で十分であることをMVP検証で確認
- `python src/audio.py` 1コマンドで最新日付の音声が生成できる手軽さを優先

## 影響

- docs/YYYY-MM-DD/brief.mp3 はローカル生成物のみ存在し、Actionsコミットには含まれない
- 音声ファイルが存在する日だけHTMLに再生リンクが表示される仕様が維持される
