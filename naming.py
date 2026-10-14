"""Single source of truth for the photo naming convention and alt-text formula.

Change VIEWS or the two build_* functions here and every part of the app follows.
"""
import re
import unicodedata

# Shot types the vision model may pick from.
VIEWS = [
    "Model Front", "Model Back", "Model Side", "Model Detail",
    "Ghost Front", "Ghost Back", "Ghost Side",
    "Detail", "Campaign",
]

# How each view reads to a shopper: alt text in plain words (a screen reader says "Ghost Front" to nobody),
# file names as lowercase words split by hyphens, which is what Google asks for (no underscores, no joined words).
_ALT_VIEW = {
    "Model Front": "front view on model", "Model Back": "back view on model", "Model Side": "side view on model",
    "Model Detail": "close-up on model", "Ghost Front": "front view", "Ghost Back": "back view", "Ghost Side": "side view",
    "Detail": "close-up", "Campaign": "campaign image",
}
_FILE_VIEW = {
    "Model Front": "model-front", "Model Back": "model-back", "Model Side": "model-side", "Model Detail": "model-closeup",
    "Ghost Front": "front", "Ghost Back": "back", "Ghost Side": "side", "Detail": "closeup", "Campaign": "campaign",
}

_IMAGE_EXTS = ("webp", "jpg", "jpeg", "png", "gif")


def _ascii(s: str) -> str:
    """Fold accents (Brontë -> Bronte) and drop anything non-ASCII."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _slug_words(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", "-", _ascii(s).lower()).split("-") if w]


def product_name(title: str) -> str:
    """'Herve Sweater in Cashmere' -> 'Herve Sweater'."""
    return re.split(r"\s+in\s+", title.strip(), maxsplit=1)[0].strip()


def material(title: str) -> str:
    """'Herve Sweater in Cashmere' -> 'Cashmere'."""
    parts = re.split(r"\s+in\s+", title.strip(), maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def color_from_handle(handle: str, title: str) -> str:
    """Handles are '<product-name>-<color>': 'herve-sweater-black' -> 'Black'.

    Removes the product-name and material words from the handle and title-cases what is left.
    """
    remove = set(_slug_words(product_name(title))) | set(_slug_words(material(title))) | {"in", "the"}
    words = [w for w in handle.lower().split("-") if w and w not in remove and not w.isdigit()]
    return " ".join(w.capitalize() for w in words)


def product_color(colors: list[str], handle: str, title: str) -> str:
    """The colour exactly as the store names it (the product's Color option).

    Handles drift from the colour ('monroe-top-red' sells Crimson, 'artusi-top-crimson' is a
    sweater), so the handle is only a fallback for products with no Color option. A product
    with several colours gets the one its handle names, if any.
    """
    colors = [c.strip() for c in colors if c and c.strip()]
    if len(colors) == 1:
        return colors[0]
    handle_words = set(handle.lower().split("-"))
    named = [c for c in colors if set(_slug_words(c)) <= handle_words]
    if len(named) == 1:
        return named[0]
    return color_from_handle(handle, title)


def _pieces(products: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """[(title, colour)] as a photo names them: in title order, so the photo reads the same from every product
    page it is on, and without a colour the title already says ('Turquoise Choker in White Gold' in Turquoise)."""
    out = []
    for title, color in sorted(products, key=lambda p: _ascii(p[0]).lower()):
        color = (color or "").strip()
        out.append((title.strip(), "" if set(_slug_words(color)) <= set(_slug_words(title)) else color))
    return out


def build_alt(products: list[tuple[str, str]], view: str) -> str:
    """AFLALO Dione Pant in Silk, Iris, front view on model  (max 125 chars).

    `products` = every (title, colour) whose page shows this photo file. Alt text belongs to the file, so a look
    photo on two pages names both: 'AFLALO Artusi Sweater in Wool, Black, and Shay Trouser in Wool, Moss, …'.
    """
    head = "AFLALO " + ", and ".join(f"{t}, {c}" if c else t for t, c in _pieces(products))
    tail = ", " + _ALT_VIEW[view]
    if len(head + tail) > 125:
        head = head[:125 - len(tail)].rsplit(" ", 1)[0].rstrip(" ,.-–")
    return head + tail


def build_filename(products: list[tuple[str, str]], view: str, index: int, ext: str) -> str:
    """aflalo-dione-pant-silk-iris-front-05.jpg

    A photo on several pages names each product without its material, to stay short:
    aflalo-artusi-sweater-black-shay-trouser-moss-model-front-02.jpg.
    `index` is the image's position on the product so two shots with the same view stay unique.
    """
    ext = ext.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    pieces = _pieces(products)
    words = ["aflalo"]
    for title, color in pieces:
        words += [w for w in _slug_words(title if len(pieces) == 1 else product_name(title)) if w != "in"]
        words += _slug_words(color)
    return "-".join(words + [_FILE_VIEW[view], f"{int(index):02d}"]) + f".{ext}"


_VIEW_TOKENS = "|".join(_FILE_VIEW.values())
_EXT_TOKENS = "|".join(_IMAGE_EXTS)
_STANDARD_RE = re.compile(rf"^aflalo(-[a-z0-9]+)+-({_VIEW_TOKENS})-\d{{2}}\.({_EXT_TOKENS})$")


def is_standard_filename(filename: str) -> bool:
    return bool(_STANDARD_RE.match(filename))


def view_from_alt(alt: str) -> str | None:
    """The view a standard alt text ends with ('…, back view on model' -> 'Model Back'), else None."""
    if not (alt or "").startswith("AFLALO "):
        return None
    return next((v for v, phrase in _ALT_VIEW.items() if alt.endswith(", " + phrase)), None)


def is_standard_alt(alt: str) -> bool:
    return view_from_alt(alt) is not None


def basename_from_url(url: str) -> str:
    return url.split("?", 1)[0].rsplit("/", 1)[-1]


def extension_from_url(url: str) -> str:
    base = basename_from_url(url)
    return base.rsplit(".", 1)[-1].lower() if "." in base else "jpg"


def normalize_view(text: str) -> str:
    """Map free-form model output onto one of VIEWS."""
    t = re.sub(r"[^a-z]", " ", (text or "").lower())
    for v in VIEWS:
        if v.lower() in t:
            return v
    if "ghost" in t or "flat" in t or "still" in t or "mannequin" in t:
        for side in ("back", "side", "front"):
            if side in t:
                return f"Ghost {side.capitalize()}"
        return "Ghost Front"
    if "detail" in t or "close" in t or "texture" in t:
        return "Detail"
    if "campaign" in t or "editorial" in t or "lifestyle" in t:
        return "Campaign"
    for side in ("back", "side", "front"):
        if side in t:
            return f"Model {side.capitalize()}"
    return "Model Front"
