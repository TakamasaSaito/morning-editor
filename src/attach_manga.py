"""漫画イラスト取り込み処理 — GitHub Issueの画像URLを取得・圧縮・保存してページを再描画する。

Usage (CLI):
    python3 src/attach_manga.py <image_path_or_url> <YYYY-MM-DD> <article_index>

GitHub Actions (--from-issue フラグ使用, 環境変数 ISSUE_TITLE / ISSUE_BODY を参照):
    python3 src/attach_manga.py --from-issue
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

LONG_EDGE = 1200
TARGET_BYTES = 300 * 1024  # 300KB


def parse_issue_title(title: str) -> tuple[str, int]:
    """[manga] YYYY-MM-DD #N 記事見出し → (date_str, article_idx)"""
    m = re.match(r'\[manga\]\s+(\d{4}-\d{2}-\d{2})\s+#(\d+)', title)
    if not m:
        raise ValueError(f"タイトルの形式が不正です: {title!r}\n"
                         "期待形式: [manga] YYYY-MM-DD #N 記事見出し")
    return m.group(1), int(m.group(2))


def extract_image_urls(body: str) -> list[str]:
    """Issue本文からGitHub添付画像URLを抽出する。"""
    # Markdown画像記法: ![...](URL)
    urls = re.findall(
        r'!\[[^\]]*\]\((https://(?:github\.com/user-attachments|user-images\.githubusercontent\.com)\S+?)\)',
        body,
    )
    if not urls:
        # 生URL形式も探す
        urls = re.findall(
            r'(https://(?:github\.com/user-attachments|user-images\.githubusercontent\.com)\S+)',
            body,
        )
    return urls


def download_image(url_or_path: str):
    """URLまたはローカルパスから Pillow Image を返す。"""
    from PIL import Image

    if url_or_path.startswith(("http://", "https://")):
        req = urllib.request.Request(
            url_or_path, headers={"User-Agent": "morning-editor-bot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        return Image.open(io.BytesIO(data))
    return Image.open(url_or_path)


def compress_to_webp(img, out_path: Path) -> None:
    """長辺 LONG_EDGE 以下にリサイズし WebP 保存 (TARGET_BYTES 目安)。"""
    from PIL import Image

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > LONG_EDGE:
        if w >= h:
            new_w, new_h = LONG_EDGE, int(h * LONG_EDGE / w)
        else:
            new_w, new_h = int(w * LONG_EDGE / h), LONG_EDGE
        img = img.resize((new_w, new_h), Image.LANCZOS)

    for quality in (85, 75, 65, 55):
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality, method=4)
        size = buf.tell()
        if size <= TARGET_BYTES or quality == 55:
            out_path.write_bytes(buf.getvalue())
            print(f"      保存: {out_path.relative_to(ROOT)} "
                  f"({size // 1024}KB, quality={quality})")
            return


def rerender(date_str: str) -> None:
    """指定日の日付ページとトップページを再描画する。"""
    sys.path.insert(0, str(ROOT / "src"))
    import importlib
    import main as m

    importlib.reload(m)

    cfg = m.load_config()
    y, mo, day = (int(x) for x in date_str.split("-"))
    now = datetime(y, mo, day, tzinfo=JST)

    docs_dir = ROOT / "docs"
    date_dir = docs_dir / date_str

    brief_path = date_dir / "brief.json"
    if not brief_path.exists():
        raise FileNotFoundError(f"brief.json が見つかりません: {brief_path}")

    data = json.loads(brief_path.read_text(encoding="utf-8"))

    print(f"      日付ページ再描画: {date_dir.name}")
    m.render_html(cfg, data, now, date_dir, in_root=False)

    # トップページ: 現在 docs/ 直下にある brief.json を使う
    top_json = docs_dir / "brief.json"
    if top_json.exists():
        print("      トップページ再描画")
        top_data = json.loads(top_json.read_text(encoding="utf-8"))
        # 最新の日付フォルダ名から now を再構築
        date_dirs = sorted(docs_dir.glob("20*-*-*"), reverse=True)
        if date_dirs:
            latest = date_dirs[0].name
            ty, tmo, tday = (int(x) for x in latest.split("-"))
            top_now = datetime(ty, tmo, tday, tzinfo=JST)
        else:
            top_now = now
        archive = m.collect_archive(docs_dir)
        weekly_archive = m.collect_weekly_archive(docs_dir)
        m.render_html(cfg, top_data, top_now, docs_dir,
                      archive=archive, in_root=True, weekly_archive=weekly_archive)


def main() -> None:
    parser = argparse.ArgumentParser(description="漫画イラスト取り込み")
    parser.add_argument(
        "--from-issue",
        action="store_true",
        help="GitHub Actions から呼ぶ場合に指定。ISSUE_TITLE / ISSUE_BODY 環境変数を参照する",
    )
    parser.add_argument(
        "image",
        nargs="?",
        help="画像パスまたはURL (直接実行時のみ)",
    )
    parser.add_argument("date", nargs="?", help="YYYY-MM-DD (直接実行時のみ)")
    parser.add_argument(
        "article_idx",
        type=int,
        nargs="?",
        default=0,
        help="記事番号: 0=一面トップ, 1〜=以降の記事 (直接実行時のみ)",
    )
    args = parser.parse_args()

    if args.from_issue:
        title = os.environ.get("ISSUE_TITLE", "")
        body = os.environ.get("ISSUE_BODY", "")
        if not title:
            print("ERROR: ISSUE_TITLE 環境変数が空です", file=sys.stderr)
            sys.exit(1)
        date_str, article_idx = parse_issue_title(title)
        urls = extract_image_urls(body)
        if not urls:
            print(
                "ERROR: Issue本文に画像が見つかりません。"
                "https://github.com/user-attachments/... 形式の画像を添付してください",
                file=sys.stderr,
            )
            sys.exit(2)
        img_source = urls[0]
        print(f"[attach_manga] Issue: {title}")
        print(f"      日付={date_str} 記事番号={article_idx} 画像={img_source[:80]}")
    else:
        if not args.image or not args.date:
            parser.print_help()
            sys.exit(1)
        img_source = args.image
        date_str = args.date
        article_idx = args.article_idx
        print(f"[attach_manga] 直接実行: {img_source} → {date_str} #{article_idx}")

    out_dir = ROOT / "docs" / date_str / "manga"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{article_idx:02d}.webp"

    print("      画像取得中...")
    img = download_image(img_source)
    compress_to_webp(img, out_path)

    print("      ページ再描画中...")
    rerender(date_str)

    print(f"完了: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
