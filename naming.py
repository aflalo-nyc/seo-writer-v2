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

_IMAGE_EXTS = ("webp", "jpg", "jpeg", "png", "gif")


def _ascii(s: str) -> str:
    """Fold accents (Brontë -> Bronte) and drop anything non-ASCII."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _slug_words(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", "-", _ascii(s).lower()).split("-") if w]


def _pascal(s: str) -> str:
    return "".join(w.capitalize() for w in _slug_words(s))


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


def build_alt(title: str, color: str, view: str) -> str:
    """AFLALO Alune Dress in Wool Silk – Citron - Ghost Front  (max 125 chars)."""
    alt = f"AFLALO {title.strip()}"
    if color:
        alt += f" – {color}"
    alt += f" - {view}"
    if len(alt) > 125:
        alt = alt[:125].rsplit(" ", 1)[0].rstrip(" ,.-–")
    return alt


def build_filename(title: str, color: str, view: str, index: int, ext: str) -> str:
    """HerveSweater_Black_ModelFront_01.webp

    `index` is the image's position on the product so two shots with the same view stay unique.
    """
    ext = ext.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    parts = [_pascal(product_name(title)), _pascal(color), _pascal(view), f"{int(index):02d}"]
    return "_".join(p for p in parts if p) + f".{ext}"


_VIEW_TOKENS = "|".join(_pascal(v) for v in VIEWS)
_EXT_TOKENS = "|".join(_IMAGE_EXTS)
_STANDARD_RE = re.compile(rf"^[A-Za-z0-9]+_[A-Za-z0-9]+_({_VIEW_TOKENS})_\d{{2}}\.({_EXT_TOKENS})$")
_STANDARD_NO_COLOR_RE = re.compile(rf"^[A-Za-z0-9]+_({_VIEW_TOKENS})_\d{{2}}\.({_EXT_TOKENS})$")


def is_standard_filename(filename: str) -> bool:
    return bool(_STANDARD_RE.match(filename) or _STANDARD_NO_COLOR_RE.match(filename))


def is_standard_alt(alt: str) -> bool:
    return bool(alt) and alt.startswith("AFLALO ") and any(alt.endswith(f"- {v}") for v in VIEWS)


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
