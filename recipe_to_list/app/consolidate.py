"""Use Claude to merge ingredient lines from several recipes into one shopping list."""

from __future__ import annotations

import json

import anthropic
from pydantic import BaseModel

from .recipes import Recipe


class ShoppingItem(BaseModel):
    name: str
    """Plain grocery name, title case, no prep words. e.g. "Unsalted Butter"."""
    quantity: str
    """Total to buy, e.g. "5 tbsp", "3 lb", "2". Empty string if unknown/to taste."""
    category: str
    """Store section: Produce, Meat & Seafood, Dairy & Eggs, Bakery, Pantry, Spices,
    Frozen, Canned & Jarred, Beverages, Other."""
    pantry_staple: bool
    already_on_list: bool
    note: str
    """Very short note for anything the user should double-check, else empty."""


class ShoppingList(BaseModel):
    items: list[ShoppingItem]


class ExtractedRecipe(BaseModel):
    title: str
    yields: str
    ingredients: list[str]


SYSTEM = """You turn recipe ingredient lists into one consolidated grocery shopping list.

Rules:
- Merge the same ingredient across steps and across recipes into ONE item, summing quantities.
  Convert compatible units before adding (3 tbsp + 1/4 cup butter = 7 tbsp). Keep the unit a
  shopper would recognise; for large totals switch up (16 tbsp butter -> 2 sticks / 1 cup).
- Treat forms of the same purchase as one item when it's obvious (2 cloves garlic + 1 tsp minced
  garlic -> Garlic, ~3 cloves; diced onion + chopped onion -> Onion). Keep genuinely different
  products separate (unsalted vs salted butter, chicken breast vs thighs, fresh vs dried herbs).
- Apply each recipe's multiplier to its quantities before merging.
- Drop prep words (diced, softened, divided, room temperature) and anything not bought
  (water, ice unless a large amount, "reserved pasta water").
- If a recipe lists a component made from other listed ingredients (e.g. "1 batch pie crust,
  above"), don't add the component itself.
- Quantity "to taste"/unspecified -> empty quantity string.
- pantry_staple = true if the item matches (loosely) anything in the user's pantry list.
- already_on_list = true if the item is clearly already on the user's current grocery list.
- note: only when a merge involved a judgement call worth a glance, max ~6 words. Else "".
- Order items by category, then name."""


class Consolidator:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def _parse(self, prompt: str, schema, system: str):
        # Server-side fallback: if the model declines (very unlikely for recipes),
        # the API retries on a fallback model inside the same call.
        resp = await self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request.")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise RuntimeError(f"Claude returned an incomplete list (stop_reason={resp.stop_reason}).")
        return resp.parsed_output

    EXTRACT_SYSTEM = (
        "Extract the recipe's title, yield/servings, and every ingredient line verbatim, with "
        "quantities and units exactly as written. Include ingredients from every component "
        "(sauce, dough, topping). Don't include equipment or instruction steps. If there is "
        "more than one recipe, combine all their ingredients and title it with all the names. "
        "If you can't find any recipe ingredients, return an empty ingredients list. "
        "If there is no title, make up a short descriptive one."
    )

    async def _extract(self, recipe: Recipe, content) -> Recipe:
        out: ExtractedRecipe = await self._parse(content, ExtractedRecipe, self.EXTRACT_SYSTEM)
        recipe.title = out.title or recipe.title
        recipe.yields = out.yields
        recipe.ingredients = [i.strip() for i in out.ingredients if i.strip()]
        recipe.page_text = None
        return recipe

    async def extract_from_page(self, recipe: Recipe) -> Recipe:
        """Fallback for web pages without schema.org recipe data."""
        return await self._extract(recipe, f"Web page {recipe.url}:\n\n{recipe.page_text}")

    async def extract_from_text(self, recipe: Recipe, text: str) -> Recipe:
        """Pasted text: a bare ingredient list or a whole recipe with steps."""
        return await self._extract(recipe, f"Text pasted by the user:\n\n{text}")

    async def extract_from_images(self, recipe: Recipe, images: list[tuple[str, str]], caption: str) -> Recipe:
        """Photos of a recipe (cookbook page, recipe card, screenshot). images = (media_type, base64)."""
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}
            for mt, data in images
        ]
        note = f"The user's caption: {caption}\n\n" if caption else ""
        content.append({"type": "text", "text": note + "Extract the recipe from these photo(s)."})
        return await self._extract(recipe, content)

    async def consolidate(
        self, recipes: list[Recipe], pantry: list[str], existing: list[str]
    ) -> list[ShoppingItem]:
        payload = {
            "recipes": [
                {
                    "title": r.title,
                    "yields": r.yields,
                    "multiplier": r.multiplier,
                    "ingredients": r.ingredients,
                }
                for r in recipes
            ],
            "pantry_staples": pantry,
            "current_grocery_list": existing,
        }
        out: ShoppingList = await self._parse(json.dumps(payload, indent=1), ShoppingList, SYSTEM)
        return out.items
