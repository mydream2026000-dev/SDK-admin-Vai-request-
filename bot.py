import os
import sqlite3
import logging
import secrets
import string
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ORDER_GROUP_ID = os.getenv("ORDER_GROUP_ID", "").strip()
FORCE_GROUP_1 = os.getenv("FORCE_GROUP_1", "").strip()  # e.g. @YourChannel
FORCE_GROUP_2 = os.getenv("FORCE_GROUP_2", "").strip()
BRAND_NAME = os.getenv("BRAND_NAME", "NOVA SMM")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()
DB_PATH = os.getenv("DB_PATH", "smm_panel.db")

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if not ADMIN_IDS:
    raise RuntimeError("Set ADMIN_IDS to one or two Telegram numeric user IDs.")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, balance REAL NOT NULL DEFAULT 0,
            joined_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
            name TEXT NOT NULL, description TEXT DEFAULT '', price_per_1000 REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_code TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL, service_id INTEGER NOT NULL, service_name TEXT NOT NULL,
            quantity INTEGER NOT NULL, target TEXT NOT NULL, total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        c.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", ("Social Media",))
        cat = c.execute("SELECT id FROM categories WHERE name=?", ("Social Media",)).fetchone()["id"]
        c.execute("""INSERT INTO services(category_id,name,description,price_per_1000)
                     SELECT ?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM services WHERE name=?)""",
                  (cat, "Demo Social Media Service", "Example listing — replace with your own service.", 50.0, "Demo Social Media Service"))

def is_admin(user_id):
    return user_id in ADMIN_IDS

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Browse Services", callback_data="categories"),
         InlineKeyboardButton("💳 My Balance", callback_data="balance")],
        [InlineKeyboardButton("📦 My Orders", callback_data="myorders"),
         InlineKeyboardButton("➕ Add Funds", callback_data="addfunds")],
        [InlineKeyboardButton("📜 Terms", callback_data="terms"),
         InlineKeyboardButton("🆘 Support", callback_data="support")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Pending Orders", callback_data="admin_pending"),
         InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("➕ Add Category", callback_data="admin_addcat"),
         InlineKeyboardButton("➕ Add Service", callback_data="admin_addservice")],
        [InlineKeyboardButton("💰 Adjust Balance", callback_data="admin_balance"),
         InlineKeyboardButton("🧾 All Orders", callback_data="admin_orders")],
        [InlineKeyboardButton("🏠 Customer Menu", callback_data="home")]
    ])

async def membership_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return False
    missing = []
    for group in (FORCE_GROUP_1, FORCE_GROUP_2):
        if not group:
            continue
        try:
            member = await context.bot.get_chat_member(group, user.id)
            if member.status in ("left", "kicked", "banned"):
                missing.append(group)
        except Exception as e:
            log.warning("Membership check failed for %s: %s", group, e)
            # Fail closed when configured: bot must be an admin in each channel/group.
            missing.append(group)
    if missing:
        rows = []
        for g in missing:
            url = g if g.startswith("https://") else ("https://t.me/" + g.lstrip("@"))
            rows.append([InlineKeyboardButton("📢 Join " + g, url=url)])
        rows.append([InlineKeyboardButton("✅ Check Membership", callback_data="check_membership")])
        text = "🔒 *Join both required Telegram groups/channels to continue.*\n\nAfter joining, tap *Check Membership*."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)
        elif update.effective_message:
            await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)
        return False
    return True

