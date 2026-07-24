"""Audio Brief Generator — VOICEVOXで朝刊を聴けるmp3を生成する

ローカル手動実行専用。VOICEVOX Engine(localhost:50021)が起動済みであること。
生成物: docs/YYYY-MM-DD/brief.mp3  (ffmpegなければ brief.wav)

usage:
    python src/audio.py              # 最新日付フォルダを対象
    python src/audio.py 2026-07-23  # 日付指定
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

DEFAULT_SPEAKER_ID = 3          # ずんだもんノーマル
DEFAULT_SPEED_SCALE = 1.1
DEFAULT_HOST = "http://localhost:50021"


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_target_dir(docs_dir: Path, date_arg: str | None) -> Path:
    if date_arg:
        d = docs_dir / date_arg
        if not (d / "brief.json").exists():
            print(f"ERROR: {d}/brief.json が見つかりません", file=sys.stderr)
            sys.exit(1)
        return d
    for d in sorted(docs_dir.glob("20*-*-*"), reverse=True):
        if (d / "brief.json").exists():
            return d
    print("ERROR: brief.json が見つかりません", file=sys.stderr)
    sys.exit(1)


def clean_for_tts(text: str) -> str:
    """読み上げ向けにテキストを整形する。URLや記号を除去する。"""
    text = re.sub(r"https?://\S+", "", text)      # URL除去
    text = re.sub(r"[*#`]", "", text)              # マークダウン記号
    text = re.sub(r"[【】]", "", text)              # 【続報】などの括弧
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def build_segments(data: dict, date_label: str) -> list[str]:
    """brief.jsonから読み上げセグメントのリストを構築する。"""
    segs: list[str] = []

    segs.append(f"おはようございます。{date_label}の、AI Morning Editor です。")

    one_line = clean_for_tts(data.get("one_line_world", ""))
    if one_line:
        segs.append(f"本日の世界。{one_line}")

    top = data.get("top_story", {})
    if top:
        segs.append(f"一面トップ。{clean_for_tts(top.get('headline', ''))}")
        summary = clean_for_tts(top.get("summary", ""))
        if summary:
            segs.append(summary)
        why = clean_for_tts(top.get("why_it_matters", ""))
        if why:
            segs.append(f"注目ポイント。{why}")
        bg = clean_for_tts((top.get("deep") or {}).get("background", ""))
        if bg:
            segs.append(f"背景として。{bg}")

    for i, story in enumerate(data.get("stories", []), start=1):
        headline = clean_for_tts(story.get("headline", ""))
        summary = clean_for_tts(story.get("summary", ""))
        if headline:
            segs.append(f"記事{i}。{headline}")
        if summary:
            segs.append(summary)

    segs.append("以上、本日のブリーフィングでした。")
    return [s for s in segs if s.strip()]


def _get_gateway_ip() -> str | None:
    """WSLのデフォルトゲートウェイIPを `ip route show default` から取得する。"""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        words = result.stdout.split()
        idx = words.index("via")
        return words[idx + 1]
    except (ValueError, IndexError, OSError):
        return None


def resolve_voicevox_host(configured_host: str) -> str:
    """接続できるVOICEVOXホストを返す。localhost失敗時はゲートウェイIPへフォールバック。"""
    parsed = urlparse(configured_host)
    port = parsed.port or 50021

    def try_host(host: str) -> str | None:
        try:
            with urllib.request.urlopen(f"{host}/version", timeout=5) as resp:
                version = resp.read().decode().strip()
            print(f"VOICEVOX Engine {version} に接続しました ({host})")
            return host
        except OSError:
            return None

    if (h := try_host(configured_host)):
        return h

    gateway = _get_gateway_ip()
    if gateway:
        fallback = f"{parsed.scheme}://{gateway}:{port}"
        if fallback != configured_host:
            print(f"localhost 接続失敗。ゲートウェイ {gateway} へフォールバック中...")
            if (h := try_host(fallback)):
                return h

    print(
        f"ERROR: VOICEVOX に接続できません ({configured_host})\n"
        "  Windows側でVOICEVOX Engineを起動してください。",
        file=sys.stderr,
    )
    sys.exit(1)


def _api_post(url: str, data: bytes | None = None,
              headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def synthesize_segment(host: str, text: str, speaker_id: int,
                        speed_scale: float) -> bytes:
    """1セグメントをVOICEVOX APIでWAVバイト列として返す。"""
    encoded = urllib.parse.quote(text)
    query = json.loads(_api_post(
        f"{host}/audio_query?text={encoded}&speaker={speaker_id}"
    ))
    query["speedScale"] = speed_scale
    return _api_post(
        f"{host}/synthesis?speaker={speaker_id}",
        data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"},
    )


def concat_wavs(wav_list: list[bytes]) -> bytes:
    """複数のWAVバイト列をPython標準wave moduleで1本に結合する。"""
    params = None
    frames_list: list[bytes] = []
    for wav_bytes in wav_list:
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            if params is None:
                params = wf.getparams()
            frames_list.append(wf.readframes(wf.getnframes()))

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setparams(params)
        for frames in frames_list:
            wf.writeframes(frames)
    return out.getvalue()


def wav_to_mp3(wav_bytes: bytes, out_path: Path) -> bool:
    """ffmpegでWAV→MP3変換。ffmpegがなければFalseを返す。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp = Path(f.name)
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(tmp),
             "-codec:a", "libmp3lame", "-qscale:a", "4", str(out_path)],
            capture_output=True,
        )
        return result.returncode == 0
    finally:
        tmp.unlink(missing_ok=True)


