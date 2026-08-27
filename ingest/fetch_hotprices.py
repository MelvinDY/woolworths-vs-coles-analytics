"""FR-1 — fetch the Hot Prices AU canonical dumps and land them on disk.

Hot Prices AU (https://hotprices.org/, source at github.com/Javex/hotprices-au,
a fork of badlogic/heissepreise) has scraped Coles and Woolworths daily since
September 2023 and publishes the whole thing as two gzipped JSON files. This
project's own collection starts in July 2026, so those two files are roughly
three years of history it cannot otherwise have — see PRD-v3 §1.

Attribution and licence
-----------------------
The hotprices-au *code* is MIT. The *data* carries no stated licence. PRD-v3 §8
records this as an open item: local analysis is fine, publishing derived figures
waits on the author's answer. Every row landed by this module carries its source
URL so the provenance travels with the data instead of living in a README.

What this module does not do
----------------------------
It does not scrape Hot Prices. It downloads two files that Hot Prices publishes
for its own frontend to consume, once, and caches them. It does not overwrite a
file it has already stored: a dump is a dated observation of somebody else's
series, and PRD-v3 §5.2 treats their collection calendar as evidence, so
silently replacing yesterday's copy would destroy the only record of what they
said yesterday.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTERNAL_DIR = PROJECT_ROOT / "data" / "external"

BASE_URL = "https://hotprices.org/data"

# Hot Prices' own store vocabulary on the left, this repo's on the right. The
# mapping lives here, at the boundary, so nothing downstream ever sees 'woolies'.
STORES: dict[str, str] = {
    "coles": "coles",
    "woolies": "woolworths",
}

USER_AGENT = (
    "woolworths-vs-coles-analytics/3.0 "
    "(+https://github.com/melvindarial/woolworths-vs-coles-analytics; "
    "personal price-analytics study)"
)

TIMEOUT_SECONDS = 180


def dump_path(store: str, fetched_date: dt.date, external_dir: Path = EXTERNAL_DIR) -> Path:
    return external_dir / f"hotprices_{store}_{fetched_date.isoformat()}.json.gz"


def latest_dump(store: str, external_dir: Path = EXTERNAL_DIR) -> Path | None:
    """Most recently fetched dump for a store, or None if we have never fetched."""
    found = sorted(external_dir.glob(f"hotprices_{store}_*.json.gz"))
    return found[-1] if found else None


def _download(store: str, dest: Path) -> None:
    url = f"{BASE_URL}/latest-canonical.{store}.compressed.json.gz"
    log.info("Fetching %s -> %s", url, dest.name)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = response.read()

    # Validate before writing. A truncated or HTML error page written to
    # data/external/ would look like a real dated observation forever after,
    # and the whole point of never overwriting is that mistakes are permanent.
    try:
        products = json.loads(gzip.decompress(payload))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{url} did not return usable gzipped JSON: {exc}") from exc
    if not isinstance(products, list) or not products:
        raise RuntimeError(f"{url} returned {type(products).__name__}, expected a non-empty list")
    if "priceHistory" not in products[0]:
        raise RuntimeError(f"{url} has no priceHistory field — the upstream format has changed")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    log.info("%s: %d products, %.1f MB", store, len(products), len(payload) / 1e6)


def run(
    fetched_date: dt.date | None = None,
    external_dir: Path = EXTERNAL_DIR,
    force: bool = False,
) -> dict[str, Path]:
    """Fetch both dumps for a date. Returns {store: path}.

    Already-stored dates are skipped rather than refetched, so this is safe to
    call from the daily pipeline. `force` re-downloads only when the file for
    the date is absent; it never overwrites (see module docstring).
    """
    fetched_date = fetched_date or dt.date.today()
    paths: dict[str, Path] = {}

    for store in STORES:
        dest = dump_path(store, fetched_date, external_dir)
        if dest.exists() and not force:
            log.info("%s: already have %s, skipping", store, dest.name)
            paths[store] = dest
            continue
        if dest.exists():
            log.info("%s: %s exists and is never overwritten", store, dest.name)
            paths[store] = dest
            continue
        _download(store, dest)
        paths[store] = dest

    return paths


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    run()
