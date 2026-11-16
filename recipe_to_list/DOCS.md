# Recipe to Grocery List

Send recipe links to a Telegram bot. It merges every ingredient across all the recipes
(3 tbsp + 2 tbsp butter → 5 tbsp), shows a checklist in Telegram, and adds only the items you
leave checked to your OurGroceries list (or any Home Assistant to-do list).

## How it works

1. Send the bot one or more recipe links. Add `x2` to a message to double that recipe.
   You can also paste a plain ingredient list, one per line.
2. Keep sending links. The bot queues them up.
3. Tap **Build list**. Claude merges everything into one list. Pantry staples, and items already
   on your OurGroceries list, start **unchecked**.
4. Tap items to check or uncheck them, then tap **Add N items**.

Items are added as `Name (quantity)`, e.g. `Butter (5 tbsp)`, which is how OurGroceries
writes quantities itself.

## Setup

### 1. Create a Telegram bot
1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts.
2. Copy the token it gives you.

Use a **new** bot for this. If an existing bot is already connected to Home Assistant's
Telegram integration, both would try to read the same messages and conflict.

### 2. Find your OurGroceries list's entity ID
Go to **Settings → Devices & services → Entities** and search for `todo.`. Copy the one for
the OurGroceries list you shop from, e.g. `todo.groceries`.

### 3. Copy this folder onto the NUC
Copy the whole `recipe_to_list` folder into the **`/addons`** folder on Home Assistant, so you
end up with `/addons/recipe_to_list/config.yaml`. Either:
- Install the **Samba share** app and copy the folder into the `addons` share from your computer, or
- Install the **Studio Code Server** or **Advanced SSH & Web Terminal** app and upload it there.

### 4. Install the app
1. Go to **Settings → Apps → Install app** (on older versions: **Add-ons → Add-on store**).
2. Open the **⋮** menu (top right) and choose **Check for updates**.
3. **Recipe to Grocery List** appears under **Local apps**. Install it. The first build takes a
   few minutes.

### 5. Configure and start it
On the app's **Configuration** tab, set:

| Option | Value |
|---|---|
| `telegram_bot_token` | Token from BotFather |
| `anthropic_api_key` | Your Claude API key |
| `todo_entity` | e.g. `todo.groceries` |
| `allowed_chat_ids` | Leave empty for now |
| `pantry_staples` | Things you always have (these start unchecked) |
| `model` | Default `claude-opus-5-5`. See "Costs" below. |

Then:
1. Start the app.
2. Message your bot `/start`. It replies with your chat ID.
3. Add that number to `allowed_chat_ids`, save, and restart the app.

The bot ignores everyone not on `allowed_chat_ids`. To use it with your partner, create a
Telegram group, add the bot to it, send `/start` in the group, and add the group's ID instead.
Group IDs are negative numbers.

## Commands
- `/list`: show the queued recipes
- `/clear`: empty the queue

## Notes
- **Sites that block bots:** If a site won't load, the bot says so. Paste the ingredient
  list instead.
- **Pages without recipe markup:** Claude reads the page text and pulls out the ingredients.
- **Restarts:** Queued recipes and open checklists live in memory. Resend the links if the
  app restarts mid-list.
- **Refusals:** The app has Claude's server-side fallback turned on. If the model ever declines
  a request (very unlikely for recipes), the API retries it on a fallback model.
- **Costs:** One merged list for a few recipes costs roughly 5–10 cents on Claude Opus 5.5. If you'd
  rather spend less, set `model` to `claude-sonnet-5-5`.
- **Logs:** Check the app's **Log** tab if something goes wrong.
