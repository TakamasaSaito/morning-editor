# 001: お気に入り保存先はGitHub Issue方式

日付: 2026-07-25
状態: 採用

## 決定

お気に入り(継続ウォッチしたい記事)の保存先をGitHub Issueとする。
VPSやDBは使わず、Issueのラベル・本文にURLと要約を記録し、続報を同Issueにコメントする方式を採る。

## 理由

- VPS+DB案は別途サーバー管理・認証・コスト(月数百円〜)が発生し、MVPには過剰
- GitHub Issueはすでにタスク管理で使用中で新たなインフラ不要
- Portfolio Dashboardの自動収集対象でもあり、Issueに残すだけで横断ビューに反映される
- スマホからもGitHub appで参照・追記できる

## 影響

- 続報追跡機能はActions/cronではなくClaude Codeとのチャット起点で実装する
- DB/ORM/認証ライブラリは追加しない
