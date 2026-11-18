"""Fetch the CNIL reference page and print its normalised SHA-256 (human-triggered, needs network).

    python tools/cnil_source.py            print the current hash and the section list
    python tools/cnil_source.py --check    compare with the hash recorded in docs/compliance/cnil/SOURCE.md

The page text is not stored in the repository; only its hash, date and section list are.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import sys
import urllib.request

URL = "https://www.cnil.fr/fr/technologies/lanonymisation-de-donnees-personnelles"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_MD = os.path.join(ROOT, "docs", "compliance", "cnil", "SOURCE.md")


def normalise(page: str) -> tuple[str, list[str]]:
    m = re.search(r"<main.*?</main>", page, re.S | re.I)
    body = m.group(0) if m else page
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<nav.*?</nav>|<form.*?</form>", " ", body, flags=re.S | re.I)
    sections = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()
                for h in re.findall(r"<h[23][^>]*>(.*?)</h[23]>", body, re.S)]
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    return text, sections


def fetch() -> tuple[str, list[str]]:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; source-check)"})
    with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310 - fixed https URL
        text, sections = normalise(res.read().decode("utf-8", "replace"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), sections


def recorded_hash() -> str | None:
    with open(SOURCE_MD, encoding="utf-8") as fh:
        m = re.search(r"Normalised SHA-256 \| `([0-9a-f]{64})`", fh.read())
    return m.group(1) if m else None


def main() -> int:
    digest, sections = fetch()
    print(f"normalised sha256: {digest}")
    for s in sections:
        print(f"  section: {s}")
    if "--check" in sys.argv:
        old = recorded_hash()
        if old != digest:
            print("SOURCE-DRIFT: the page differs from the recorded hash. A person must review the change before "
                  "SOURCE.md and requirements.yaml are updated.")
            return 1
        print("unchanged since the recorded retrieval")
    return 0


if __name__ == "__main__":
    sys.exit(main())
