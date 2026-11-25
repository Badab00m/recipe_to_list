"""Telegram bot: collect recipe links, build a merged checklist, push checked items to HA."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .consolidate import Consolidator, ShoppingItem
from .ha import HomeAssistant
from .images import prepare_image
from .recipes import SCALE_RE, Recipe, fetch_recipe, parse_message

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("recipe_to_list")

MAX_BUTTONS = 95  # Telegram caps inline keyboards at 100 buttons


def load_options() -> dict:
    p = Path("/data/options.json")
    if p.exists():
        return json.loads(p.read_text())
    # Local testing outside Home Assistant
    return {
        "telegram_bot_token": os.environ["TELEGRAM_BOT_TOKEN"],
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "allowed_chat_ids": os.environ.get("ALLOWED_CHAT_IDS", ""),
        "todo_entity": os.environ["TODO_ENTITY"],
        "model": os.environ.get("MODEL", "claude-opus-5-5"),
        "pantry_staples": os.environ.get("PANTRY", "salt,black pepper,water").split(","),
    }


@dataclass
class Checklist:
    items: list[ShoppingItem]
    checked: set[int] = field(default_factory=set)


OPTS = load_options()
def parse_chat_ids(value) -> set[int]:
    """Accept "123, -100456" (current format) or a list (older configs)."""
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    return {int(x) for x in re.findall(r"-?\d+", str(value or ""))}


ALLOWED = parse_chat_ids(OPTS.get("allowed_chat_ids"))
TODO = OPTS["todo_entity"]
PANTRY = OPTS.get("pantry_staples") or []
consolidator = Consolidator(OPTS["anthropic_api_key"] or None, OPTS.get("model") or "claude-opus-5-5")
ha = HomeAssistant()

pending: dict[int, list[Recipe]] = {}            # chat_id -> recipes collected so far
checklists: dict[tuple[int, int], Checklist] = {}  # (chat_id, message_id) -> checklist
albums: dict[str, list] = {}                       # media_group_id -> photo messages
_tasks: set[asyncio.Task] = set()                 # keeps album timers alive
ALBUM_WAIT = 2.0  # seconds to wait for the rest of an album to arrive


def allowed(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.id in ALLOWED


def item_label(it: ShoppingItem) -> str:
    return f"{it.name} ({it.quantity})" if it.quantity else it.name


def render(cl: Checklist) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for i, it in enumerate(cl.items[:MAX_BUTTONS]):
        box = "✅" if i in cl.checked else "⬜"
        tag = " · pantry" if it.pantry_staple else " · on list" if it.already_on_list else ""
        text = f"{box} {item_label(it)}{tag}"
        rows.append([InlineKeyboardButton(text[:64], callback_data=f"t:{i}")])
    rows.append([
        InlineKeyboardButton("Select all", callback_data="all"),
        InlineKeyboardButton("Select none", callback_data="none"),
    ])
    rows.append([
        InlineKeyboardButton(f"🛒 Add {len(cl.checked)} items", callback_data="add"),
        InlineKeyboardButton("✖ Cancel", callback_data="cancel"),
    ])

    lines = [f"<b>Shopping list</b>: {len(cl.items)} items. Tap to check/uncheck.",
             "Pantry staples and items already on your list start unchecked."]
    notes = [f"• {html.escape(it.name)}: {html.escape(it.note)}" for it in cl.items if it.note]
    if notes:
        lines += ["", "<b>Double-check:</b>", *notes]
    if len(cl.items) > MAX_BUTTONS:
        lines.append(f"\n⚠ Only the first {MAX_BUTTONS} items are shown (Telegram limit).")
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def collected_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🧾 Build list", callback_data="build"),
        InlineKeyboardButton("🗑 Start over", callback_data="clear"),
    ]])


def collected_text(chat_id: int) -> str:
    rs = pending.get(chat_id, [])
    lines = [f"<b>{len(rs)} recipe(s) queued:</b>"]
    for r in rs:
        scale = f" ×{r.multiplier:g}" if r.multiplier != 1 else ""
        serves = f" ({html.escape(r.yields)})" if r.yields else ""
        lines.append(f"• {html.escape(r.title)}{serves}{scale}: {len(r.ingredients)} ingredients")
    lines.append("\nSend more recipes (links, photos or text), or tap <b>Build list</b>.")
    return "\n".join(lines)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    if cid not in ALLOWED:
        await update.message.reply_text(
            f"Your chat ID is {cid}. Add it to allowed_chat_ids in the app's configuration, "
            "then restart the app."
        )
        return
    await update.message.reply_text(
        "Send me any of these, and add x2 to double a recipe:\n"
        "• a recipe link\n"
        "• a photo of a recipe (cookbook page, recipe card, screenshot). Send several "
        "photos together for a multi-page recipe\n"
        "• pasted text: an ingredient list or a whole recipe\n\n"
        "I'll queue them up. Tap Build list to get one merged checklist.\n"
        "/list shows what's queued, /clear empties it."
    )


async def show_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    await update.message.reply_text(
        collected_text(update.effective_chat.id), parse_mode=ParseMode.HTML, reply_markup=collected_markup()
    )


async def clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    pending.pop(update.effective_chat.id, None)
    await update.message.reply_text("Cleared.")


def pasted_multiplier(text: str) -> float:
    """In pasted recipes, only a line that is just "x2" (etc.) counts, so "2 x 4 inch" doesn't."""
    for line in text.splitlines():
        m = SCALE_RE.fullmatch(" " + line.strip())
        if m:
            return float(m.group(1) or m.group(2))
    return 1.0


