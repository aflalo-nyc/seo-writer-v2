import logging
import re
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_VISION_MODEL
from naming import VIEWS, normalize_view

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _text(message) -> str:
    return "".join(b.text for b in message.content if b.type == "text").strip()


_GOLD_EXAMPLES = [
    ("Silk balloon pants crafted in NYC. Subtly sheer, lightweight, and voluminous with a tapered ankle."),
    ("A high-waisted, slightly-flared jean crafted from premium Japanese denim. Made in Los Angeles, the Bronte flatters with a contoured, leg-lengthening fit."),
]


def generate_seo(product_title: str, body_html: str, tags: str, handle: str = "", references: list[dict] | None = None) -> dict:
    """Write the SEO title + meta description for one product.

    `references` are live, already-approved examples from the same category
    ({"title", "seo_title", "seo_desc"}) so new copy matches what is on the site.
    """
    body_text = re.sub(r"<[^>]+>", " ", body_html or "").strip()
    body_text = re.sub(r"\s+", " ", body_text)[:1500]
    handle_readable = handle.replace("-", " ")

    ref_block = ""
    if references:
        lines = []
        for r in references[:5]:
            lines.append(f'- {r["title"]}\n  TITLE: {r["seo_title"]}\n  DESCRIPTION: {r["seo_desc"]}')
        ref_block = "\nLive examples already approved on aflalo.com for this category. Match this voice, rhythm and level of detail exactly:\n" + "\n".join(lines) + "\n"

    prompt = f"""You write SEO meta descriptions for Aflalo NYC, a luxury women's fashion brand.

Product: {product_title}
Handle: {handle_readable}
Description: {body_text}
{ref_block}
Write a meta description following this formula:
Sentence 1: [searchable product descriptor + material] crafted in [location].
Sentence 2: [searchable features — silhouette, fit, feel, fabric details].

Rules:
- Max 155 characters total. Count carefully.
- Use the word "crafted". Luxury tone — no generic filler, no second-person ("your").
- Use real search terms people type: fabric names, material quality, silhouette names, fit descriptors, prints or textures.
- Never mention closures or hardware: zippers, buttons, hooks, snaps. These are not search terms and not selling points.
- For denim: location is always "Los Angeles", material is always "premium Japanese denim".
- For other products: extract the location and material strictly from the product description. If a country or city is mentioned (e.g. "Made in Turkey", "Made in Italy"), you MUST include it as "crafted in [location]" in sentence 1. If no location is mentioned, omit it entirely. Never assume or invent a location.
- Sentence 2 must start with "The [Product Name]" (e.g. "The Ater Pant", "The Bronte Jean"). This is important for branded search.

Gold standard examples:
"{_GOLD_EXAMPLES[0]}"
"{_GOLD_EXAMPLES[1]}"

Also write the SEO title in this format: [Product Name] [Color] in [Material] | AFLALO
The color is in the handle: {handle_readable}
For denim use "Japanese Denim". For others extract material from the product title or description.

Respond in exactly this format and nothing else:
TITLE: <title here>
DESCRIPTION: <description here>"""

    message = _get_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _text(message)
    title_match = re.search(r"TITLE:\s*(.+)", text)
    desc_match = re.search(r"DESCRIPTION:\s*(.+)", text)
    title = title_match.group(1).strip() if title_match else ""
    description = desc_match.group(1).strip() if desc_match else ""
    if len(description) > 155:
        description = description[:155].rsplit(" ", 1)[0].rstrip(" ,.") + "."
    logger.debug("title=%d chars, desc=%d chars", len(title), len(description))
    return {"title": title, "description": description}


def classify_view(image_url: str, product_title: str) -> str:
    """Look at a product photo and return one of naming.VIEWS (e.g. 'Model Back')."""
    options = "\n".join(f"- {v}" for v in VIEWS)
    message = _get_client().messages.create(
        model=CLAUDE_VISION_MODEL,
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "url", "url": image_url}},
                {"type": "text", "text": f"""This is a product photo of "{product_title}" for a luxury fashion e-commerce site.
Classify the shot type. Pick exactly one label from this list and reply with the label only:
{options}

Definitions:
- "Model ..." = a person is wearing the garment. Front/Back/Side is the direction the body faces. "Model Detail" = a tight crop on a person wearing it.
- "Ghost ..." = the garment alone on an invisible mannequin or laid flat, no person.
- "Detail" = close-up of fabric, texture or construction with no person visible.
- "Campaign" = editorial or lifestyle scene where the garment is not the clear focus."""},
            ],
        }],
    )
    return normalize_view(_text(message))
