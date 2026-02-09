#!/usr/bin/env python3
"""
💰 GastosBot - Bot de Telegram para Control de Gastos Personales
================================================================
Registro rápido de gastos/ingresos desde Telegram con dashboard web.

Stack: python-telegram-bot + SQLite + FastAPI (dashboard)
Deploy: Docker en VPS
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════

DB_PATH = os.environ.get("DB_PATH", "/app/data/gastos.db")

def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('gasto', 'ingreso')),
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            payment_method TEXT DEFAULT 'Efectivo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '📌',
            type TEXT NOT NULL CHECK(type IN ('gasto', 'ingreso')),
            UNIQUE(user_id, name, type)
        );
        
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            monthly_limit REAL NOT NULL,
            UNIQUE(user_id, category)
        );
        
        CREATE INDEX IF NOT EXISTS idx_trans_user ON transactions(user_id);
        CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(created_at);
        CREATE INDEX IF NOT EXISTS idx_trans_type ON transactions(user_id, type);
    """)
    conn.close()

def seed_categories(user_id: int):
    """Insert default categories for a new user."""
    conn = get_db()
    default_gastos = [
        ("🏠 Vivienda", "🏠"), ("🍽️ Comida", "🍽️"), ("🚗 Transporte", "🚗"),
        ("💡 Servicios", "💡"), ("🏥 Salud", "🏥"), ("📚 Educación", "📚"),
        ("🎮 Entretenimiento", "🎮"), ("👔 Ropa", "👔"), ("💰 Ahorro", "💰"),
        ("🎁 Otros", "🎁"),
    ]
    default_ingresos = [
        ("💼 Salario", "💼"), ("💻 Freelance", "💻"), ("📈 Inversiones", "📈"),
        ("🏠 Rentas", "🏠"), ("🎁 Otros", "🎁"),
    ]
    for name, emoji in default_gastos:
        conn.execute(
            "INSERT OR IGNORE INTO categories (user_id, name, emoji, type) VALUES (?, ?, ?, 'gasto')",
            (user_id, name, emoji)
        )
    for name, emoji in default_ingresos:
        conn.execute(
            "INSERT OR IGNORE INTO categories (user_id, name, emoji, type) VALUES (?, ?, ?, 'ingreso')",
            (user_id, name, emoji)
        )
    conn.commit()
    conn.close()

# ══════════════════════════════════════════════
# QUERIES
# ══════════════════════════════════════════════

def add_transaction(user_id, tx_type, category, amount, description="", payment_method="Efectivo"):
    conn = get_db()
    conn.execute(
        "INSERT INTO transactions (user_id, type, category, amount, description, payment_method) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, tx_type, category, amount, description, payment_method)
    )
    conn.commit()
    conn.close()

def get_summary(user_id, days=30):
    conn = get_db()
    since = (datetime.now() - timedelta(days=days)).isoformat()
    
    totals = conn.execute("""
        SELECT type, SUM(amount) as total
        FROM transactions 
        WHERE user_id = ? AND created_at >= ?
        GROUP BY type
    """, (user_id, since)).fetchall()
    
    by_category = conn.execute("""
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM transactions 
        WHERE user_id = ? AND type = 'gasto' AND created_at >= ?
        GROUP BY category
        ORDER BY total DESC
    """, (user_id, since)).fetchall()
    
    conn.close()
    return totals, by_category

def get_recent(user_id, limit=10):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM transactions 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return rows

def get_today_total(user_id):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions 
        WHERE user_id = ? AND type = 'gasto' AND DATE(created_at) = ?
    """, (user_id, today)).fetchone()
    conn.close()
    return row["total"]

def get_month_summary(user_id):
    conn = get_db()
    now = datetime.now()
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    
    row = conn.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN type='ingreso' THEN amount ELSE 0 END), 0) as ingresos,
            COALESCE(SUM(CASE WHEN type='gasto' THEN amount ELSE 0 END), 0) as gastos
        FROM transactions 
        WHERE user_id = ? AND created_at >= ?
    """, (user_id, month_start)).fetchone()
    conn.close()
    return row["ingresos"], row["gastos"]

def delete_last_transaction(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, category, amount FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
        conn.commit()
    conn.close()
    return row

def get_categories(user_id, tx_type):
    conn = get_db()
    rows = conn.execute(
        "SELECT name, emoji FROM categories WHERE user_id = ? AND type = ? ORDER BY name",
        (user_id, tx_type)
    ).fetchall()
    conn.close()
    return rows

# ══════════════════════════════════════════════
# TELEGRAM BOT
# ══════════════════════════════════════════════

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, filters, ContextTypes
)

