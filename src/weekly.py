"""Weekly AI Editor — 週次まとめ号の生成

直近7日分の brief.json を読み込み、Claude APIで週次編集する。
web検索は使わない(素材は蓄積済みJSONのみ)。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from anthropic import Anthropic
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

MODEL = os.environ.get("EDITOR_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 16000


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_week_briefs(docs_dir: Path, today: datetime, days: int = 7) -> list[dict]:
    """直近 days 日分の brief.json を古い順で返す(今日分は除外)。"""
    today_str = today.strftime("%Y-%m-%d")
    briefs = []
    for d in sorted(docs_dir.glob("20*-*-*"), reverse=True):
        if d.name == today_str:
            continue
        j = d / "brief.json"
        if not (d.is_dir() and j.exists()):
            continue
        try:
            data = json.loads(j.read_text(encoding="utf-8"))
            data["_date"] = d.name
            briefs.append(data)
        except Exception:
            pass
        if len(briefs) >= days:
            break
    return list(reversed(briefs))


def build_material(briefs: list[dict]) -> str:
    lines = []
    for b in briefs:
        lines.append(f"\n## {b['_date']}")
        one_line = b.get("one_line_world", "")
        if one_line:
            lines.append(f"一文サマリー: {one_line}")
        top = b.get("top_story", {})
        if top:
            lines.append(
                f"トップ記事: 【{top.get('category', '')}】{top.get('headline', '')}"
            )
            lines.append(f"  概要: {top.get('summary', '')}")
            lines.append(f"  重要性: {top.get('why_it_matters', '')}")
        for s in b.get("stories", []):
            lines.append(
                f"記事: 【{s.get('category', '')}】"
                f"{s.get('headline', '')} — {s.get('summary', '')}"
            )
    return "\n".join(lines)


def build_weekly_prompt(cfg: dict, briefs: list[dict]) -> str:
    prompt = (ROOT / "src" / "prompts" / "weekly_editor.md").read_text(encoding="utf-8")
    reader = cfg["reader"]

    if briefs:
        start_dt = datetime.strptime(briefs[0]["_date"], "%Y-%m-%d")
        end_dt = datetime.strptime(briefs[-1]["_date"], "%Y-%m-%d")
        week_label = (
            f"{start_dt.year}年{start_dt.month}月{start_dt.day}日"
            f"〜{end_dt.month}月{end_dt.day}日"
        )
    else:
        week_label = "不明"

    repl = {
        "{{week_label}}": week_label,
        "{{interests}}": "、".join(reader["interests"]),
        "{{profession}}": reader["profession"],
        "{{depth}}": reader["depth"],
        "{{language}}": cfg["brief"]["language"],
        "{{material}}": build_material(briefs),
    }
    for k, v in repl.items():
        prompt = prompt.replace(k, v)
    return prompt


def call_weekly_editor(prompt: str) -> dict:
    """Claudeをweb検索なしで呼び、週次編集済みJSONを受け取る。"""
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "max_tokens":
        print("WARNING: レスポンスが max_tokens に達し出力が打ち切られました", file=sys.stderr)
    text = "".join(b.text for b in resp.content if b.type == "text")
    return parse_json(text)


def parse_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSONが見つかりません:\n{text[:500]}")
    raw = text[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        return _repair_json(raw, e)


def _repair_json(raw: str, original_error: json.JSONDecodeError) -> dict:
    print("WARNING: JSONパースエラー。Claudeに修復を依頼します...", file=sys.stderr)
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": (
                "以下のJSONは構文エラーがあります。エラーを修正して有効なJSONのみを返してください。"
                "前置きや説明は不要です。JSONのみを出力してください。\n\n" + raw
            ),
        }],
    )
    fixed = "".join(b.text for b in resp.content if b.type == "text")
    fixed = re.sub(r"```(?:json)?", "", fixed).strip()
    s, e2 = fixed.find("{"), fixed.rfind("}")
    if s != -1 and e2 != -1:
        try:
            return json.loads(fixed[s : e2 + 1])
        except json.JSONDecodeError:
            pass
    tail = raw[max(0, len(raw) - 200):]
    raise ValueError(
        f"JSONパースエラー(修復失敗): {original_error}\nレスポンス末尾200文字:\n{tail}"
    ) from original_error


def validate_weekly(d: dict) -> None:
    assert "top_story" in d and "stories" in d, "スキーマ不一致: top_story/stories欠落"
    assert "next_week_watch" in d, "スキーマ不一致: next_week_watch欠落"
    for s in [d["top_story"], *d["stories"]]:
        for key in ("headline", "summary", "why_it_matters", "deep"):
            assert key in s, f"欠落フィールド: {key} in {s.get('headline', '?')}"


def render_weekly_html(cfg: dict, d: dict, briefs: list[dict], out_dir: Path) -> Path:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    html = env.get_template("weekly.html.j2").render(
        site_title=cfg["site"]["title"],
        d=d,
    )
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def collect_weekly_archive(docs_dir: Path, limit: int = 8) -> list[dict]:
    """docs/weekly 配下の日付フォルダを新しい順に走査し、週刊アーカイブ一覧を作る。"""
    weekly_dir = docs_dir / "weekly"
    if not weekly_dir.exists():
        return []
    items = []
    for d in sorted(weekly_dir.glob("20*-*-*"), reverse=True):
        j = d / "weekly.json"
        if not (d.is_dir() and j.exists()):
            continue
        try:
            data = json.loads(j.read_text(encoding="utf-8"))
            headline = data.get("top_story", {}).get("headline", "")
            week_label = data.get("week_label", d.name)
        except Exception:
            headline = ""
            week_label = d.name
        items.append({"date": d.name, "week_label": week_label, "headline": headline})
        if len(items) >= limit:
            break
    return items


def render_weekly_index(cfg: dict, docs_dir: Path, archive: list[dict]) -> None:
    """docs/weekly/index.html を更新(週刊アーカイブ一覧ページ)。"""
    site_title = cfg["site"]["title"]
    rows = "".join(
        f'<a href="{a["date"]}/" class="wi-row">'
        f'<span class="wi-week">{a["week_label"]}</span>'
        f'<span class="wi-head">{a["headline"]}</span>'
        f"</a>\n"
        for a in archive
    )
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title} — 週刊アーカイブ</title>
<link rel="icon" type="image/svg+xml" href="../icon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;700;800&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{{--ink:#1B2A4A;--paper:#FBFAF7;--kincha:#B07C1F;--rule:#D8D4CA;--muted:#6B7280;
    --serif:'Shippori Mincho',serif;--sans:'Noto Sans JP',sans-serif;}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#EDEBE4;font-family:var(--sans);color:var(--ink);
    display:flex;flex-direction:column;align-items:center;padding:16px 12px 64px}}
  .hd{{width:100%;max-width:560px;border-top:6px solid var(--ink);background:var(--paper);
    padding:20px 24px;margin-bottom:4px;box-shadow:0 2px 16px rgba(27,42,74,.12)}}
  .back{{font-size:.8rem;color:var(--kincha);text-decoration:none;display:block;margin-bottom:12px}}
  .hd h1{{font-family:var(--serif);font-size:1.1rem;font-weight:800;letter-spacing:.06em}}
  .wi-row{{display:flex;gap:12px;align-items:baseline;text-decoration:none;
    color:var(--ink);padding:13px 24px;border-bottom:1px solid var(--rule);
    background:var(--paper);width:100%;max-width:560px}}
  .wi-row:hover{{background:#fff}}
  .wi-week{{font-size:.78rem;color:var(--kincha);font-weight:700;flex:none;min-width:9em}}
  .wi-head{{font-family:var(--serif);font-size:.9rem;line-height:1.5;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
</style>
</head>
<body>
<div class="hd">
  <a class="back" href="../">← 最新の朝刊へ</a>
  <h1>週刊アーカイブ</h1>
</div>
{rows}
</body>
</html>"""
    (docs_dir / "weekly" / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    now = datetime.now(JST)
    cfg = load_config()
    docs_dir = ROOT / "docs"

    print(f"[1/5] 直近7日分のbrief.jsonを収集 ({now:%Y-%m-%d %H:%M} JST)")
    briefs = collect_week_briefs(docs_dir, now)
    print(f"      収集: {len(briefs)}日分 ({', '.join(b['_date'] for b in briefs)})")
    if not briefs:
        print("ERROR: 素材が0件。中断します。", file=sys.stderr)
        sys.exit(1)

    print("[2/5] 週次プロンプト構築 → Claude呼び出し(web検索なし・蓄積素材のみ)")
    prompt = build_weekly_prompt(cfg, briefs)
    data = call_weekly_editor(prompt)
    validate_weekly(data)
    print(f"      トップ: {data['top_story']['headline']} / 他{len(data['stories'])}本")
    print(f"      来週の注目点: {len(data['next_week_watch'])}件")

    out_date = briefs[-1]["_date"]
    weekly_dir = docs_dir / "weekly" / out_date
    weekly_dir.mkdir(parents=True, exist_ok=True)

    print("[3/5] weekly.json 保存")
    (weekly_dir / "weekly.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[4/5] 週次HTML生成")
    html_path = render_weekly_html(cfg, data, briefs, weekly_dir)
    print(f"      出力: {html_path}")

    print("[5/5] 週刊アーカイブ一覧を更新")
    archive = collect_weekly_archive(docs_dir)
    render_weekly_index(cfg, docs_dir, archive)

    print(f"完了: {weekly_dir} / 週刊アーカイブ {len(archive)}号")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
