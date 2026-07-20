"""AI Morning Editor — 毎朝の自動編集パイプライン

流れ: config読込 → Claude API(web検索)で収集・選定・ファクトチェック
     → JSON解析 → HTML生成 → Briefカードを画像化 → docs/ に出力
GitHub Actionsから毎朝実行される想定。ローカルでも `python src/main.py` で動く。
"""

import json
import os
import re
import shutil
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
MAX_TOKENS = 8000


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_prompt(cfg: dict, now: datetime) -> str:
    prompt = (ROOT / "src" / "prompts" / "editor.md").read_text(encoding="utf-8")
    reader, brief = cfg["reader"], cfg["brief"]
    repl = {
        "{{today}}": now.strftime("%Y年%m月%d日"),
        "{{weekday}}": WEEKDAYS[now.weekday()] + "曜日",
        "{{minutes}}": str(reader["minutes"]),
        "{{interests}}": "、".join(reader["interests"]),
        "{{profession}}": reader["profession"],
        "{{depth}}": reader["depth"],
        "{{story_count}}": str(brief["story_count"]),
        "{{language}}": brief["language"],
    }
    for k, v in repl.items():
        prompt = prompt.replace(k, v)
    return prompt


def call_editor(prompt: str) -> dict:
    """Claudeをweb検索付きで呼び、編集済みJSONを受け取る。"""
    client = Anthropic()  # ANTHROPIC_API_KEY は環境変数から
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 12,
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return parse_json(text)


def parse_json(text: str) -> dict:
    """コードフェンスや前置きが混ざっても最初のJSONオブジェクトを取り出す。"""
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSONが見つかりません:\n{text[:500]}")
    return json.loads(text[start : end + 1])


def validate(d: dict) -> None:
    assert "top_story" in d and "stories" in d, "スキーマ不一致"
    for s in [d["top_story"], *d["stories"]]:
        for key in ("headline", "summary", "why_it_matters", "deep", "sources"):
            assert key in s, f"欠落フィールド: {key} in {s.get('headline', '?')}"


def render_html(cfg: dict, d: dict, now: datetime, out_dir: Path,
                archive: list[dict] | None = None, in_root: bool = False) -> Path:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    html = env.get_template("brief.html.j2").render(
        site_title=cfg["site"]["title"],
        today=now.strftime("%Y.%m.%d"),
        weekday=WEEKDAYS[now.weekday()],
        d=d,
        archive=archive or [],
        in_root=in_root,   # トップページかどうか(アーカイブのリンク先の階層調整に使う)
    )
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def collect_archive(docs_dir: Path, limit: int = 14) -> list[dict]:
    """docs配下の日付フォルダを新しい順に走査し、アーカイブ一覧を作る。"""
    items = []
    for d in sorted(docs_dir.glob("20*-*-*"), reverse=True):
        j = d / "brief.json"
        if not (d.is_dir() and j.exists()):
            continue
        try:
            data = json.loads(j.read_text(encoding="utf-8"))
            headline = data.get("top_story", {}).get("headline", "")
        except Exception:
            headline = ""
        y, m, day = d.name.split("-")
        items.append({
            "date": d.name,
            "label": f"{int(m)}月{int(day)}日",
            "weekday": WEEKDAYS[datetime(int(y), int(m), int(day)).weekday()],
            "headline": headline,
        })
    return items[:limit]


def screenshot_card(html_path: Path, out_dir: Path) -> None:
    """Briefカード部分だけを画像化(Today's Brief 1枚画像)。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 620, "height": 1400},
                                device_scale_factor=2)
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")  # Webフォント読込待ち
        page.locator("#brief-card").screenshot(path=str(out_dir / "brief.png"))
        browser.close()


def generate_apple_touch_icon(docs_dir: Path) -> None:
    """icon.svg を 180×180 PNG に変換して apple-touch-icon.png として保存。"""
    from playwright.sync_api import sync_playwright

    svg = (docs_dir / "icon.svg").read_text(encoding="utf-8")
    html = (
        "<!DOCTYPE html><html><head>"
        "<style>*{margin:0;padding:0}svg{display:block;width:180px;height:180px}</style>"
        "</head><body>" + svg + "</body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 180, "height": 180})
        page.set_content(html)
        page.screenshot(path=str(docs_dir / "apple-touch-icon.png"))
        browser.close()


def main() -> None:
    now = datetime.now(JST)
    cfg = load_config()

    print(f"[1/5] 編集長プロンプト構築 ({now:%Y-%m-%d %H:%M} JST)")
    prompt = build_prompt(cfg, now)

    print("[2/5] Claude呼び出し(ニュース収集・選定・ファクトチェック)")
    data = call_editor(prompt)
    validate(data)
    print(f"      トップ: {data['top_story']['headline']} / 他{len(data['stories'])}本")

    date_dir = ROOT / "docs" / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    (date_dir / "brief.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[3/7] HTML生成(日付ページ)")
    html_path = render_html(cfg, data, now, date_dir)

    print("[4/7] Briefカード画像化")
    screenshot_card(html_path, date_dir)

    docs_dir = ROOT / "docs"
    print("[5/7] apple-touch-icon.png 生成")
    generate_apple_touch_icon(docs_dir)

    print("[6/7] 画像とJSONを docs/ 直下へ配置")
    for name in ("brief.png", "brief.json"):
        shutil.copy(date_dir / name, docs_dir / name)

    print("[7/7] アーカイブ一覧を付けてトップページ生成")
    archive = collect_archive(docs_dir)
    render_html(cfg, data, now, docs_dir, archive=archive, in_root=True)

    print(f"完了: {date_dir} / アーカイブ {len(archive)}件")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