NOTHING_FOUND = (
    "I didn't find a recipe in that. Send a recipe link, a photo of a recipe, "
    "or paste the ingredients or the whole recipe."
)


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    msg = update.message
    if msg.media_group_id:
        # Albums arrive as separate messages; collect them, then read them as one recipe.
        group = albums.setdefault(msg.media_group_id, [])
        group.append(msg)
        if len(group) == 1:
            task = asyncio.create_task(_read_album_later(msg.media_group_id, ctx))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
        return
    await read_photos(update.effective_chat.id, [msg], ctx)


async def _read_album_later(group_id: str, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await asyncio.sleep(ALBUM_WAIT)
    msgs = albums.pop(group_id, [])
    if msgs:
        await read_photos(msgs[0].chat.id, sorted(msgs, key=lambda m: m.message_id), ctx)


async def read_photos(cid: int, msgs: list, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    caption = " ".join(m.caption for m in msgs if m.caption)
    m = SCALE_RE.search(caption)
    mult = float(m.group(1) or m.group(2)) if m else 1.0
    n = len(msgs)
    log.info("Photo(s) from chat %s: %d image(s), caption %r", cid, n, caption[:120])
    status = await ctx.bot.send_message(cid, f"Reading {'photo' if n == 1 else f'{n} photos'}…")
    try:
        images = []
        for msg in msgs:
            tg_file = await (msg.photo[-1] if msg.photo else msg.document).get_file()
            images.append(await asyncio.to_thread(prepare_image, bytes(await tg_file.download_as_bytearray())))
        r = await consolidator.extract_from_images(Recipe("photo", "Recipe photo", "", [], mult), images, caption)
    except Exception as e:
        log.exception("Photo extraction failed")
        await status.edit_text(
            f"Couldn't read that photo ({type(e).__name__}). Try a clearer, closer shot, or paste the ingredients."
        )
        return
    await status.delete()
    if not r.ingredients:
        await ctx.bot.send_message(cid, "I couldn't find recipe ingredients in that photo. Try a clearer, closer shot.")
        return
    pending.setdefault(cid, []).append(r)
    await ctx.bot.send_message(cid, collected_text(cid), parse_mode=ParseMode.HTML, reply_markup=collected_markup())


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    cid = update.effective_chat.id
    text = update.message.text or ""
    entities = update.message.parse_entities([MessageEntity.URL, MessageEntity.TEXT_LINK])
    entity_urls = [e.url if e.type == MessageEntity.TEXT_LINK else value for e, value in entities.items()]
    links = parse_message(text, entity_urls)
    log.info("Message from chat %s: %d link(s): %r", cid, len(links), text[:120])

    if not links:
        if len(text.strip()) < 4:
            await update.message.reply_text(NOTHING_FOUND)
            return
        mult = pasted_multiplier(text)
        status = await update.message.reply_text("Reading your text…")
        try:
            r = await consolidator.extract_from_text(Recipe("pasted", "Pasted recipe", "", [], mult), text)
        except Exception as e:
            log.exception("Text extraction failed")
            await status.edit_text(f"Couldn't read that ({type(e).__name__}). Please try again.")
            return
        await status.delete()
        if not r.ingredients:
            await update.message.reply_text(NOTHING_FOUND)
            return
        pending.setdefault(cid, []).append(r)
    else:
        status = await update.message.reply_text("Reading recipe…")
        for url, mult in links:
            try:
                r = await fetch_recipe(url, mult)
                if not r.ingredients and r.page_text:
                    r = await consolidator.extract_from_page(r)
                if not r.ingredients:
                    await update.message.reply_text(f"Couldn't find ingredients at {url}. Try pasting them instead.")
                    continue
                pending.setdefault(cid, []).append(r)
            except Exception as e:
                log.exception("Fetch failed for %s", url)
                await update.message.reply_text(
                    f"Couldn't read {url} ({type(e).__name__}). Some sites block bots, so try pasting the ingredients."
                )
        await status.delete()

    if pending.get(cid):
        await update.message.reply_text(
            collected_text(cid), parse_mode=ParseMode.HTML, reply_markup=collected_markup()
        )


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not allowed(update):
        await q.answer()
        return
    cid, mid, data = q.message.chat.id, q.message.message_id, q.data

    if data == "clear":
        pending.pop(cid, None)
        await q.answer("Cleared")
        await q.edit_message_text("Queue cleared. Send a new link to start.")
        return

    if data == "build":
        recipes = pending.get(cid)
        if not recipes:
            await q.answer("Nothing queued")
            return
        await q.answer()
        await q.edit_message_text(f"Merging {len(recipes)} recipe(s)…")
        try:
            try:
                existing = await ha.get_open_items(TODO)
            except Exception:
                log.warning("Could not read current list; continuing without it", exc_info=True)
                existing = []
            items = await consolidator.consolidate(recipes, PANTRY, existing)
        except Exception as e:
            log.exception("Consolidation failed")
            await q.edit_message_text(
                f"Merging failed: {html.escape(str(e))}\nYour recipes are still queued; tap to retry.",
                parse_mode=ParseMode.HTML, reply_markup=collected_markup(),
            )
            return
        pending.pop(cid, None)
        cl = Checklist(items, {i for i, it in enumerate(items) if not (it.pantry_staple or it.already_on_list)})
        checklists[(cid, mid)] = cl
        text, kb = render(cl)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    cl = checklists.get((cid, mid))
    if cl is None:
        await q.answer("This list expired (the app restarted). Send the links again.", show_alert=True)
        return

    if data.startswith("t:"):
        i = int(data[2:])
        cl.checked ^= {i}
    elif data == "all":
        cl.checked = set(range(min(len(cl.items), MAX_BUTTONS)))
    elif data == "none":
        cl.checked = set()
    elif data == "cancel":
        checklists.pop((cid, mid), None)
        await q.answer()
        await q.edit_message_text("Cancelled. Nothing was added.")
        return
    elif data == "add":
        if not cl.checked:
            await q.answer("Nothing checked")
            return
        await q.answer()
        chosen = [cl.items[i] for i in sorted(cl.checked)]
        await q.edit_message_text(f"Adding {len(chosen)} items…")
        added, failed = [], []
        for it in chosen:
            try:
                await ha.add_item(TODO, item_label(it))
                added.append(it)
            except Exception:
                log.exception("add_item failed for %s", it.name)
                failed.append(it)
        checklists.pop((cid, mid), None)
        msg = f"✅ Added {len(added)} items to your list."
        if failed:
            msg += "\n⚠ Failed: " + ", ".join(html.escape(item_label(f)) for f in failed)
        await q.edit_message_text(msg, parse_mode=ParseMode.HTML)
        return

    await q.answer()
    text, kb = render(cl)
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


def main() -> None:
    app = Application.builder().token(OPTS["telegram_bot_token"]).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("list", show_list))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot starting; allowed chats: %s; list: %s", sorted(ALLOWED) or "none yet", TODO)
    # Skip messages that piled up while the app was stopped, so they aren't answered all at once.
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
