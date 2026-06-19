"""One-off helper: convert seed CSV Image Src URLs to picsum.photos URLs.

History:
  v1 used `placehold.co` — solid-colour text blocks, looked fake on Shopify.
  v2 used `loremflickr.com` — real topic-tagged photos, but Shopify import
     intermittently reported "Media processing failed" (loremflickr rate-limits
     and has cache-miss latency under batch load).
  v3 (current) uses `picsum.photos/seed/{seed}/600/800.jpg` — real photography
     served from Fastly CDN, direct .jpg URL, deterministic via the seed.
     Trade-off: photos are topic-agnostic (random landscapes / objects from
     the Unsplash pool) but they ALWAYS load and ALWAYS decode as a valid
     Shopify-compatible JPEG.

The MAPPING table is still keyed by (hex, encoded_text) — that disambiguates
products that share a Title but differ by Colour variant (Cotton Bucket Hat,
Canvas Tote Bag, Cotton Crew Socks) so each colourway still gets a different
seed and therefore a different photo. Seeds also stay stable across runs.

Two-pass logic so reruns stay safe:

Pass 1 — replace any remaining `placehold.co/...?text=...` URL OR any prior
`loremflickr.com` URL with the picsum URL for the same product seed.

Pass 2 — wrap every Image Src URL in double quotes if it isn't already. Picsum
URLs don't contain commas so quoting isn't strictly required, but quoting
costs nothing and protects against future tag-style services that do.

Run from the repo root:
    python scripts/_relink_catalog_images.py

Idempotent. Safe to delete after the swap is committed.
"""

from __future__ import annotations

import re
from pathlib import Path

