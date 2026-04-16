#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PAGE_INFO_RE = re.compile(
    r"var\s+__PAGE\s*=\s*\{[^}]*1:\s*(\d+)\s*,\s*2:\s*(\d+)\s*,\s*3:\s*(\d+)",
    re.S,
)
REPLY_HEADER_RE = re.compile(
    r"\[b\]Reply to \[pid=\d+(?:,\d+,\d+)?\]Reply\[/pid\] "
    r"Post by \[uid=(?P<uid>-?\d+)\](?P<name>.*?)\[/uid\] "
    r"\((?P<time>.*?)\)\[/b\]",
    re.S,
)
QUOTE_RE = re.compile(r"^\s*\[quote\](?P<quote>.*?)\[/quote\]\s*(?P<body>.*)$", re.S)
QUOTE_USER_RE = re.compile(r"Post by (.*?) \(")
QUOTE_TIME_RE = re.compile(r"\((.*?)\):")
QUOTE_CONTENT_RE = re.compile(r":\[/b\](.*)", re.S)
IMAGE_CODE_RE = re.compile(r"\[img\](.*?)\[/img\]", re.I | re.S)


@dataclass
class ThreadMeta:
    tid: int
    title: str
    folder_name: str
    total_pages: int
    current_page: int
    page_size: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill an NGA thread into Markdown.")
    parser.add_argument("--tid", type=int, required=True, help="Thread id, e.g. 45974302")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the existing nga_spider config.yaml",
    )
    parser.add_argument(
        "--base-url",
        default="https://bbs.nga.cn/read.php",
        help="NGA thread endpoint",
    )
    parser.add_argument(
        "--save-dir",
        default=None,
        help="Override save_dir from config.yaml",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help="Final Markdown file. Defaults to <thread folder>/posts.rebuilt.md",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start page for backfill",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="End page for backfill, defaults to last page",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.15,
        help="Sleep seconds between pages",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="Max retries per page",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout seconds",
    )
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="Download images into the thread images directory",
    )
    parser.add_argument(
        "--force-refetch",
        action="store_true",
        help="Ignore cached page snippets and refetch everything in the selected page range",
    )
    parser.add_argument(
        "--extra-query",
        default="",
        help="Extra query params to append to each read.php request, e.g. authorid=150058",
    )
    return parser.parse_args()


