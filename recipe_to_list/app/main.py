"""Telegram bot: collect recipe links, build a merged checklist, push checked items to HA."""

from __future__ import annotations

import html
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from .recipes import Recipe, fetch_recipe, parse_message

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
        "allowed_chat_ids": [int(x) for x in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if x],
        "todo_entity": os.environ["TODO_ENTITY"],
        "model": os.environ.get("MODEL", "claude-opus-5-5"),
        "pantry_staples": os.environ.get("PANTRY", "salt,black pepper,water").split(","),
    }


@dataclass
class Checklist:
    items: list[ShoppingItem]
    checked: set[int] = field(default_factory=set)


OPTS = load_options()
ALLOWED = set(OPTS.get("allowed_chat_ids") or [])
TODO = OPTS["todo_entity"]
PANTRY = OPTS.get("pantry_staples") or []
consolidator = Consolidator(OPTS["anthropic_api_key"] or None, OPTS.get("model") or "claude-opus-5-5")
ha = HomeAssistant()

pending: dict[int, list[Recipe]] = {}            # chat_id -> recipes collected so far
checklists: dict[tuple[int, int], Checklist] = {}  # (chat_id, message_id) -> checklist


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
    lines.append("\nSend more links, or tap <b>Build list</b>.")
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
        "Send me recipe links (add x2 to double one). I'll queue them up, then "
        "tap Build list to get one merged checklist.\n\n"
        "You can also paste a plain ingredient list.\n"
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


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    cid = update.effective_chat.id
    text = update.message.text or ""
    links = parse_message(text)

    if not links:
        lines = [ln.strip("•-* \t") for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            await update.message.reply_text("Send a recipe link, or paste an ingredient list (one per line).")
            return
        pending.setdefault(cid, []).append(Recipe("pasted", "Pasted ingredients", "", lines))
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot starting; allowed chats: %s; list: %s", sorted(ALLOWED) or "none yet", TODO)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
