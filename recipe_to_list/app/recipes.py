"""Fetch a recipe page and pull out its title, yield and raw ingredient lines."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_html

log = logging.getLogger(__name__)

# Many recipe sites block obvious bots; a normal browser UA avoids most of that.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

URL_RE = re.compile(r"https?://\S+")
# "x2", "2x", "×1.5", "*3" anywhere in the message scales that recipe.
SCALE_RE = re.compile(r"(?:^|\s)(?:[x×*]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*[x×])(?=\s|$)", re.I)


@dataclass
class Recipe:
    url: str
    title: str
    yields: str
    ingredients: list[str]
    multiplier: float = 1.0
    page_text: str | None = None  # set only when structured data was missing


def parse_message(text: str) -> list[tuple[str, float]]:
    """Return (url, multiplier) pairs from a chat message."""
    urls = URL_RE.findall(text)
    m = SCALE_RE.search(URL_RE.sub(" ", text))
    mult = float(m.group(1) or m.group(2)) if m else 1.0
    return [(u.rstrip(").,>"), mult) for u in urls]


async def fetch_recipe(url: str, multiplier: float = 1.0) -> Recipe:
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=30,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    return recipe_from_html(html, str(resp.url), multiplier)


def recipe_from_html(html: str, url: str, multiplier: float = 1.0) -> Recipe:
    try:
        s = scrape_html(html, org_url=url, supported_only=False)
        ingredients = [i.strip() for i in s.ingredients() if i and i.strip()]
        if ingredients:
            return Recipe(
                url=url,
                title=_safe(s.title) or url,
                yields=_safe(s.yields) or "",
                ingredients=ingredients,
                multiplier=multiplier,
            )
    except Exception as e:  # recipe_scrapers raises a variety of errors
        log.info("Structured scrape failed for %s: %s", url, e)

    # No schema.org data: hand the visible page text to Claude later.
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    return Recipe(url=url, title=title, yields="", ingredients=[], multiplier=multiplier, page_text=text)


def _safe(fn) -> str:
    try:
        return str(fn() or "").strip()
    except Exception:
        return ""
