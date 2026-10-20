# SDK SMM — Premium Telegram SMM Panel

A manually managed Telegram order bot built with Python, `python-telegram-bot`, and SQLite. Includes two-admin authorization, unique order IDs, order-group notifications, two required membership checks, editable categories/services, customer balance, and order status controls.

## Important hosting note

This project is configured for Render as a **Background Worker** with a persistent disk for SQLite. GitHub stores your code; it does not keep a Telegram bot running by itself. Do not deploy multiple copies polling with the same bot token.

## 1. Create the Telegram bot

1. Open `@BotFather` in Telegram and create a bot.
2. Copy the token.
3. Get numeric Telegram IDs for both admins.
4. Create an order notification group and add the bot. Make it an admin if needed to post messages.
5. Add the bot as an administrator to both required groups/channels so it can check membership. Use public `@usernames` for reliable checks.

## 2. Upload to GitHub

Upload `bot.py`, `requirements.txt`, `render.yaml`, `.gitignore`, and optionally `logo.svg` and `.env.example` to a repository. **Never upload a real bot token or `.env` file.**

## 3. Deploy on Render

1. Create a Render account and connect the GitHub repository.
2. Create a Background Worker (or use the Blueprint from `render.yaml`).
3. Add environment variables:
   - `BOT_TOKEN`: token from BotFather
   - `ADMIN_IDS`: two numeric IDs separated by a comma, e.g. `111111111,222222222`
   - `ORDER_GROUP_ID`: group ID, usually begins with `-100`
   - `FORCE_GROUP_1`: first group/channel username, e.g. `@mychannel`
   - `FORCE_GROUP_2`: second group/channel username
   - `BRAND_NAME`: desired brand name
   - `SUPPORT_USERNAME`: optional support username without `@` or with `@`
   - `DB_PATH`: `/var/data/smm_panel.db` when using the included persistent disk
4. Deploy and check the worker logs.

Render's free offerings and persistent-disk availability/pricing can change. A persistent disk may require a paid plan; without persistent storage, SQLite data can be lost when the instance restarts or redeploys. Verify the current plan details in Render before relying on it for real customer balances.

## Customer flow

- `/start`: membership gate and customer menu
- Browse categories and services
- Choose quantity and target URL/ID
- Order gets a unique ID and is posted to the order group
- Customer can check balance and recent orders

Orders require sufficient in-bot balance. Admins can manually adjust a balance through `/admin` → Adjust Balance. Add-funds instructions are manual; this starter does not verify bKash/Nagad payments automatically.

## Admin flow

Use `/admin`. Both IDs in `ADMIN_IDS` are authorized. Admin menu supports:
- Pending orders and all recent orders
- Processing / Completed / Cancelled status updates
- Add category
- Add service in this format: `Category name | Service name | Price per 1000 | Description`
- Adjust balance: `TelegramUserID | amount` (negative amount debits)
- Statistics

A cancellation refunds the order amount to the customer's bot balance.

## Notes / limitations

- This is a working starter, not a connection to an external SMM provider/API. Service fulfilment is manual.
- Only add services you are authorized to provide and follow each platform's rules.
- Telegram group membership checks can fail if the bot is not an administrator or the group identifier is invalid.
- For private groups, configure an invite link if you want a direct join button; the sample button URL is intended for public `@usernames`.
- Use backups before making changes to live customer balances.