# (hex_color, encoded_text) → (tag_set, lock_seed)
MAPPING: dict[tuple[str, str], tuple[str, int]] = {
    # ---- catalog.csv ------------------------------------------------------
    ("222222", "Classic+Black+Tee"):              ("tshirt,black,cotton,fashion", 1),
    ("F5F5F5", "White+Essential+Tee"):            ("tshirt,white,cotton,fashion", 2),
    ("1B2A4A", "Navy+Stripe+Tee"):                ("tshirt,navy,stripe,fashion", 3),
    ("556B2F", "Olive+Pocket+Tee"):               ("tshirt,olive,utility,fashion", 4),
    ("B7410E", "Rust+Henley+Tee"):                ("tshirt,henley,rust,fashion", 5),
    ("1A1A1A", "Oversized+Urban+Tee"):            ("tshirt,oversized,streetwear,black", 6),
    ("800000", "Oversized+Washed+Tee"):           ("tshirt,oversized,maroon,vintage", 7),
    ("D2B48C", "Oversized+Graphic+Tee"):          ("tshirt,oversized,beige,graphic", 8),
    ("1C1C1C", "Slim+Fit+Jeans+Black"):           ("jeans,slim,black,denim", 9),
    ("1B2A4A", "Relaxed+Jeans+Navy"):             ("jeans,navy,blue,denim", 10),
    ("556B2F", "Cargo+Joggers+Olive"):            ("joggers,cargo,olive,pants", 11),
    ("1A1A1A", "Fleece+Joggers+Black"):           ("joggers,fleece,black,pants", 12),
    ("D2B48C", "Terry+Joggers+Beige"):            ("joggers,beige,pants", 13),
    ("B7410E", "Floral+Midi+Dress"):              ("dress,floral,women,fashion", 14),
    ("1B2A4A", "Solid+A-Line+Dress"):             ("dress,navy,women,fashion", 15),
    ("556B2F", "Wrap+Maxi+Dress"):                ("dress,olive,women,wrap", 16),
    ("F5F5F5", "Cotton+Straight+Kurta"):          ("kurta,white,ethnic,indian", 17),
    ("800000", "Printed+Anarkali+Kurta"):         ("kurta,maroon,ethnic,anarkali", 18),
    ("F5F0E1", "Chikankari+Kurta"):               ("kurta,chikankari,ethnic,beige", 19),
    ("F5F5F5", "Canvas+Low+Sneakers"):            ("sneakers,canvas,white,shoes", 20),
    ("1B2A4A", "Retro+Runner+Sneakers"):          ("sneakers,retro,navy,running", 21),
    ("1A1A1A", "High-Top+Sneakers"):              ("sneakers,hightop,black,streetwear", 22),
    ("D2B48C", "Cotton+Bucket+Hat"):              ("hat,bucket,beige,fashion", 23),
    ("1A1A1A", "Cotton+Bucket+Hat"):              ("hat,bucket,black,fashion", 24),
    ("1B2A4A", "Canvas+Tote+Bag"):                ("tote,bag,navy,canvas", 25),
    ("556B2F", "Canvas+Tote+Bag"):                ("tote,bag,olive,canvas", 26),
    ("800000", "Woven+Leather+Belt"):             ("belt,leather,brown,fashion", 27),
    ("1A1A1A", "Cotton+Crew+Socks"):              ("socks,black,cotton", 28),
    ("F5F5F5", "Cotton+Crew+Socks"):              ("socks,white,cotton", 29),
    # ---- catalog_jeans_expansion.csv --------------------------------------
    ("87CEEB", "Basic+Straight+Jeans+Light+Blue"):("jeans,lightblue,denim,straight", 101),
    ("808080", "Budget+Slim+Jeans+Grey"):         ("jeans,grey,denim,slim", 102),
    ("1A1A1A", "Stretch+Skinny+Jeans+Black"):     ("jeans,black,skinny,denim", 103),
    ("2C3E50", "Distressed+Slim+Jeans+Blue"):     ("jeans,distressed,blue,denim", 104),
    ("4B0082", "High-Rise+Mom+Jeans+Indigo"):     ("jeans,women,indigo,denim", 105),
    ("6B8AB5", "Wide-Leg+Jeans+Washed+Blue"):     ("jeans,wideleg,women,blue", 106),
    ("232E5C", "Bootcut+Jeans+Dark+Indigo"):      ("jeans,bootcut,indigo,denim", 107),
    ("1A1A1A", "Cropped+Straight+Jeans+Black"):   ("jeans,cropped,women,black", 108),
    # ---- catalog_accessories_footwear_expansion.csv -----------------------
    ("8B7355", "Canvas+Sling+Bag+Tan"):           ("bag,sling,tan,fashion", 201),
    ("1A1A1A", "Canvas+Sling+Bag+Black"):         ("bag,sling,black,fashion", 202),
    ("1A1A1A", "Aviator+Sunglasses"):             ("sunglasses,aviator,fashion", 203),
    ("1B2A4A", "Cotton+Baseball+Cap+Navy"):       ("cap,baseball,navy,hat", 204),
    ("1A1A1A", "Cotton+Baseball+Cap+Black"):      ("cap,baseball,black,hat", 205),
    ("654321", "Leather+Bifold+Wallet"):          ("wallet,leather,brown,bifold", 206),
    ("D4A5A5", "Printed+Silk+Scarf"):             ("scarf,silk,women,fashion", 207),
    ("556B2F", "Webbing+Crossbody+Bag+Olive"):    ("crossbody,bag,olive,fashion", 208),
    ("1A1A1A", "Webbing+Crossbody+Bag+Black"):    ("crossbody,bag,black,fashion", 209),
    ("F5F5F5", "Canvas+Slip-Ons+White"):          ("shoes,slipon,white,canvas", 210),
    ("2D2D2D", "Chunky+Sandals+Black"):           ("sandals,women,black,fashion", 211),
    ("E85D3A", "Running+Sports+Shoes"):           ("sneakers,running,sports,shoes", 212),
    ("8B4513", "Flat+Loafers+Brown"):             ("loafers,women,brown,shoes", 213),
    # ---- catalog_ethnic_expansion.csv -------------------------------------
    ("8B0000", "Embroidered+Straight+Kurta"):     ("kurta,embroidered,maroon,ethnic", 301),
    ("4A6FA5", "Printed+Palazzo+Set"):            ("palazzo,kurta,ethnic,indigo", 302),
    ("2D2D2D", "Ethnic+Nehru+Jacket"):            ("nehru,jacket,ethnic,men", 303),
    ("F5F5F5", "Chikankari+White+Kurta"):         ("kurta,chikankari,white,ethnic", 304),
    ("800020", "Indo-Western+Asymmetric+Kurta"):  ("kurta,modern,burgundy,ethnic", 305),
}

