"""ソースURLの死活確認。

判定基準:
  404 / 410 / DNS解決失敗 / 接続不能 → dead
  403 / 429 (ボット遮断の可能性)     → unverifiable
  200番台 / その他リダイレクト       → ok
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_TIMEOUT = 10
_DEAD = {404, 410}
_UNVERIFIABLE = {403, 429}


def _fetch(url: str) -> tuple[str, str]:
    """HEAD → 405なら GET にフォールバックして生死を判定する。"""
    for method in ("HEAD", "GET"):
        req = Request(url, headers={"User-Agent": _UA}, method=method)
        try:
            urlopen(req, timeout=_TIMEOUT)
            return url, "ok"
        except HTTPError as e:
            if e.code == 405 and method == "HEAD":
                continue
            if e.code in _DEAD:
                return url, "dead"
            if e.code in _UNVERIFIABLE:
                return url, "unverifiable"
            return url, "ok"
        except URLError:
            return url, "dead"
        except Exception:
            return url, "unverifiable"
    return url, "unverifiable"


def check_brief(data: dict, max_workers: int = 8) -> dict[str, str]:
    """brief.json 全ソースURLを並列チェックし {url: status} を返す。"""
    seen: set[str] = set()
    urls: list[str] = []
    for article in [data.get("top_story", {})] + data.get("stories", []):
        for src in article.get("sources", []):
            url = src.get("url", "")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    if not urls:
        return {}
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed({ex.submit(_fetch, u): u for u in urls}):
            url, status = fut.result()
            results[url] = status
    return results


def log_summary(results: dict[str, str]) -> None:
    ok = sum(1 for s in results.values() if s == "ok")
    dead = sum(1 for s in results.values() if s == "dead")
    unver = sum(1 for s in results.values() if s == "unverifiable")
    print(f"      リンク検証: OK={ok} / リンク切れ={dead} / 検証不能(403等)={unver}")
    for url, status in results.items():
        if status != "ok":
            label = "DEAD" if status == "dead" else "UNVERIFIABLE"
            print(f"      [{label}] {url}", file=sys.stderr)
