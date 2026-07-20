"""生成済みのbrief.jsonを読んで、GmailでHTMLメールを送る。

GitHub Actionsの生成ステップの後に実行される。必要な環境変数:
  GMAIL_USER      送信元Gmailアドレス
  GMAIL_APP_PASS  Gmailのアプリパスワード(16桁、通常のログインPWではない)
  MAIL_TO         宛先(未指定ならGMAIL_USER自身に送る)
  PAGE_URL        Brief公開URL(メール内リンク先)
すべて揃っていなければ何もせず終了する(送信を任意機能にするため)。
"""

import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    user = os.environ.get("GMAIL_USER")
    app_pass = os.environ.get("GMAIL_APP_PASS")
    if not user or not app_pass:
        print("Gmail未設定のためメール送信をスキップ")
        return

    to_addr = os.environ.get("MAIL_TO") or user
    page_url = os.environ.get("PAGE_URL", "")

    brief_path = ROOT / "docs" / "brief.json"
    if not brief_path.exists():
        print("brief.jsonが無いため送信スキップ")
        return
    data = json.loads(brief_path.read_text(encoding="utf-8"))

    top = data.get("top_story", {})
    stories = data.get("stories", [])
    one_line = data.get("one_line_world", "")

    # 本文HTML: 一言 → トップ見出し → 他の見出し一覧 → リンクボタン
    rows = "".join(
        f'<li style="margin:6px 0;font-size:14px;color:#3D4A66">'
        f'<span style="color:#B07C1F">[{s.get("category","")}]</span> {s.get("headline","")}</li>'
        for s in stories
    )
    html = f"""\
<div style="max-width:560px;margin:0 auto;font-family:sans-serif;color:#1B2A4A">
  <p style="font-size:13px;color:#6B7280;border-bottom:2px solid #1B2A4A;padding-bottom:8px">
    AI Morning Editor 朝刊</p>
  <p style="font-size:14px">{one_line}</p>
  <h1 style="font-size:22px;line-height:1.4;margin:14px 0 6px">{top.get('headline','')}</h1>
  <p style="font-size:14px;line-height:1.7;color:#3D4A66">{top.get('summary','')}</p>
  <ul style="padding-left:18px;margin:14px 0">{rows}</ul>
  <p style="margin:22px 0">
    <a href="{page_url}" style="background:#1B2A4A;color:#fff;text-decoration:none;
       padding:12px 22px;border-radius:4px;font-size:15px">今日のブリーフを読む →</a>
  </p>
  <p style="font-size:11px;color:#9CA3AF">AIが収集・2ソース以上で照合済み</p>
</div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"☀️ 今日のブリーフ: {top.get('headline','')}"
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(f"{one_line}\n\n{top.get('headline','')}\n{page_url}", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, app_pass)
        s.send_message(msg)
    print(f"メール送信完了 → {to_addr}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 送信失敗で全体を落とさない(Briefは既に公開済みのため)
        print(f"メール送信エラー(無視して続行): {e}", file=sys.stderr)
