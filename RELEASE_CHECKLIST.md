# Release Checklist

## Before Git Init

- Confirm `project/web_panel_settings.example.json` contains only example values.
- Confirm `project/web_panel_settings.json` is not committed.
- Confirm `project/bot_panel.db` is not committed.
- Confirm `project/logs/`, `project/runtime/`, and `project/static/payment_receipts/` are not committed.
- Confirm `xray/runtime/config.json` is not committed.
- Confirm there is no real Telegram bot token or real admin ID in tracked files.

## Quick Checks

Run these locally before the first commit:

```bash
python -m py_compile setup_wizard.py project/web_panel.py project/config.py project/networking.py
```

Search for secrets or real IDs:

```bash
rg -n "bot_token|telegram_api_ip|main_admin_chat_ids|admin_chat_ids|AAE|Rogerpick|example_support" .
```

## First Git Commands

```bash
git init
git add .
git status
```

Review `git status` carefully before the first commit. The ignored runtime files should not appear.

## Recommended First Commit

```bash
git commit -m "Prepare offline Ubuntu bundle for release"
```

## Before GitHub Push

- Revoke/regenerate any Telegram token that was ever used during development.
- Double-check `README_OFFLINE_UBUNTU24.md` and `SERVER_RUN_COMMANDS.md`.
- Test the setup wizard once from a clean copy of the bundle.
