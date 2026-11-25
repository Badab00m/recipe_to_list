# Changelog

## 1.1.0
- Send a photo of a recipe (cookbook page, recipe card, screenshot) and its ingredients are read
  from the image. Send several photos together for a multi-page recipe. Add `x2` in the caption to scale.
- Paste a whole recipe, not just an ingredient list. Intro text and steps are ignored.

## 1.0.2
- Ignore messages that piled up while the app was stopped, instead of answering them all on startup.
- Recognize links without "https://" and links hidden behind text (e.g. some share buttons).
- Clearer reply when a message has no link, and each incoming message is now logged.

## 1.0.1
- Fix "Invalid list for option 'allowed_chat_ids'" when saving settings. Chat IDs are now a plain text field; separate several with commas.

## 1.0.0
- First release: Telegram link intake, Claude-merged shopping list, checklist confirmation, push to an HA to-do list.