def load_config(config_path: Path) -> Dict:
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_session(cookie: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Cookie": cookie,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session


def fetch_text(
    session: requests.Session,
    url: str,
    timeout: int,
    retries: int,
    *,
    expect_page: Optional[int] = None,
    referer: Optional[str] = None,
) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            request_headers = {"Referer": referer} if referer else None
            response = session.get(url, timeout=timeout, headers=request_headers)
            response.raise_for_status()
            response.encoding = "gbk"
            text = response.text
            if "您访问的页面不存在" in text or "帖子不存在" in text:
                raise RuntimeError(f"NGA returned not-found for {url}")
            if expect_page is not None:
                page_info = parse_page_info(text)
                if page_info and page_info.current_page != expect_page:
                    raise RuntimeError(
                        f"expected page {expect_page}, got {page_info.current_page}"
                    )
            return text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait_seconds = min(2 ** (attempt - 1), 10)
            if "403" in str(exc):
                wait_seconds = max(wait_seconds, 30)
            print(
                f"[warn] fetch failed ({attempt}/{retries}) for {url}: {exc}",
                file=sys.stderr,
            )
            if attempt < retries:
                time.sleep(wait_seconds)
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def parse_page_info(text: str) -> Optional[ThreadMeta]:
    match = PAGE_INFO_RE.search(text)
    if not match:
        return None
    total_pages, current_page, page_size = map(int, match.groups())
    return ThreadMeta(
        tid=0,
        title="",
        folder_name="",
        total_pages=total_pages,
        current_page=current_page,
        page_size=page_size,
    )


def extract_balanced_braces(text: str, marker: str) -> Optional[str]:
    marker_index = text.find(marker)
    if marker_index == -1:
        return None
    start = text.find("{", marker_index)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def discover_thread_meta(
    session: requests.Session,
    base_url: str,
    tid: int,
    timeout: int,
    retries: int,
    extra_query: str,
) -> Tuple[ThreadMeta, str]:
    probe_url = build_thread_url(base_url, tid, 999999, extra_query)
    text = fetch_text(
        session,
        probe_url,
        timeout=timeout,
        retries=retries,
        referer=build_thread_url(base_url, tid, None, extra_query),
    )
    page_info = parse_page_info(text)
    if page_info is None:
        raise RuntimeError("could not find __PAGE metadata in NGA HTML")
    soup = BeautifulSoup(text, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else f"NGA-{tid}"
    folder_name = sanitize_folder_name(title.replace(" NGA玩家社区", "").replace(" NGA", ""))
    meta = ThreadMeta(
        tid=tid,
        title=title,
        folder_name=folder_name,
        total_pages=page_info.total_pages,
        current_page=page_info.current_page,
        page_size=page_info.page_size,
    )
    return meta, text


def sanitize_folder_name(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    return cleaned or "NGA帖子"


def cache_suffix(extra_query: str) -> str:
    if not extra_query:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", extra_query).strip("_")
    return f"_{cleaned}" if cleaned else ""


def build_thread_url(base_url: str, tid: int, page: Optional[int], extra_query: str) -> str:
    parsed = urlparse(base_url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items["tid"] = str(tid)
    if page is not None:
        query_items["page"] = str(page)
    else:
        query_items.pop("page", None)
    if extra_query:
        for key, value in parse_qsl(extra_query, keep_blank_values=True):
            query_items[key] = value
    new_query = urlencode(query_items)
    return urlunparse(parsed._replace(query=new_query))


def extract_user_map(text: str) -> Dict[str, Dict]:
    payload = extract_balanced_braces(text, "commonui.userInfo.setAll(")
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def normalize_text(raw_text: str) -> str:
    text = html.unescape(raw_text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_name(name: str) -> str:
    return re.sub(r"\[/?uid.*?\]", "", name).strip()


def format_body(raw_text: str) -> str:
    text = normalize_text(raw_text)
    quote_match = QUOTE_RE.match(text)
    if quote_match:
        quote_block = quote_match.group("quote")
        body = normalize_text(quote_match.group("body"))
        user_match = QUOTE_USER_RE.search(quote_block)
        quoted_user = clean_name(user_match.group(1)) if user_match else "未知用户"
        time_match = QUOTE_TIME_RE.search(quote_block)
        quoted_time = time_match.group(1) if time_match else "未知时间"
        content_match = QUOTE_CONTENT_RE.search(quote_block)
        quoted_content = normalize_text(content_match.group(1)) if content_match else ""
        body = replace_reply_headers(body)
        if quoted_content:
            return f"回复[@{quoted_user}][{quoted_time}]<<<{quoted_content}>>>\n\n{body}".strip()
        return f"回复[@{quoted_user}][{quoted_time}]\n\n{body}".strip()

    return replace_reply_headers(text)


def replace_reply_headers(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        quoted_user = clean_name(match.group("name"))
        quoted_time = match.group("time").strip()
        return f"\n\n回复[@{quoted_user}][{quoted_time}]\n\n"

    cleaned = REPLY_HEADER_RE.sub(repl, text)
    return normalize_text(cleaned)


def normalize_image_url(url: str) -> str:
    url = url.strip()
    if url.startswith("./"):
        return "https://img.nga.178.com/attachments/" + url[2:]
    if url.startswith("/"):
        return "https://img.nga.178.com" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://img.nga.178.com/attachments/" + url.lstrip("/")


def extract_images(content_tag: BeautifulSoup, raw_text: str) -> List[str]:
    found: List[str] = []
    seen = set()

    for img in content_tag.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        normalized = normalize_image_url(src)
        if normalized not in seen:
            seen.add(normalized)
            found.append(normalized)

    for code_url in IMAGE_CODE_RE.findall(raw_text):
        normalized = normalize_image_url(code_url)
        if normalized not in seen:
            seen.add(normalized)
            found.append(normalized)

    return found


def strip_image_codes(text: str) -> str:
    return normalize_text(IMAGE_CODE_RE.sub("", text))


def download_image(
    session: requests.Session,
    image_url: str,
    image_dir: Path,
    timeout: int,
    retries: int,
) -> Optional[Path]:
    filename = image_url.split("/")[-1].split("?")[0]
    target = image_dir / filename
    if target.exists():
        return target
    image_dir.mkdir(parents=True, exist_ok=True)
    try:
        response = session.get(image_url, timeout=timeout)
        response.raise_for_status()
        target.write_bytes(response.content)
        return target
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] image download failed for {image_url}: {exc}", file=sys.stderr)
        return None


def parse_posts_from_html(
    html_text: str,
    page_number: int,
    user_name_overrides: Dict[int, str],
    session: requests.Session,
    image_dir: Path,
    *,
    download_images: bool,
    timeout: int,
    retries: int,
) -> Tuple[List[str], int]:
    soup = BeautifulSoup(html_text, "html.parser")
    user_map = extract_user_map(html_text)
    rendered_posts: List[str] = []
    parsed_count = 0

    for row in soup.select("tr.postrow"):
        content_tag = row.find("span", class_="postcontent")
        if content_tag is None:
            continue

        container = row.find("td", id=re.compile(r"postcontainer"))
        if container is None:
            continue

        pid_anchor = container.find("a", id=re.compile(r"pid\d+Anchor"))
        if pid_anchor is None:
            continue
        pid_match = re.search(r"pid(\d+)Anchor", pid_anchor.get("id", ""))
        if pid_match is None:
            continue
        pid = pid_match.group(1)

        author_link = row.find("a", id=re.compile(r"postauthor"))
        uid = 0
        if author_link and author_link.get("href"):
            uid_match = re.search(r"uid=(-?\d+)", author_link["href"])
            if uid_match:
                uid = int(uid_match.group(1))

        username = ""
        if uid in user_name_overrides:
            username = user_name_overrides[uid]
        elif uid and str(uid) in user_map:
            username = user_map[str(uid)].get("username") or ""
        elif author_link:
            username = author_link.get_text(strip=True)
        username = username or (f"UID:{uid}" if uid else "未知用户")

        post_time_tag = container.find("span", id=re.compile(r"postdate"))
        post_time = post_time_tag.get_text(strip=True) if post_time_tag else "未知时间"

        for br in content_tag.find_all("br"):
            br.replace_with("\n")

        raw_text = content_tag.get_text("\n", strip=False)
        images = extract_images(content_tag, raw_text)
        cleaned_body = format_body(strip_image_codes(raw_text))

        image_lines: List[str] = []
        if images:
            for index, image_url in enumerate(images, start=1):
                if download_images:
                    local_image = download_image(
                        session,
                        image_url,
                        image_dir,
                        timeout=timeout,
                        retries=retries,
                    )
                    if local_image:
                        image_lines.append(f"[图片{index}](images/{local_image.name})")
                        continue
                image_lines.append(f"[图片{index}]({image_url})")

        block_lines = [
            f"<!-- pid:{pid} uid:{uid} page:{page_number} -->",
            f"**[@{username}]**发帖时间：{post_time}",
            "",
            cleaned_body,
        ]
        if image_lines:
            block_lines.append("")
            block_lines.extend(image_lines)
        block_lines.extend(["", "---", ""])
        rendered_posts.append("\n".join(block_lines))
        parsed_count += 1

    return rendered_posts, parsed_count


def write_page_cache(page_file: Path, blocks: Iterable[str]) -> None:
    page_file.parent.mkdir(parents=True, exist_ok=True)
    page_file.write_text("".join(blocks), encoding="utf-8")


def assemble_output(
    meta: ThreadMeta,
    page_cache_dir: Path,
    output_file: Path,
    start_page: int,
    end_page: int,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as handle:
        handle.write(f"# {meta.folder_name}\n\n")
        handle.write(f"- tid: `{meta.tid}`\n")
        handle.write(f"- pages: `{start_page}-{end_page}` / `{meta.total_pages}`\n")
        handle.write("- source: `bbs.nga.cn`\n\n")
        for page in range(start_page, end_page + 1):
            page_file = page_cache_dir / f"{page:05d}.md"
            if not page_file.exists():
                raise RuntimeError(f"missing page cache: {page_file}")
            handle.write(page_file.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    cookie = config.get("cookies")
    if not cookie:
        raise RuntimeError("config.yaml is missing cookies")

    save_dir = Path(args.save_dir or config.get("save_dir", "./nga_downloads")).expanduser()
    session = build_session(cookie)

    meta, last_page_html = discover_thread_meta(
        session,
        args.base_url,
        args.tid,
        args.timeout,
        args.retries,
        args.extra_query,
    )

    start_page = max(1, args.start_page)
    end_page = min(args.end_page or meta.total_pages, meta.total_pages)
    if start_page > end_page:
        raise RuntimeError(f"invalid page range: {start_page} > {end_page}")

    thread_dir = (config_path.parent / save_dir / meta.folder_name).resolve()
    image_dir = thread_dir / "images"
    cache_root = thread_dir / f".backfill_tid_{args.tid}{cache_suffix(args.extra_query)}"
    cache_dir = cache_root / "pages"
    output_file = (
        Path(args.output_file).expanduser().resolve()
        if args.output_file
        else thread_dir / "posts.rebuilt.md"
    )

    thread_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    meta_file = cache_root / "meta.json"
    meta_file.write_text(
        json.dumps(
            {
                "tid": meta.tid,
                "title": meta.title,
                "folder_name": meta.folder_name,
                "total_pages": meta.total_pages,
                "page_size": meta.page_size,
                "generated_at": int(time.time()),
                "extra_query": args.extra_query,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"[info] thread={meta.folder_name} tid={args.tid} "
        f"pages={start_page}-{end_page}/{meta.total_pages}"
    )

    user_name_overrides = {
        int(uid): name for uid, name in (config.get("user_names") or {}).items()
    }
    total_posts = 0

    for page in range(start_page, end_page + 1):
        page_file = cache_dir / f"{page:05d}.md"
        if page_file.exists() and not args.force_refetch:
            print(f"[skip] page {page} cached")
            continue

        if page == meta.current_page:
            html_text = last_page_html
        else:
            url = build_thread_url(args.base_url, args.tid, page, args.extra_query)
            html_text = fetch_text(
                session,
                url,
                timeout=args.timeout,
                retries=args.retries,
                expect_page=page,
                referer=build_thread_url(args.base_url, args.tid, None, args.extra_query),
            )

        blocks, count = parse_posts_from_html(
            html_text,
            page,
            user_name_overrides,
            session,
            image_dir,
            download_images=args.download_images,
            timeout=args.timeout,
            retries=args.retries,
        )
        write_page_cache(page_file, blocks)
        total_posts += count
        print(f"[ok] page {page}/{end_page} posts={count}")
        if args.sleep > 0 and page < end_page:
            time.sleep(args.sleep)

    assemble_output(meta, cache_dir, output_file, start_page, end_page)
    print(f"[done] output={output_file}")
    if total_posts:
        print(f"[done] parsed posts this run={total_posts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