def register_user(user):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id,username,joined_at) VALUES(?,?,?)",
                  (user.id, user.username or "", datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE users SET username=? WHERE user_id=?", (user.username or "", user.id))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if not await membership_ok(update, context):
        return
    await update.effective_message.reply_text(
        f"✨ *{BRAND_NAME} — Premium SMM Panel*\n\nWelcome! Choose an option below.",
        reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN
    )

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Admin access only.")
        return
    await update.effective_message.reply_text("🛡 *Admin Control Center*", reply_markup=admin_menu(), parse_mode=ParseMode.MARKDOWN)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("Cancelled. Use /start to open the menu.", reply_markup=main_menu())

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = update.effective_user
    data = q.data
    if data == "check_membership":
        await q.answer()
        if await membership_ok(update, context):
            await q.message.reply_text("✅ Membership verified!", reply_markup=main_menu())
        return
    if not await membership_ok(update, context):
        return
    await q.answer()

    if data == "home":
        await q.message.reply_text(f"✨ *{BRAND_NAME}*", reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)
    elif data == "categories":
        with db() as c:
            cats = c.execute("SELECT id,name FROM categories ORDER BY name").fetchall()
        rows = [[InlineKeyboardButton(r["name"], callback_data=f"cat:{r['id']}")] for r in cats]
        rows.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="home")])
        await q.message.reply_text("🗂 *Choose a category:*", reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)
    elif data.startswith("cat:"):
        cat_id = int(data.split(":")[1])
        with db() as c:
            services = c.execute("SELECT * FROM services WHERE category_id=? AND active=1 ORDER BY id", (cat_id,)).fetchall()
        rows = [[InlineKeyboardButton(f"{s['name']} — ৳{s['price_per_1000']:g}/1k", callback_data=f"svc:{s['id']}")] for s in services]
        rows.append([InlineKeyboardButton("⬅️ Categories", callback_data="categories")])
        await q.message.reply_text("🛍 *Available services:*", reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)
    elif data.startswith("svc:"):
        service_id = int(data.split(":")[1])
        with db() as c:
            s = c.execute("SELECT * FROM services WHERE id=? AND active=1", (service_id,)).fetchone()
        if not s:
            await q.message.reply_text("This service is no longer available.")
            return
        context.user_data["order_service_id"] = service_id
        context.user_data["flow"] = "quantity"
        await q.message.reply_text(
            f"🧾 *{s['name']}*\n{s['description'] or ''}\n\nPrice: ৳{s['price_per_1000']:g} per 1,000\nSend the quantity (minimum 1).",
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "balance":
        with db() as c:
            r = c.execute("SELECT balance FROM users WHERE user_id=?", (user.id,)).fetchone()
        await q.message.reply_text(f"💳 Your balance: *৳{(r['balance'] if r else 0):.2f}*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    elif data == "myorders":
        with db() as c:
            rows = c.execute("SELECT order_code,service_name,quantity,total,status FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (user.id,)).fetchall()
        if not rows:
            await q.message.reply_text("You have no orders yet.", reply_markup=main_menu())
        else:
            txt = "📦 *Your latest orders*\n\n" + "\n".join(f"`{r['order_code']}` · {r['service_name']} × {r['quantity']} · ৳{r['total']:.2f} · *{r['status']}*" for r in rows)
            await q.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
    elif data == "addfunds":
        await q.message.reply_text("➕ *Add Funds*\n\nContact an admin to request a manual balance top-up. Include your Telegram ID:\n`" + str(user.id) + "`", parse_mode=ParseMode.MARKDOWN)
    elif data == "terms":
        await q.message.reply_text("📜 *Terms:* Orders are manually reviewed. Do not submit targets you do not own or have permission to promote.", parse_mode=ParseMode.MARKDOWN)
    elif data == "support":
        msg = f"Contact @{SUPPORT_USERNAME.lstrip('@')}" if SUPPORT_USERNAME else "Contact a bot admin for support."
        await q.message.reply_text("🆘 " + msg)
    elif data.startswith("admin_"):
        if not is_admin(user.id):
            await q.message.reply_text("⛔ Admin access only.")
            return
        await admin_action(q, context, data)

async def admin_action(q, context, data):
    if data == "admin_pending" or data == "admin_orders":
        status_filter = " AND status='Pending'" if data == "admin_pending" else ""
        with db() as c:
            rows = c.execute("SELECT * FROM orders WHERE 1=1" + status_filter + " ORDER BY id DESC LIMIT 15").fetchall()
        if not rows:
            await q.message.reply_text("No matching orders.")
            return
        for r in rows:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏳ Processing", callback_data=f"status:{r['id']}:Processing"),
                 InlineKeyboardButton("✅ Complete", callback_data=f"status:{r['id']}:Completed")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"status:{r['id']}:Cancelled")]
            ])
            await q.message.reply_text(
                f"🧾 *{r['order_code']}*\nUser: `{r['user_id']}`\n{r['service_name']} × {r['quantity']}\nTarget: {r['target']}\nTotal: ৳{r['total']:.2f}\nStatus: *{r['status']}*",
                reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
    elif data == "admin_stats":
        with db() as c:
            users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            orders = c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
            pending = c.execute("SELECT COUNT(*) n FROM orders WHERE status='Pending'").fetchone()["n"]
            revenue = c.execute("SELECT COALESCE(SUM(total),0) n FROM orders WHERE status='Completed'").fetchone()["n"]
        await q.message.reply_text(f"📊 *Statistics*\nUsers: {users}\nOrders: {orders}\nPending: {pending}\nCompleted order value: ৳{revenue:.2f}", parse_mode=ParseMode.MARKDOWN)
    elif data == "admin_addcat":
        context.user_data["flow"] = "admin_addcat"
        await q.message.reply_text("Send the new category name.")
    elif data == "admin_addservice":
        context.user_data["flow"] = "admin_addservice"
        await q.message.reply_text("Send service details in this format:\n`Category name | Service name | Price per 1000 | Description`", parse_mode=ParseMode.MARKDOWN)
    elif data == "admin_balance":
        context.user_data["flow"] = "admin_balance"
        await q.message.reply_text("Send: `TelegramUserID | amount` (use a negative amount to debit).", parse_mode=ParseMode.MARKDOWN)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await membership_ok(update, context):
        return
    flow = context.user_data.get("flow")
    txt = (update.effective_message.text or "").strip()
    if not flow:
        await update.effective_message.reply_text("Choose an option from /start.", reply_markup=main_menu())
        return
    if flow == "quantity":
        try:
            qty = int(txt)
            if qty < 1 or qty > 10_000_000:
                raise ValueError()
        except ValueError:
            await update.effective_message.reply_text("Enter a whole number from 1 to 10,000,000.")
            return
        with db() as c:
            s = c.execute("SELECT * FROM services WHERE id=? AND active=1", (context.user_data["order_service_id"],)).fetchone()
        if not s:
            context.user_data.clear()
            await update.effective_message.reply_text("Service unavailable. Start again with /start.")
            return
        context.user_data["quantity"] = qty
        context.user_data["total"] = round(qty * s["price_per_1000"] / 1000, 2)
        context.user_data["flow"] = "target"
        await update.effective_message.reply_text(f"Send the target link or ID.\nEstimated total: ৳{context.user_data['total']:.2f}")
    elif flow == "target":
        service_id = context.user_data["order_service_id"]
        qty = context.user_data["quantity"]
        total = context.user_data["total"]
        with db() as c:
            s = c.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
            bal = c.execute("SELECT balance FROM users WHERE user_id=?", (user.id,)).fetchone()
            if not s:
                context.user_data.clear()
                await update.effective_message.reply_text("Service unavailable.")
                return
            if not bal or bal["balance"] < total:
                context.user_data.clear()
                await update.effective_message.reply_text(f"Insufficient balance. Order total is ৳{total:.2f}. Contact an admin to add funds.", reply_markup=main_menu())
                return
            code = "SM" + "".join(secrets.choice(string.digits) for _ in range(8))
            c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total, user.id))
            cur = c.execute("""INSERT INTO orders(order_code,user_id,service_id,service_name,quantity,target,total,status,created_at)
                               VALUES(?,?,?,?,?,?,?,'Pending',?)""",
                            (code, user.id, service_id, s["name"], qty, txt, total, datetime.now(timezone.utc).isoformat()))
            order_id = cur.lastrowid
        context.user_data.clear()
        await update.effective_message.reply_text(f"✅ *Order submitted!*\nOrder ID: `{code}`\nService: {s['name']}\nQuantity: {qty}\nTotal: ৳{total:.2f}\nStatus: Pending", parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu())
        if ORDER_GROUP_ID:
            try:
                group_text = (f"🆕 *NEW SMM ORDER*\nOrder ID: `{code}` (DB #{order_id})\n"
                              f"Customer: {user.mention_markdown_v2() if user.username else str(user.id)}\n"
                              f"User ID: `{user.id}`\nService: {s['name']}\nQuantity: {qty}\nTarget: {txt}\nTotal: ৳{total:.2f}\nStatus: Pending")
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏳ Processing", callback_data=f"status:{order_id}:Processing"),
                     InlineKeyboardButton("✅ Complete", callback_data=f"status:{order_id}:Completed")],
                    [InlineKeyboardButton("❌ Cancel", callback_data=f"status:{order_id}:Cancelled")]
                ])
                await context.bot.send_message(chat_id=ORDER_GROUP_ID, text=group_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            except Exception as e:
                log.exception("Could not send order to group: %s", e)
    elif flow == "admin_addcat":
        if not is_admin(user.id):
            context.user_data.clear()
            return
        try:
            with db() as c:
                c.execute("INSERT INTO categories(name) VALUES(?)", (txt,))
            await update.effective_message.reply_text("✅ Category added.")
        except sqlite3.IntegrityError:
            await update.effective_message.reply_text("That category already exists.")
        context.user_data.clear()
    elif flow == "admin_addservice":
        if not is_admin(user.id):
            context.user_data.clear()
            return
        try:
            category, name, price, desc = [x.strip() for x in txt.split("|", 3)]
            price = float(price)
            if price < 0:
                raise ValueError()
            with db() as c:
                cat = c.execute("SELECT id FROM categories WHERE name=?", (category,)).fetchone()
                if not cat:
                    raise LookupError()
                c.execute("INSERT INTO services(category_id,name,description,price_per_1000) VALUES(?,?,?,?)", (cat["id"], name, desc, price))
            await update.effective_message.reply_text("✅ Service added.")
        except LookupError:
            await update.effective_message.reply_text("Category not found. Add the category first; spelling must match.")
        except Exception:
            await update.effective_message.reply_text("Invalid format. Use: `Category name | Service name | Price per 1000 | Description`", parse_mode=ParseMode.MARKDOWN)
        context.user_data.clear()
    elif flow == "admin_balance":
        if not is_admin(user.id):
            context.user_data.clear()
            return
        try:
            uid_s, amount_s = [x.strip() for x in txt.split("|", 1)]
            uid, amount = int(uid_s), float(amount_s)
            with db() as c:
                row = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
                if not row:
                    raise LookupError()
                new_balance = row["balance"] + amount
                if new_balance < 0:
                    raise ValueError()
                c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, uid))
            await update.effective_message.reply_text(f"✅ Balance updated. New balance: ৳{new_balance:.2f}")
            try:
                await context.bot.send_message(uid, f"Your SMM panel balance was adjusted by ৳{amount:.2f}. New balance: ৳{new_balance:.2f}")
            except Exception:
                pass
        except LookupError:
            await update.effective_message.reply_text("User not found. They must start the bot first.")
        except Exception:
            await update.effective_message.reply_text("Invalid input or balance would become negative. Format: `TelegramUserID | amount`", parse_mode=ParseMode.MARKDOWN)
        context.user_data.clear()

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(update.effective_user.id):
        await q.answer("Admin only.", show_alert=True)
        return
    _, order_id, status = q.data.split(":", 2)
    with db() as c:
        row = c.execute("SELECT * FROM orders WHERE id=?", (int(order_id),)).fetchone()
        if not row:
            await q.answer("Order not found.", show_alert=True)
            return
        previous = row["status"]
        c.execute("UPDATE orders SET status=? WHERE id=?", (status, int(order_id)))
        # Refund on cancellation only once.
        if status == "Cancelled" and previous != "Cancelled":
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (row["total"], row["user_id"]))
    await q.answer("Order updated.")
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Status: {status}", callback_data="noop")]
    ]))
    try:
        await context.bot.send_message(row["user_id"], f"📦 Order `{row['order_code']}` status updated: *{status}*." + ("\nCancelled order amount refunded to your balance." if status == "Cancelled" and previous != "Cancelled" else ""), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context.error)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(status_callback, pattern=r"^status:"))
    app.add_handler(CallbackQueryHandler(noop, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)
    log.info("%s bot starting", BRAND_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
