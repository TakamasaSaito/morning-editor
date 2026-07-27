"""既存の brief.json から全ページを再描画するスクリプト。Claude APIは呼ばない。

使い方:
  python src/rebuild_html.py          # 全日付ページ + トップページ
  python src/rebuild_html.py --no-screenshot  # スクリーンショット(Playwright)をスキップ
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render_html(cfg, d, now, out_dir, archive=None, in_root=False, weekly_archive=None):
    if in_root:
        manga_dir = out_dir / now.strftime("%Y-%m-%d") / "manga"
        manga_prefix = now.strftime("%Y-%m-%d") + "/manga/"
    else:
        manga_dir = out_dir / "manga"
        manga_prefix = "manga/"

    num_articles = 1 + len(d.get("stories", []))
    manga_images = [None] * num_articles
    if manga_dir.exists():
        for img in sorted(manga_dir.glob("*.webp")):
            try:
                idx = int(img.stem)
                if 0 <= idx < num_articles:
                    manga_images[idx] = manga_prefix + img.name
            except ValueError:
                pass

    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=True)
    html = env.get_template("brief.html.j2").render(
        site_title=cfg["site"]["title"],
        today=now.strftime("%Y.%m.%d"),
        today_iso=now.strftime("%Y-%m-%d"),
        weekday=WEEKDAYS[now.weekday()],
        d=d,
        archive=archive or [],
        in_root=in_root,
        weekly_archive=weekly_archive or [],
        manga_images=manga_images,
    )
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def screenshot_card(html_path, out_dir):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 620, "height": 1400}, device_scale_factor=2)
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.locator("#brief-card").screenshot(path=str(out_dir / "brief.png"))
        browser.close()


def collect_archive(docs_dir, limit=14):
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


def collect_weekly_archive(docs_dir, limit=4):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-screenshot", action="store_true", help="Playwrightスクリーンショットをスキップ")
    args = parser.parse_args()

    cfg = load_config()
    docs_dir = ROOT / "docs"

    date_dirs = sorted(docs_dir.glob("20*-*-*"))
    print(f"対象日付ページ: {len(date_dirs)}件")

    latest_dir = None
    latest_now = None

    for d in date_dirs:
        j = d / "brief.json"
        if not (d.is_dir() and j.exists()):
            continue
        y, m, day = d.name.split("-")
        now = datetime(int(y), int(m), int(day), 7, 0, 0, tzinfo=JST)
        data = json.loads(j.read_text(encoding="utf-8"))

        html_path = render_html(cfg, data, now, d)
        print(f"  {d.name}: HTML生成 → {html_path}")

        if not args.no_screenshot:
            screenshot_card(html_path, d)
            print(f"  {d.name}: スクリーンショット生成")

        latest_dir = d
        latest_now = now

    if latest_dir is None:
        print("ERROR: 日付ディレクトリが見つかりません", file=sys.stderr)
        sys.exit(1)

    print(f"\n最新日付: {latest_dir.name} → トップページ生成")
    latest_data = json.loads((latest_dir / "brief.json").read_text(encoding="utf-8"))
    archive = collect_archive(docs_dir)
    weekly_archive = collect_weekly_archive(docs_dir)
    render_html(cfg, latest_data, latest_now, docs_dir,
                archive=archive, in_root=True, weekly_archive=weekly_archive)
    print(f"  docs/index.html 生成 (アーカイブ {len(archive)}件)")

    for name in ("brief.json",):
        shutil.copy(latest_dir / name, docs_dir / name)
        print(f"  docs/{name} を {latest_dir.name} からコピー")

    if not args.no_screenshot:
        shutil.copy(latest_dir / "brief.png", docs_dir / "brief.png")
        print("  docs/brief.png をコピー")

    print("\n完了")


if __name__ == "__main__":
    main()
