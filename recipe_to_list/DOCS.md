# Recipe to Grocery List

A Home Assistant app that turns recipe links into a grocery list.

Send a Telegram bot recipe links, photos of recipes (cookbook pages, recipe cards, screenshots),
or pasted recipe text. It merges every ingredient across all the recipes
(3 tbsp butter in one step + 2 tbsp in another → **Butter (5 tbsp)**) and shows you a
checklist in Telegram. Only the items you leave checked get added to your OurGroceries list,
or any other Home Assistant to-do list.

```
You: https://example.com/lasagna x2
You: https://example.com/garlic-bread
You: 📷 (photo of a cookbook page)
Bot: 3 recipe(s) queued … [🧾 Build list]
Bot: Shopping list: 23 items. Tap to check/uncheck.
     ✅ Unsalted Butter (7 tbsp)
     ✅ Garlic (~8 cloves)
     ⬜ Salt · pantry
     ⬜ Olive Oil · on list
     …
     [🛒 Add 21 items] [✖ Cancel]
```

**Contents**
- [What you need](#what-you-need)
- [Step 1: Install the app](#step-1-install-the-app)
- [Step 2: Create a Telegram bot](#step-2-create-a-telegram-bot)
- [Step 3: Get a Claude API key](#step-3-get-a-claude-api-key)
- [Step 4: Find your grocery list's entity ID](#step-4-find-your-grocery-lists-entity-id)
- [Step 5: Configure the app](#step-5-configure-the-app)
- [Step 6: Start the app and allow your chat](#step-6-start-the-app-and-allow-your-chat)
- [Step 7: Try it](#step-7-try-it)
- [Using it day to day](#using-it-day-to-day)
- [Sharing it with your household (Telegram group)](#sharing-it-with-your-household-telegram-group)
- [Settings reference](#settings-reference)
- [Troubleshooting](#troubleshooting)
- [Updating](#updating)

---

## What you need

- **Home Assistant OS** (or Supervised), meaning you have **Settings → Apps** (called **Add-ons** on
  older versions).
- **A to-do list in Home Assistant** to add items to. For OurGroceries, set up the
  [OurGroceries integration](https://www.home-assistant.io/integrations/ourgroceries/) first.
  Any other to-do integration works too.
- **Telegram** on your phone.
- **A Claude API key** with some credit on it (see step 3). Each merged list costs a few cents.

---

## Step 1: Install the app

1. In Home Assistant, go to **Settings → Apps → Install app**.
2. Open the **⋮** menu (top right) and choose **Repositories**.
3. Paste `https://github.com/Badab00m/recipe_to_list`, click **Add**, then close the dialog.
4. Scroll down to the **Recipe to Grocery List** section, open the app, and click **Install**.
   The first install builds the app on your machine and takes a few minutes.

Don't start it yet. It needs the settings from the next steps first.

---

## Step 2: Create a Telegram bot

The app talks to you through your own private Telegram bot.

1. In Telegram, search for **@BotFather** (the official one has a blue checkmark) and open it.
2. Send `/newbot`.
3. Give it a **display name**, e.g. `Grocery Helper`.
4. Give it a **username**. It must end in `bot` and be unique, e.g. `smith_grocery_bot`.
5. BotFather replies with a **token** that looks like `7123456789:AAH4k…`.
   Copy it and keep it private, since anyone with it can control your bot.

> **Use a new bot just for this.** If you already use a bot with Home Assistant's Telegram
> integration, don't reuse its token. Two programs reading the same bot conflict, and messages
> go missing.

---

## Step 3: Get a Claude API key

The app uses Claude to merge ingredients. Skip this step if you already have a key.

1. Sign in to the Claude Console at [platform.claude.com](https://platform.claude.com).
2. Under **Billing**, add a payment method and buy a small amount of credit. $5 lasts a long time.
3. Under **API keys**, click **Create key**, name it e.g. `recipe-to-list`, and copy it.
   It starts with `sk-ant-`.

---

## Step 4: Find your grocery list's entity ID

1. Go to **Settings → Devices & services → Entities**.
2. Type `todo.` in the search box.
3. Click the list you shop from, open its **⚙ settings**, and copy the **Entity ID**,
   e.g. `todo.groceries`. If you have several OurGroceries lists, each one has its own.

---

## Step 5: Configure the app

Open the app (**Settings → Apps → Recipe to Grocery List**) and go to the **Configuration** tab.

| Setting | What to enter |
|---|---|
| **telegram_bot_token** | The token from step 2 |
| **anthropic_api_key** | The key from step 3 |
| **todo_entity** | The entity ID from step 4, e.g. `todo.groceries` |
| **allowed_chat_ids** | Leave empty for now. You fill it in during step 6. |
| **model** | Leave as `claude-opus-5-5` |
| **pantry_staples** | Things you always have at home. They still show up on the checklist but start **unchecked**. Edit freely: `salt`, `olive oil`, `butter`, … |

Click **Save**.

---

## Step 6: Start the app and allow your chat

The bot only answers chats you allow. To allow yours, you need your chat ID, and the bot tells you what it is.

1. Go to the app's **Info** tab, make sure **Start on boot** is on, and click **Start**.
2. Open the **Log** tab. After a few seconds you should see a line like:
   ```
   Bot starting; allowed chats: none yet; list: todo.groceries
   ```
3. In Telegram, find your bot by the username from step 2, open it, and tap **Start**
   (or send `/start`).
4. The bot replies: *"Your chat ID is 123456789…"*. Copy that number.
5. Back on the **Configuration** tab, paste the number into **allowed_chat_ids** and click **Save**.
   To allow more than one chat, separate the IDs with commas: `123456789, -1001234567890`.

   > **If saving fails** with "expected str" or "Invalid list": the settings form can save the
   > chat ID as a number instead of text. Open **⋮ → Edit in YAML** and write the line with
   > single quotes, leaving the other settings unquoted:
   > ```yaml
   > allowed_chat_ids: '123456789'
   > ```
   > For several chats: `allowed_chat_ids: '123456789, -1001234567890'`
6. Go to the **Info** tab and click **Restart**.
7. Send `/start` to the bot again. This time it replies with instructions instead of your chat ID.
   You're set up.

---

## Step 7: Try it

1. Open any recipe in your phone's browser.
2. Tap **Share → Telegram →** your bot, then send it. Copying and pasting the link also works,
   and so does a photo of a recipe from a cookbook.
3. The bot replies with the recipe name and ingredient count, plus a **Build list** button.
4. Tap **Build list** and wait 10–30 seconds while Claude merges everything.
5. Check and uncheck items, then tap **Add N items**.
6. Open OurGroceries. The items are there, written like `Butter (5 tbsp)`.

---

## Using it day to day

- **Three ways to send a recipe**, and you can mix them:
  - **Link:** share or paste the recipe's web address.
  - **Photo:** take a picture of a cookbook page or recipe card, or send a screenshot. For a recipe
    that spans pages, select all the photos and send them together in one message; they're read as
    one recipe. Photos sent "as a file" work too, including iPhone HEIC photos.
  - **Pasted text:** paste just the ingredients, or the whole recipe with its intro and steps.
    Only the ingredients are kept.
- **Several recipes at once:** keep sending recipes before you tap **Build list**. Everything
  is merged into one list.
- **Scaling a recipe:** add `x2`, `x1.5`, `3x`, etc.:
  - with a link, in the same message: `https://example.com/chili x3`
  - with a photo, in the photo's caption: `x2`
  - with pasted text, on a line of its own at the start or end of the message
- **If a site won't load:** send a screenshot of the recipe, or paste it instead.
- **What starts unchecked:** pantry staples, and anything already on your grocery list. Tap to
  include them anyway. **Select all** and **Select none** are at the bottom.
- **"Double-check" notes:** when Claude had to make a judgment call (e.g. merging "2 cloves
  garlic" with "1 tsp minced garlic"), it lists the item above the checklist so you can take a look.
- **Commands:**
  - `/list`: show what's queued
  - `/clear`: empty the queue
  - `/help`: show instructions

---

## Sharing it with your household (Telegram group)

To let someone else use the bot too, put it in a Telegram group:

1. **Let the bot see normal messages in groups.** In @BotFather, send `/setprivacy`, pick
   your bot, and choose **Disable**. Otherwise, in a group the bot only sees commands, not the links you send.
2. Create a Telegram group with the people who should use it, and add your bot to it.
   If the bot was already in the group, remove it and add it again so the privacy change applies.
3. Send `/start` in the group. The bot replies with the **group's** chat ID, a negative
   number like `-1001234567890`.
4. Add that number to **allowed_chat_ids**, after a comma (keep your own too if you still want to use
   the bot privately), e.g. `123456789, -1001234567890`, click **Save**, and restart the app.

---

## Settings reference

| Setting | Required | Description |
|---|---|---|
| `telegram_bot_token` | Yes | Bot token from @BotFather. |
| `anthropic_api_key` | Yes | Claude API key. |
| `todo_entity` | Yes | The Home Assistant to-do list that items are added to. Must start with `todo.`. |
| `allowed_chat_ids` | Yes | Telegram chat IDs the bot will answer, separated by commas. Everyone else is ignored. |
| `model` | No | Claude model used for merging. Default `claude-opus-5-5`. `claude-sonnet-5-5` is cheaper. |
| `pantry_staples` | No | Items that start unchecked on the checklist. |

Your settings are stored in Home Assistant, not in this repository, so updates never touch them.

---

## Troubleshooting

Start with the app's **Log** tab. Most problems show up there.

| Problem | Fix |
|---|---|
| The app stops right after starting | Check the log. `InvalidToken` means the Telegram token is wrong or has extra spaces. |
| Bot doesn't reply at all | Make sure the app is running. Check that you're messaging the right bot (the username from step 2). |
| Log shows `Conflict: terminated by other getUpdates request` | Something else is using the same bot token, often Home Assistant's own Telegram integration. Create a new bot for this app (step 2). |
| "Failed to save: expected str" or "Invalid list for option 'allowed_chat_ids'" | Use **⋮ → Edit in YAML** and write `allowed_chat_ids: '123456789'`, with single quotes around the ID(s) only. See [step 6](#step-6-start-the-app-and-allow-your-chat). |
| Bot only ever replies with your chat ID | That chat isn't in **allowed_chat_ids** yet, or you didn't restart the app after saving. |
| Bot ignores links in a group | Turn privacy mode off (see [Sharing it with your household](#sharing-it-with-your-household-telegram-group)), then remove the bot from the group and add it back. |
| "Couldn't read <link>" | Some sites block automated requests. Send a screenshot of the recipe, or paste it instead. |
| "I couldn't find recipe ingredients in that photo" | Take the photo closer and straight on, in good light, with the ingredient list filling most of the frame. |
| "Merging failed: … authentication" | The Claude API key is wrong. Re-copy it into **anthropic_api_key** and restart the app. |
| "Merging failed: … credit balance" | Add credit in the Claude Console under **Billing**. |
| Bot says items were added, but they aren't in OurGroceries | Check **todo_entity**, and look for `add_item failed` in the log. Also check that the list itself works from Home Assistant: add an item by hand on its to-do page. |
| "This list expired" when tapping a button | The app restarted, which clears queued recipes and open checklists. Send the links again. |

---

## Updating

When a new version is released, Home Assistant shows an **Update** button on the app (usually
within a few hours; **⋮ → Check for updates** on the Apps page checks right away). Your
settings carry over. See [CHANGELOG](https://github.com/Badab00m/recipe_to_list/blob/main/recipe_to_list/CHANGELOG.md) for what changed.

## License
MIT. See [LICENSE](https://github.com/Badab00m/recipe_to_list/blob/main/LICENSE).