TARGET_FILES = [
    "seed/catalog.csv",
    "seed/catalog_jeans_expansion.csv",
    "seed/catalog_accessories_footwear_expansion.csv",
    "seed/catalog_ethnic_expansion.csv",
]


def _placeholder(hex_color: str, encoded_text: str) -> tuple[str, str]:
    """Both placeholder variants used in the seed (light vs dark text colour)."""

    light = f"https://placehold.co/600x800/{hex_color}/FFFFFF?text={encoded_text}"
    dark = f"https://placehold.co/600x800/{hex_color}/31343C?text={encoded_text}"
    return light, dark


def _loremflickr(tags: str, lock: int) -> str:
    """v2 URL — kept only as a recognisable shape for Pass 1's rewrite."""

    return f"https://loremflickr.com/600/800/{tags}?lock={lock}"


def _picsum(seed: int) -> str:
    """Stable picsum.photos URL — direct JPEG from Fastly, deterministic per seed."""

    return f"https://picsum.photos/seed/{seed}/600/800.jpg"


# Pass 2 matchers: catch unquoted Image Src URLs sitting at the end of a CSV
# row (preceded by `,`, ending at end-of-line). Covers picsum (current), and
# loremflickr (v2 legacy in case any survived) — both ensure the URL is wrapped
# in `"..."` so loremflickr's comma-tag URLs never re-break a row.
_UNQUOTED_IMAGE_TAIL = re.compile(
    r",(https://(?:picsum\.photos|loremflickr\.com)/[^\r\n\"]*)(?=\r?\n|$)"
)


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    total_swaps = 0
    total_quotes = 0
    for rel in TARGET_FILES:
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        original = text

        # Pass 1: placehold.co OR loremflickr.com → picsum.photos. Each MAPPING
        # entry's seed is the stable per-product identifier; the same product
        # always gets the same picsum image across reruns.
        file_swaps = 0
        for (hex_color, encoded_text), (tags, lock) in MAPPING.items():
            new_url = _picsum(lock)
            # placehold variants (both light- and dark-text colourings)
            for old_url in _placeholder(hex_color, encoded_text):
                if old_url in text:
                    count = text.count(old_url)
                    text = text.replace(old_url, new_url)
                    file_swaps += count
            # legacy loremflickr URL from v2 (idempotent: noop after the first run)
            legacy = _loremflickr(tags, lock)
            if legacy in text:
                count = text.count(legacy)
                text = text.replace(legacy, new_url)
                file_swaps += count

        # Pass 2: wrap any unquoted picsum/loremflickr URL in double quotes.
        def _quote(m: re.Match[str]) -> str:
            return f',"{m.group(1)}"'

        text, file_quotes = _UNQUOTED_IMAGE_TAIL.subn(_quote, text)

        path.write_text(text, encoding="utf-8")
        delta_parts = []
        if file_swaps:
            delta_parts.append(f"{file_swaps} URL replacements")
        if file_quotes:
            delta_parts.append(f"{file_quotes} URLs quoted")
        if not delta_parts:
            delta_parts.append("no changes" if text == original else "noop write")
        print(f"{rel}: " + ", ".join(delta_parts))
        total_swaps += file_swaps
        total_quotes += file_quotes
    print(
        f"\nTotal: {total_swaps} URL replacements + {total_quotes} URLs CSV-quoted "
        f"across {len(TARGET_FILES)} files."
    )


if __name__ == "__main__":
    main()