def update_html(cfg: dict, date_dir: Path, data: dict) -> None:
    """brief.mp3 生成後に当日のHTMLを再描画してオーディオリンクを追加する。"""
    try:
        y, m, d = date_dir.name.split("-")
        dt = datetime(int(y), int(m), int(d), tzinfo=JST)
        today = dt.strftime("%Y.%m.%d")
        weekday = WEEKDAYS[dt.weekday()]
    except Exception:
        today = date_dir.name
        weekday = ""

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    html = env.get_template("brief.html.j2").render(
        site_title=cfg["site"]["title"],
        today=today,
        weekday=weekday,
        d=data,
        archive=[],
        in_root=False,
        weekly_archive=[],
        has_audio=True,
    )
    (date_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="VOICEVOXで朝刊のmp3を生成する")
    parser.add_argument("date", nargs="?", help="対象日付(例: 2026-07-23、省略時は最新)")
    args = parser.parse_args()

    cfg = load_config()
    audio_cfg = cfg.get("audio", {})
    host = str(audio_cfg.get("voicevox_host", DEFAULT_HOST))
    speaker_id = int(audio_cfg.get("speaker_id", DEFAULT_SPEAKER_ID))
    speed_scale = float(audio_cfg.get("speed_scale", DEFAULT_SPEED_SCALE))

    docs_dir = ROOT / "docs"
    date_dir = find_target_dir(docs_dir, args.date)

    print(f"対象: {date_dir}")
    print(f"話者ID: {speaker_id}  速度: {speed_scale}  VOICEVOX: {host}")

    host = resolve_voicevox_host(host)

    data = json.loads((date_dir / "brief.json").read_text(encoding="utf-8"))
    segments = build_segments(data, date_dir.name)
    print(f"セグメント数: {len(segments)}")

    wav_list: list[bytes] = []
    for i, seg in enumerate(segments, start=1):
        preview = seg[:40] + ("…" if len(seg) > 40 else "")
        print(f"  [{i}/{len(segments)}] {preview}")
        wav_list.append(synthesize_segment(host, seg, speaker_id, speed_scale))

    print("WAV結合中...")
    combined_wav = concat_wavs(wav_list)

    mp3_path = date_dir / "brief.mp3"
    if wav_to_mp3(combined_wav, mp3_path):
        print(f"MP3生成: {mp3_path}")
        out_path = mp3_path
    else:
        wav_path = date_dir / "brief.wav"
        wav_path.write_bytes(combined_wav)
        print(f"ffmpegが見つかりません。WAVとして出力: {wav_path}", file=sys.stderr)
        print("  sudo apt install ffmpeg でインストールするとMP3に変換できます。")
        out_path = wav_path

    print("HTMLを更新中(音声リンクを追加)...")
    update_html(cfg, date_dir, data)
    print(f"完了: {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
