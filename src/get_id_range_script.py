
import json
import re
import time
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests

START = "2409.18594"
END = "2410.03024"
BATCH_SIZE = 50
OUTPUT = Path("data/arxiv_metadata.json")
API_URL = "https://export.arxiv.org/api/query"

# Webshare rotating endpoint: https://www.webshare.io/blog/what-are-rotating-proxies
PROXY_ENABLED = True  # Set True after filling in your Webshare proxy credentials.
WEBSHARE_HOST = "p.webshare.io"
WEBSHARE_PORT = 80
WEBSHARE_USERNAME = "enhvxeqy-rotate"  # Proxy username, not API key; accepts the -rotate suffix.
WEBSHARE_PASSWORD = "vfl95aimirwr"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom"
}

session = requests.Session()
session.headers.update({
    "User-Agent": "arxiv-milestone1-metadata-crawler/1.0 (academic student project)"
})

last_request = 0.0


def get_request_proxies():
    """Build the Webshare rotating proxy URL, or use the existing connection."""
    if not PROXY_ENABLED:
        return None
    if not WEBSHARE_USERNAME or not WEBSHARE_PASSWORD:
        raise ValueError("Set WEBSHARE_USERNAME and WEBSHARE_PASSWORD first")

    username = WEBSHARE_USERNAME
    if not username.endswith("-rotate"):
        username += "-rotate"
    proxy_url = (
        f"http://{quote(username, safe='')}:{quote(WEBSHARE_PASSWORD, safe='')}"
        f"@{WEBSHARE_HOST}:{WEBSHARE_PORT}"
    )
    return {"http": proxy_url, "https": proxy_url}


def request_xml(ids):
    """Call arXiv API with rate limiting and retries."""
    global last_request

    proxies = get_request_proxies()

    for attempt in range(5):
        wait = 3.2 - (time.monotonic() - last_request)
        if wait > 0:
            time.sleep(wait)

        last_request = time.monotonic()

        try:
            response = session.get(
                API_URL,
                params={
                    "id_list": ",".join(ids),
                    "max_results": len(ids)
                },
                timeout=45,
                proxies=proxies,
                # A fresh connection lets Webshare rotate the IP on every attempt.
                headers={"Connection": "close"} if proxies else None
            )

            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                seconds = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else 5 * (2 ** attempt)
                )
                print(f"HTTP {response.status_code}, retry in {seconds}s")
                time.sleep(seconds)
                continue

            response.raise_for_status()
            return ET.fromstring(response.content)

        except (requests.RequestException, ET.ParseError) as exc:
            # Proxy exceptions can contain the URL with its username/password.
            error = type(exc).__name__ if proxies else str(exc)
            print(f"Attempt {attempt + 1}/5 failed: {error}")
            if attempt < 4:
                time.sleep(5 * (2 ** attempt))

    raise RuntimeError("arXiv API failed repeatedly")


def xml_text(entry, tag):
    value = entry.findtext(tag, default=None, namespaces=NS)
    return " ".join(value.split()) if value else None


def fetch_papers(ids):
    """Get metadata of requested arXiv IDs."""
    root = request_xml(ids)
    requested = set(ids)
    result = {}

    for entry in root.findall("atom:entry", NS):
        url = xml_text(entry, "atom:id") or ""

        match = re.search(
            r"/(\d{4}\.\d{4,5})(v\d+)?$",
            url
        )

        if not match or match.group(1) not in requested:
            continue

        paper_id = match.group(1)
        version_num = (
            int(match.group(2)[1:])
            if match.group(2)
            else 1
        )

        authors = [
            xml_text(a, "atom:name")
            for a in entry.findall("atom:author", NS)
        ]

        result[paper_id] = {
            "arxiv_id": paper_id,
            "latest_version": f"{paper_id}v{version_num}",
            "versions": [
                f"{paper_id}v{v}"
                for v in range(1, version_num + 1)
            ],
            "title": xml_text(entry, "atom:title"),
            "authors": [a for a in authors if a],
            "summary": xml_text(entry, "atom:summary"),
            "published": xml_text(entry, "atom:published"),
            "updated": xml_text(entry, "atom:updated"),
            "categories": [
                e.get("term")
                for e in entry.findall("atom:category", NS)
            ],
            "journal_ref": xml_text(entry, "arxiv:journal_ref"),
            "doi": xml_text(entry, "arxiv:doi")
        }

    return result


def find_last_september_id():
    """Find highest valid arXiv ID in September 2024."""
    if START not in fetch_papers([START]):
        raise RuntimeError(f"Starting ID {START} not found")

    low = int(START.split(".")[1])
    high = 99999

    while low < high:
        mid = (low + high + 1) // 2
        candidate = f"2409.{mid:05d}"

        if candidate in fetch_papers([candidate]):
            low = mid
        else:
            high = mid - 1

    return low


def save_json(data):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    temp = OUTPUT.with_suffix(".tmp")

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    temp.replace(OUTPUT)


def main():
    if OUTPUT.exists():
        with open(OUTPUT, encoding="utf-8") as f:
            data = json.load(f)

        if (
            data["range"]["start"] != START
            or data["range"]["end"] != END
        ):
            raise RuntimeError("Checkpoint range mismatch")

        print("Resuming from checkpoint...")

    else:
        last_sep = find_last_september_id()

        ids = (
            [
                f"2409.{i:05d}"
                for i in range(
                    int(START.split(".")[1]),
                    last_sep + 1
                )
            ]
            +
            [
                f"2410.{i:05d}"
                for i in range(
                    1,
                    int(END.split(".")[1]) + 1
                )
            ]
        )

        data = {
            "range": {
                "start": START,
                "end": END,
                "last_september_id": f"2409.{last_sep:05d}",
                "total_ids": len(ids),
                "total_papers": 0
            },
            "ids": ids,
            "papers": [],
            "processed_ids": [],
            "missing_ids": []
        }

        save_json(data)

    papers = {
        p["arxiv_id"]: p
        for p in data["papers"]
    }

    processed = set(data["processed_ids"])

    remaining = [
        pid for pid in data["ids"]
        if pid not in processed
    ]

    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i:i + BATCH_SIZE]
        found = fetch_papers(batch)

        if not found:
            raise RuntimeError(
                f"No results returned for batch starting {batch[0]}"
            )

        papers.update(found)
        processed.update(batch)

        data["papers"] = [
            papers[pid]
            for pid in data["ids"]
            if pid in papers
        ]

        data["range"]["total_papers"] = len(papers)

        data["processed_ids"] = [
            pid for pid in data["ids"]
            if pid in processed
        ]

        data["missing_ids"] = [
            pid for pid in data["processed_ids"]
            if pid not in papers
        ]

        save_json(data)

        print(
            f"Processed {len(processed)}/{len(data['ids'])} | "
            f"Found {len(papers)} papers"
        )

    print(f"\nCompleted: {len(papers)} papers")
    print(f"Missing IDs: {len(data['missing_ids'])}")
    print(f"Saved: {OUTPUT.resolve()}")


if __name__ == "__main__":
    main()