# Conversation states
AMOUNT, DESCRIPTION, PAYMENT = range(3)

# Authorized users (set your Telegram user ID)
AUTHORIZED_USERS = set(
    int(uid.strip()) 
    for uid in os.environ.get("AUTHORIZED_USERS", "").split(",") 
    if uid.strip()
)

def auth_check(func):
    """Decorator to restrict bot to authorized users only."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if AUTHORIZED_USERS and user_id not in AUTHORIZED_USERS:
            await update.message.reply_text("⛔ No estás autorizado para usar este bot.")
            return
        return await func(update, context)
    return wrapper

# ── Commands ──

@auth_check
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    seed_categories(user_id)
    
    today_total = get_today_total(user_id)
    ingresos, gastos = get_month_summary(user_id)
    balance = ingresos - gastos
    
    text = (
        f"👋 ¡Hola {update.effective_user.first_name}!\n\n"
        f"💰 *GastosBot* — Tu control financiero personal\n\n"
        f"📊 *Resumen del mes:*\n"
        f"   Ingresos: ${ingresos:,.2f}\n"
        f"   Gastos: ${gastos:,.2f}\n"
        f"   Balance: ${balance:,.2f}\n"
        f"   Hoy: ${today_total:,.2f} gastados\n\n"
        f"⚡ *Registro rápido:*\n"
        f"   Escribe el monto directamente: `150`\n"
        f"   O con descripción: `150 uber`\n\n"
        f"📋 *Comandos:*\n"
        f"/gasto — Registrar un gasto\n"
        f"/ingreso — Registrar un ingreso\n"
        f"/resumen — Ver resumen del mes\n"
        f"/hoy — Gastos de hoy\n"
        f"/recientes — Últimos 10 movimientos\n"
        f"/borrar — Eliminar último registro\n"
        f"/help — Ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    categories = get_categories(user_id, "gasto")
    
    keyboard = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(cat["name"], callback_data=f"cat_gasto|{cat['name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    
    await update.message.reply_text(
        "💸 *Registrar Gasto*\n\nSelecciona la categoría:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return AMOUNT

@auth_check
async def cmd_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    categories = get_categories(user_id, "ingreso")
    
    keyboard = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(cat["name"], callback_data=f"cat_ingreso|{cat['name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    
    await update.message.reply_text(
        "💰 *Registrar Ingreso*\n\nSelecciona la categoría:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return AMOUNT

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "cancel":
        await query.edit_message_text("❌ Cancelado")
        return ConversationHandler.END
    
    tx_type, category = data.split("|", 1)
    tx_type = tx_type.replace("cat_", "")
    
    context.user_data["tx_type"] = tx_type
    context.user_data["category"] = category
    
    emoji = "💸" if tx_type == "gasto" else "💰"
    await query.edit_message_text(
        f"{emoji} *{category}*\n\n💵 Escribe el monto:",
        parse_mode="Markdown"
    )
    return AMOUNT

async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace("$", "")
    
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Monto inválido. Escribe un número positivo:")
        return AMOUNT
    
    context.user_data["amount"] = amount
    
    keyboard = [
        [
            InlineKeyboardButton("💵 Efectivo", callback_data="pay|Efectivo"),
            InlineKeyboardButton("💳 Yape", callback_data="pay|Yape"),
        ],
        [
            InlineKeyboardButton("🏦 BCP", callback_data="pay|BCP"),
            InlineKeyboardButton("💳 Tarjeta", callback_data="pay|Tarjeta"),
        ],
        [
            InlineKeyboardButton("📲 Plin", callback_data="pay|Plin"),
            InlineKeyboardButton("🔄 Transfer.", callback_data="pay|Transferencia"),
        ],
        [InlineKeyboardButton("⏭️ Saltar", callback_data="pay|No especificado")],
    ]
    
    await update.message.reply_text(
        f"💵 Monto: *${amount:,.2f}*\n\n💳 Método de pago:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PAYMENT

async def payment_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    payment = query.data.split("|")[1]
    context.user_data["payment_method"] = payment
    
    await query.edit_message_text(
        f"📝 ¿Descripción? (o escribe *no* para omitir)",
        parse_mode="Markdown"
    )
    return DESCRIPTION

async def description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc.lower() in ("no", "n", "-", "skip", "omitir"):
        desc = ""
    
    user_id = update.effective_user.id
    tx_type = context.user_data["tx_type"]
    category = context.user_data["category"]
    amount = context.user_data["amount"]
    payment = context.user_data.get("payment_method", "Efectivo")
    
    add_transaction(user_id, tx_type, category, amount, desc, payment)
    
    today_total = get_today_total(user_id)
    emoji = "💸" if tx_type == "gasto" else "💰"
    tipo_label = "Gasto" if tx_type == "gasto" else "Ingreso"
    
    text = (
        f"✅ *{tipo_label} registrado*\n\n"
        f"{emoji} {category}\n"
        f"💵 ${amount:,.2f}\n"
        f"💳 {payment}\n"
    )
    if desc:
        text += f"📝 {desc}\n"
    
    if tx_type == "gasto":
        text += f"\n📊 Total hoy: ${today_total:,.2f}"
    
    await update.message.reply_text(text, parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END

# ── Quick registration (just send a number) ──

@auth_check
async def quick_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain number messages as quick expense registration."""
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    
    try:
        amount = float(parts[0].replace(",", "").replace("$", ""))
        if amount <= 0:
            return  # Ignore
    except (ValueError, IndexError):
        return
    
    desc = parts[1] if len(parts) > 1 else ""
    user_id = update.effective_user.id
    
    # Show category selection for quick expense
    categories = get_categories(user_id, "gasto")
    if not categories:
        seed_categories(user_id)
        categories = get_categories(user_id, "gasto")
    
    context.user_data["amount"] = amount
    context.user_data["tx_type"] = "gasto"
    context.user_data["quick_desc"] = desc
    
    keyboard = []
    row = []
    for cat in categories:
        callback = f"quick|{cat['name']}"
        row.append(InlineKeyboardButton(cat["name"], callback_data=callback))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    desc_text = f"\n📝 {desc}" if desc else ""
    await update.message.reply_text(
        f"⚡ *Gasto rápido: ${amount:,.2f}*{desc_text}\n\nSelecciona categoría:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def quick_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = query.data.split("|", 1)[1]
    user_id = query.from_user.id
    amount = context.user_data.get("amount", 0)
    desc = context.user_data.get("quick_desc", "")
    
    # Show payment method
    context.user_data["category"] = category
    
    keyboard = [
        [
            InlineKeyboardButton("💵 Efectivo", callback_data="qpay|Efectivo"),
            InlineKeyboardButton("💳 Yape", callback_data="qpay|Yape"),
        ],
        [
            InlineKeyboardButton("🏦 BCP", callback_data="qpay|BCP"),
            InlineKeyboardButton("💳 Tarjeta", callback_data="qpay|Tarjeta"),
        ],
        [InlineKeyboardButton("⏭️ Sin especificar", callback_data="qpay|No especificado")],
    ]
    
    await query.edit_message_text(
        f"⚡ *${amount:,.2f}* → {category}\n\n💳 Método de pago:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def quick_payment_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    payment = query.data.split("|")[1]
    user_id = query.from_user.id
    amount = context.user_data.get("amount", 0)
    category = context.user_data.get("category", "🎁 Otros")
    desc = context.user_data.get("quick_desc", "")
    
    add_transaction(user_id, "gasto", category, amount, desc, payment)
    today_total = get_today_total(user_id)
    
    text = (
        f"✅ *Gasto registrado*\n\n"
        f"💸 {category}\n"
        f"💵 ${amount:,.2f}\n"
        f"💳 {payment}\n"
    )
    if desc:
        text += f"📝 {desc}\n"
    text += f"\n📊 Total hoy: ${today_total:,.2f}"
    
    await query.edit_message_text(text, parse_mode="Markdown")
    context.user_data.clear()

# ── Info commands ──

@auth_check
async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ingresos, gastos = get_month_summary(user_id)
    balance = ingresos - gastos
    ahorro_pct = (balance / ingresos * 100) if ingresos > 0 else 0
    
    totals, by_category = get_summary(user_id, days=30)
    
    bar_max = max((row["total"] for row in by_category), default=1)
    
    text = (
        f"📊 *Resumen del Mes*\n"
        f"{'─' * 28}\n\n"
        f"💰 Ingresos:  ${ingresos:>12,.2f}\n"
        f"💸 Gastos:    ${gastos:>12,.2f}\n"
        f"{'─' * 28}\n"
        f"📊 Balance:   ${balance:>12,.2f}\n"
        f"📈 Ahorro:    {ahorro_pct:.1f}%\n\n"
    )
    
    if by_category:
        text += "*Gastos por categoría:*\n"
        for row in by_category:
            bar_len = int((row["total"] / bar_max) * 8) if bar_max > 0 else 0
            bar = "█" * bar_len + "░" * (8 - bar_len)
            pct = (row["total"] / gastos * 100) if gastos > 0 else 0
            text += f"`{bar}` {row['category']}\n  ${row['total']:,.2f} ({pct:.0f}%)\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    rows = conn.execute("""
        SELECT category, amount, description, payment_method, created_at
        FROM transactions 
        WHERE user_id = ? AND type = 'gasto' AND DATE(created_at) = ?
        ORDER BY created_at DESC
    """, (user_id, today)).fetchall()
    conn.close()
    
    total = sum(r["amount"] for r in rows)
    
    text = f"📅 *Gastos de Hoy*\n{'─' * 28}\n\n"
    
    if not rows:
        text += "🎉 ¡No has gastado nada hoy!\n"
    else:
        for r in rows:
            desc = f" — {r['description']}" if r["description"] else ""
            text += f"• {r['category']} → ${r['amount']:,.2f}{desc}\n"
        text += f"\n{'─' * 28}\n💸 *Total: ${total:,.2f}*"
    
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_recientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = get_recent(user_id, 10)
    
    text = f"🕐 *Últimos Movimientos*\n{'─' * 28}\n\n"
    
    if not rows:
        text += "No hay movimientos registrados.\n"
    else:
        for r in rows:
            emoji = "💸" if r["type"] == "gasto" else "💰"
            dt = datetime.fromisoformat(r["created_at"]).strftime("%d/%m %H:%M")
            desc = f" — {r['description']}" if r["description"] else ""
            text += f"{emoji} `{dt}` {r['category']}\n   ${r['amount']:,.2f} ({r['payment_method']}){desc}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    deleted = delete_last_transaction(user_id)
    
    if deleted:
        await update.message.reply_text(
            f"🗑️ *Eliminado:* {deleted['category']} → ${deleted['amount']:,.2f}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("No hay registros para eliminar.")

@auth_check
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Guía de GastosBot*\n\n"
        "⚡ *Registro Rápido:*\n"
        "Escribe solo el monto y te pido la categoría:\n"
        "  `150` → selecciona categoría → listo\n"
        "  `85 almuerzo` → con descripción\n\n"
        "📋 *Comandos:*\n"
        "/gasto — Registro paso a paso\n"
        "/ingreso — Registrar ingreso\n"
        "/resumen — Resumen mensual con gráficas\n"
        "/hoy — Gastos del día\n"
        "/recientes — Últimos 10 movimientos\n"
        "/borrar — Eliminar último registro\n\n"
        "💡 *Tips:*\n"
        "• Los métodos de pago incluyen Yape, BCP, Plin\n"
        "• El bot solo responde a usuarios autorizados\n"
        "• Los datos se guardan en tu propio servidor"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ── Cancel handler ──

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Cancelado")
    else:
        await update.message.reply_text("❌ Cancelado")
    return ConversationHandler.END

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

def main():
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        print("❌ ERROR: Set TELEGRAM_BOT_TOKEN environment variable")
        return
    
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler for /gasto
    gasto_handler = ConversationHandler(
        entry_points=[CommandHandler("gasto", cmd_gasto)],
        states={
            AMOUNT: [
                CallbackQueryHandler(category_selected, pattern=r"^cat_"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received),
            ],
            PAYMENT: [
                CallbackQueryHandler(payment_selected, pattern=r"^pay\|"),
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, description_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Conversation handler for /ingreso
    ingreso_handler = ConversationHandler(
        entry_points=[CommandHandler("ingreso", cmd_ingreso)],
        states={
            AMOUNT: [
                CallbackQueryHandler(category_selected, pattern=r"^cat_"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received),
            ],
            PAYMENT: [
                CallbackQueryHandler(payment_selected, pattern=r"^pay\|"),
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, description_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("recientes", cmd_recientes))
    app.add_handler(CommandHandler("borrar", cmd_borrar))
    app.add_handler(gasto_handler)
    app.add_handler(ingreso_handler)
    
    # Quick expense callbacks
    app.add_handler(CallbackQueryHandler(quick_category_selected, pattern=r"^quick\|"))
    app.add_handler(CallbackQueryHandler(quick_payment_selected, pattern=r"^qpay\|"))
    
    # Quick expense: any plain number message
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, quick_expense))
    
    print("🤖 GastosBot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
