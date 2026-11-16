#!/usr/bin/env python3
"""Merge a get_users_posts JSON dump into data/ and regenerate RSS + OPML.

Usage:
    python3 scripts/update.py <username> <posts.json>
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_PATH = ROOT / "accounts.json"
DATA_DIR = ROOT / "data"
FEEDS_DIR = ROOT / "feeds"
RAW_FEED_BASE = "https://raw.githubusercontent.com/VirusPC/x-feeds/main/feeds"
MAX_POSTS = 200
TITLE_CHARS = 80


def load_json_payload(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    for opener in ("{", "["):
        start = raw.find(opener)
        if start != -1:
            obj, _ = decoder.raw_decode(raw, start)
            return obj
    raise ValueError(f"在 {path} 里找不到 JSON 对象或数组")


def as_posts_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise ValueError("posts.json 需要是对象或数组")
    if isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    if isinstance(payload.get("posts"), list):
        return [item for item in payload["posts"] if isinstance(item, dict)]
    raise ValueError("posts.json 里没有 data / posts 列表")


def load_accounts() -> list[dict[str, Any]]:
    if not ACCOUNTS_PATH.exists():
        return []
    data = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("accounts.json 必须是数组")
    return data


def account_for(username: str) -> dict[str, Any] | None:
    needle = username.lstrip("@")
    for account in load_accounts():
        if str(account.get("username") or "") == needle:
            return account
    return None


def first_present(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def referenced_types(post: dict[str, Any]) -> set[str]:
    refs = post.get("referenced_tweets") or post.get("referenced_posts") or []
    types: set[str] = set()
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, dict) and ref.get("type"):
                types.add(str(ref["type"]))
    return types


def normalize_post(post: dict[str, Any], username: str) -> dict[str, Any] | None:
    pid = post.get("id")
    if pid is None:
        return None
    pid = str(pid)
    created_at = post.get("created_at") or ""
    text = post.get("text") or ""
    if not isinstance(text, str):
        text = str(text)
    url = first_present(post.get("url"), f"https://x.com/{username}/status/{pid}")
    article = post.get("article") if isinstance(post.get("article"), dict) else {}
    article_title = first_present(post.get("article_title"), article.get("title") if article else None)
    article_text = first_present(
        article.get("plain_text") if article else None,
        article.get("preview_text") if article else None,
    )
    types = referenced_types(post)
    is_retweet = "retweeted" in types or text.startswith("RT @")
    is_reply = "replied_to" in types or bool(post.get("in_reply_to_user_id"))
    return {
        "id": pid,
        "created_at": created_at,
        "text": text,
        "url": url,
        "article_title": article_title,
        "article_text": article_text,
        "is_reply": bool(is_reply),
        "is_retweet": bool(is_retweet),
    }


def parse_created_at(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def sort_key(post: dict[str, Any]) -> tuple:
    dt = parse_created_at(str(post.get("created_at") or ""))
    stamp = dt.timestamp() if dt else 0.0
    return (-stamp, str(post.get("id") or ""))


def merge_posts(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for post in existing:
        pid = str(post.get("id") or "")
        if pid:
            by_id[pid] = post
    for post in incoming:
        pid = str(post.get("id") or "")
        if not pid:
            continue
        previous = by_id.get(pid)
        if previous is None:
            by_id[pid] = post
            continue
        merged = dict(previous)
        for key, value in post.items():
            if value not in (None, "", []) or merged.get(key) in (None, "", []):
                merged[key] = value
        by_id[pid] = merged
    merged_list = sorted(by_id.values(), key=sort_key)
    return merged_list[:MAX_POSTS]


def load_existing(username: str) -> list[dict[str, Any]]:
    path = DATA_DIR / f"{username}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("posts"), list):
        return [item for item in payload["posts"] if isinstance(item, dict)]
    return []


def item_title(post: dict[str, Any]) -> str:
    title = first_present(post.get("article_title"))
    if title:
        return title
    text = " ".join(str(post.get("text") or "").split())
    if not text:
        return f"Post {post.get('id')}"
    if len(text) <= TITLE_CHARS:
        return text
    return text[:TITLE_CHARS].rstrip() + "…"


def item_description(post: dict[str, Any]) -> str:
    body = first_present(post.get("article_text"), post.get("text"))
    return body or item_title(post)


def rfc822(value: str) -> str:
    dt = parse_created_at(value)
    if dt is None:
        dt = datetime.now(timezone.utc)
    return format_datetime(dt)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_rss(username: str, title: str, posts: list[dict[str, Any]]) -> str:
    channel_title = f"{title} (@{username})"
    link = f"https://x.com/{username}"
    description = f"Posts from @{username}, generated by VirusPC/x-feeds."
    last_build = rfc822(posts[0]["created_at"] if posts else "")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        f"    <title>{escape(channel_title)}</title>",
        f"    <link>{escape(link)}</link>",
        f"    <description>{escape(description)}</description>",
        "    <language>en</language>",
        f"    <lastBuildDate>{escape(last_build)}</lastBuildDate>",
        "    <generator>VirusPC/x-feeds</generator>",
    ]
    for post in posts:
        item_link = post.get("url") or f"https://x.com/{username}/status/{post['id']}"
        lines.extend(
            [
                "    <item>",
                f"      <title>{escape(item_title(post))}</title>",
                f"      <link>{escape(item_link)}</link>",
                f'      <guid isPermaLink="false">{escape(str(post["id"]))}</guid>',
                f"      <pubDate>{escape(rfc822(str(post.get('created_at') or '')))}</pubDate>",
                f"      <description>{escape(item_description(post))}</description>",
                "    </item>",
            ]
        )
    lines.extend(["  </channel>", "</rss>", ""])
    return "\n".join(lines)


def render_opml() -> str:
    accounts = {str(a.get("username")): a for a in load_accounts() if a.get("username")}
    usernames: list[str] = [str(a["username"]) for a in load_accounts() if a.get("username")]
    for path in sorted(FEEDS_DIR.glob("*.xml")):
        name = path.stem
        if name not in usernames:
            usernames.append(name)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        "  <head>",
        "    <title>VirusPC X Feeds</title>",
        "  </head>",
        "  <body>",
    ]
    for username in usernames:
        feed_path = FEEDS_DIR / f"{username}.xml"
        if not feed_path.exists():
            continue
        account = accounts.get(username) or {}
        title = str(account.get("title") or username)
        text = f"{title} (@{username})"
        xml_url = f"{RAW_FEED_BASE}/{username}.xml"
        html_url = f"https://x.com/{username}"
        lines.append(
            "    "
            f'<outline text="{escape(text)}" title="{escape(text)}" '
            f'type="rss" xmlUrl="{escape(xml_url)}" htmlUrl="{escape(html_url)}"/>'
        )
    lines.extend(["  </body>", "</opml>", ""])
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("用法: python3 scripts/update.py <username> <posts.json>", file=sys.stderr)
        return 2
    username = argv[1].lstrip("@")
    payload_path = Path(argv[2]).expanduser().resolve()
    if not payload_path.is_file():
        print(f"找不到文件: {payload_path}", file=sys.stderr)
        return 2

    incoming = [normalize_post(item, username) for item in as_posts_list(load_json_payload(payload_path))]
    incoming = [item for item in incoming if item is not None]
    if not incoming:
        print(f"{payload_path} 里没有可用帖子", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)

    merged = merge_posts(load_existing(username), incoming)
    write_json(DATA_DIR / f"{username}.json", merged)

    account = account_for(username)
    title = str((account or {}).get("title") or username)
    (FEEDS_DIR / f"{username}.xml").write_text(render_rss(username, title, merged), encoding="utf-8")
    (FEEDS_DIR / "index.opml").write_text(render_opml(), encoding="utf-8")

    print(f"updated {username}: posts={len(merged)} incoming={len(incoming)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
