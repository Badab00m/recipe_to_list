# Changelog

## 1.0.2
- Ignore messages that piled up while the app was stopped, instead of answering them all on startup.
- Recognize links without "https://" and links hidden behind text (e.g. some share buttons).
- Clearer reply when a message has no link, and each incoming message is now logged.

## 1.0.1
- Fix "Invalid list for option 'allowed_chat_ids'" when saving settings. Chat IDs are now a plain text field; separate several with commas.

## 1.0.0
- First release: Telegram link intake, Claude-merged shopping list, checklist confirmation, push to an HA to-do list.
