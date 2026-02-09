#!/usr/bin/env python3
"""
💰 GastosBot — Bot de Telegram para Control de Gastos Personales
================================================================
Registro rápido de gastos/ingresos desde Telegram.
Moneda: Soles (S/). Soporte de fotos, gastos fijos y recurrentes.

Stack: python-telegram-bot + SQLite
Deploy: Docker en VPS
"""

import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════

import sheets_sync

DB_PATH = os.environ.get("DB_PATH", "/app/data/gastos.db")
PHOTOS_DIR = os.environ.get("PHOTOS_DIR", "/app/data/photos")
CURRENCY = "S/"

AUTHORIZED_USERS = set(
    int(uid.strip())
    for uid in os.environ.get("AUTHORIZED_USERS", "").split(",")
    if uid.strip()
)

# ══════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════

def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    Path(PHOTOS_DIR).mkdir(parents=True, exist_ok=True)
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
            photo_path TEXT,
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

        CREATE TABLE IF NOT EXISTS recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('gasto', 'ingreso')),
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            payment_method TEXT DEFAULT 'Transferencia',
            day_of_month INTEGER NOT NULL DEFAULT 1,
            active INTEGER DEFAULT 1,
            last_applied TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_trans_user ON transactions(user_id);
        CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(created_at);
        CREATE INDEX IF NOT EXISTS idx_trans_type ON transactions(user_id, type);
        CREATE INDEX IF NOT EXISTS idx_recurring_user ON recurring(user_id);
    """)
    conn.close()

def seed_categories(user_id: int):
    conn = get_db()
    default_gastos = [
        ("🏠 Vivienda", "🏠"), ("🍽️ Comida", "🍽️"), ("🚗 Transporte", "🚗"),
        ("💡 Servicios", "💡"), ("🏥 Salud", "🏥"), ("📚 Educación", "📚"),
        ("🎮 Entretenimiento", "🎮"), ("👔 Ropa", "👔"), ("💰 Ahorro", "💰"),
        ("🎁 Otros", "🎁"),
    ]
    default_ingresos = [
        ("💼 Salario", "💼"), ("💻 Freelance", "💻"), ("📈 Inversiones", "📈"),
        ("🏠 Rentas", "🏠"), ("🎁 Otros ingresos", "🎁"),
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

def add_transaction(user_id, tx_type, category, amount, description="", payment_method="Efectivo", photo_path=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO transactions (user_id, type, category, amount, description, payment_method, photo_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, tx_type, category, amount, description, payment_method, photo_path)
    )
    conn.commit()
    conn.close()
    # Sync to Google Sheets
    if sheets_sync.is_enabled():
        sheets_sync.sync_transaction(tx_type, category, amount, description, payment_method)

def get_today_total(user_id):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = ? AND type = 'gasto' AND DATE(created_at) = ?",
        (user_id, today)
    ).fetchone()
    conn.close()
    return row["total"]

def get_month_summary(user_id):
    conn = get_db()
    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN type='ingreso' THEN amount ELSE 0 END), 0) as ingresos,
            COALESCE(SUM(CASE WHEN type='gasto' THEN amount ELSE 0 END), 0) as gastos
        FROM transactions WHERE user_id = ? AND created_at >= ?
    """, (user_id, month_start)).fetchone()
    conn.close()
    return row["ingresos"], row["gastos"]

def get_summary_by_category(user_id, days=30):
    conn = get_db()
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM transactions
        WHERE user_id = ? AND type = 'gasto' AND created_at >= ?
        GROUP BY category ORDER BY total DESC
    """, (user_id, since)).fetchall()
    conn.close()
    return rows

def get_recent(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return rows

def delete_last_transaction(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, category, amount, photo_path FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
        conn.commit()
        if row["photo_path"] and os.path.exists(row["photo_path"]):
            os.remove(row["photo_path"])
        # Sync delete to Google Sheets
        if sheets_sync.is_enabled():
            sheets_sync.sync_delete_last()
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

# ── Recurring ──

def add_recurring(user_id, tx_type, category, amount, description, payment_method, day_of_month):
    conn = get_db()
    conn.execute(
        "INSERT INTO recurring (user_id, type, category, amount, description, payment_method, day_of_month) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, tx_type, category, amount, description, payment_method, day_of_month)
    )
    conn.commit()
    conn.close()

def get_recurring(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM recurring WHERE user_id = ? AND active = 1 ORDER BY day_of_month",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows

def delete_recurring(recurring_id, user_id):
    conn = get_db()
    conn.execute("UPDATE recurring SET active = 0 WHERE id = ? AND user_id = ?", (recurring_id, user_id))
    conn.commit()
    conn.close()

def apply_recurring_transactions():
    """Check and apply recurring transactions for today."""
    conn = get_db()
    today = datetime.now()
    day = today.day
    month_key = today.strftime("%Y-%m")

    rows = conn.execute(
        "SELECT * FROM recurring WHERE active = 1 AND day_of_month = ? AND (last_applied IS NULL OR last_applied != ?)",
        (day, month_key)
    ).fetchall()

    applied = []
    for r in rows:
        conn.execute(
            "INSERT INTO transactions (user_id, type, category, amount, description, payment_method) VALUES (?, ?, ?, ?, ?, ?)",
            (r["user_id"], r["type"], r["category"], r["amount"],
             f"[Auto] {r['description'] or ''}", r["payment_method"])
        )
        conn.execute("UPDATE recurring SET last_applied = ? WHERE id = ?", (month_key, r["id"]))
        applied.append(r)

    conn.commit()
    conn.close()
    return applied

# ══════════════════════════════════════════════
# TELEGRAM BOT
# ══════════════════════════════════════════════

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)

# States
AMOUNT, DESCRIPTION, PAYMENT, PHOTO_WAIT = range(4)
REC_TYPE, REC_CAT, REC_AMOUNT, REC_DESC, REC_DAY, REC_PAY = range(10, 16)

def auth_check(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if AUTHORIZED_USERS and uid not in AUTHORIZED_USERS:
            await update.effective_message.reply_text("⛔ No autorizado.")
            return
        return await func(update, context)
    return wrapper

def fmt(amount):
    """Format amount in Soles."""
    return f"{CURRENCY}{amount:,.2f}"

# ── /start ──

@auth_check
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    seed_categories(uid)
    today_total = get_today_total(uid)
    ingresos, gastos = get_month_summary(uid)
    balance = ingresos - gastos

    sheets_status = "✅ Google Sheets conectado" if sheets_sync.is_enabled() else "⚠️ Google Sheets no configurado"

    text = (
        f"👋 ¡Hola {update.effective_user.first_name}!\n\n"
        f"💰 *GastosBot* — Tu control financiero\n\n"
        f"📊 *Resumen del mes:*\n"
        f"   Ingresos: {fmt(ingresos)}\n"
        f"   Gastos:   {fmt(gastos)}\n"
        f"   Balance:  {fmt(balance)}\n"
        f"   Hoy:      {fmt(today_total)} gastados\n\n"
        f"📋 {sheets_status}\n\n"
        f"⚡ *Registro rápido:*\n"
        f"   Escribe el monto: `45`\n"
        f"   Con detalle: `45 almuerzo`\n"
        f"   📸 Envía una foto de tu boleta\n\n"
        f"📋 /help para ver todos los comandos"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ── /help ──

@auth_check
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Guía de GastosBot*\n\n"
        "⚡ *Registro Rápido:*\n"
        "  `45` → categoría → pago → ✅\n"
        "  `85 almuerzo` → con descripción\n"
        "  📸 Foto + monto en caption\n\n"
        "📋 *Comandos principales:*\n"
        "/gasto — Registrar gasto paso a paso\n"
        "/ingreso — Registrar ingreso\n"
        "/resumen — Resumen mensual\n"
        "/hoy — Gastos del día\n"
        "/recientes — Últimos 10 movimientos\n"
        "/borrar — Eliminar último registro\n\n"
        "🔄 *Recurrentes (fijos):*\n"
        "/fijo — Agregar gasto/ingreso fijo\n"
        "/fijos — Ver todos los fijos activos\n"
        "/quitarfijo — Desactivar un fijo\n\n"
        "💡 *Tips:*\n"
        "• Envía 📸 foto de boleta para guardarla\n"
        "• Los fijos se registran automáticamente\n"
        "• Métodos: Yape, BCP, Plin, Efectivo, etc."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ══════════════════════════════════════════════
# EXPENSE/INCOME REGISTRATION (step by step)
# ══════════════════════════════════════════════

def category_keyboard(categories, prefix):
    keyboard = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(cat["name"], callback_data=f"{prefix}|{cat['name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)

def payment_keyboard(prefix="pay"):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💵 Efectivo", callback_data=f"{prefix}|Efectivo"),
            InlineKeyboardButton("📱 Yape", callback_data=f"{prefix}|Yape"),
        ],
        [
            InlineKeyboardButton("🏦 BCP", callback_data=f"{prefix}|BCP"),
            InlineKeyboardButton("📲 Plin", callback_data=f"{prefix}|Plin"),
        ],
        [
            InlineKeyboardButton("💳 Tarjeta", callback_data=f"{prefix}|Tarjeta"),
            InlineKeyboardButton("🔄 Transfer.", callback_data=f"{prefix}|Transferencia"),
        ],
        [InlineKeyboardButton("⏭️ Saltar", callback_data=f"{prefix}|No especificado")],
    ])

@auth_check
async def cmd_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cats = get_categories(uid, "gasto")
    if not cats:
        seed_categories(uid)
        cats = get_categories(uid, "gasto")
    await update.message.reply_text(
        "💸 *Registrar Gasto*\n\nSelecciona categoría:",
        reply_markup=category_keyboard(cats, "cat_gasto"),
        parse_mode="Markdown"
    )
    return AMOUNT

@auth_check
async def cmd_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cats = get_categories(uid, "ingreso")
    if not cats:
        seed_categories(uid)
        cats = get_categories(uid, "ingreso")
    await update.message.reply_text(
        "💰 *Registrar Ingreso*\n\nSelecciona categoría:",
        reply_markup=category_keyboard(cats, "cat_ingreso"),
        parse_mode="Markdown"
    )
    return AMOUNT

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelado")
        return ConversationHandler.END

    tx_type, category = query.data.split("|", 1)
    tx_type = tx_type.replace("cat_", "")
    context.user_data["tx_type"] = tx_type
    context.user_data["category"] = category

    emoji = "💸" if tx_type == "gasto" else "💰"
    await query.edit_message_text(
        f"{emoji} *{category}*\n\n💵 Escribe el monto en soles:",
        parse_mode="Markdown"
    )
    return AMOUNT

async def amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace("S/", "").replace("s/", "").replace("$", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Monto inválido. Escribe un número:")
        return AMOUNT

    context.user_data["amount"] = amount
    await update.message.reply_text(
        f"💵 Monto: *{fmt(amount)}*\n\n💳 Método de pago:",
        reply_markup=payment_keyboard("pay"),
        parse_mode="Markdown"
    )
    return PAYMENT

async def payment_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment = query.data.split("|")[1]
    context.user_data["payment_method"] = payment

    await query.edit_message_text(
        f"📝 ¿Descripción? (escribe *no* para omitir)\n📸 O envía una foto de la boleta",
        parse_mode="Markdown"
    )
    return DESCRIPTION

async def description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc.lower() in ("no", "n", "-", "skip", "omitir"):
        desc = ""
    return await _save_transaction(update, context, desc, None)

async def photo_in_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo sent during description step."""
    photo_path = await _save_photo(update)
    caption = update.message.caption or ""
    return await _save_transaction(update, context, caption, photo_path)

async def _save_transaction(update, context, description, photo_path):
    uid = update.effective_user.id
    tx_type = context.user_data.get("tx_type", "gasto")
    category = context.user_data.get("category", "🎁 Otros")
    amount = context.user_data.get("amount", 0)
    payment = context.user_data.get("payment_method", "Efectivo")

    add_transaction(uid, tx_type, category, amount, description, payment, photo_path)

    today_total = get_today_total(uid)
    emoji = "💸" if tx_type == "gasto" else "💰"
    tipo_label = "Gasto" if tx_type == "gasto" else "Ingreso"

    text = (
        f"✅ *{tipo_label} registrado*\n\n"
        f"{emoji} {category}\n"
        f"💵 {fmt(amount)}\n"
        f"💳 {payment}\n"
    )
    if description:
        text += f"📝 {description}\n"
    if photo_path:
        text += f"📸 Foto guardada\n"
    if tx_type == "gasto":
        text += f"\n📊 Total hoy: {fmt(today_total)}"
    if sheets_sync.is_enabled():
        text += f"\n📋 Sincronizado con Google Sheets"

    await update.effective_message.reply_text(text, parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════════════
# QUICK REGISTRATION (just send a number or photo)
# ══════════════════════════════════════════════

async def _save_photo(update: Update) -> str:
    """Download and save photo, return file path."""
    photo = update.message.photo[-1]  # Highest resolution
    file = await photo.get_file()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = update.effective_user.id
    filename = f"{uid}_{timestamp}.jpg"
    filepath = os.path.join(PHOTOS_DIR, filename)
    await file.download_to_drive(filepath)
    return filepath

@auth_check
async def quick_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Photo sent directly — save and ask for amount."""
    photo_path = await _save_photo(update)
    context.user_data["pending_photo"] = photo_path

    caption = update.message.caption or ""
    parts = caption.strip().split(maxsplit=1)

    # Try to parse amount from caption
    if parts:
        try:
            amount = float(parts[0].replace(",", "").replace("S/", "").replace("s/", ""))
            if amount > 0:
                context.user_data["amount"] = amount
                context.user_data["tx_type"] = "gasto"
                context.user_data["quick_desc"] = parts[1] if len(parts) > 1 else ""

                uid = update.effective_user.id
                cats = get_categories(uid, "gasto")
                if not cats:
                    seed_categories(uid)
                    cats = get_categories(uid, "gasto")

                keyboard = []
                row = []
                for cat in cats:
                    row.append(InlineKeyboardButton(cat["name"], callback_data=f"quick|{cat['name']}"))
                    if len(row) == 2:
                        keyboard.append(row)
                        row = []
                if row:
                    keyboard.append(row)

                await update.message.reply_text(
                    f"📸 Foto guardada\n⚡ *Gasto: {fmt(amount)}*\n\nSelecciona categoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return
        except (ValueError, IndexError):
            pass

    await update.message.reply_text(
        "📸 Foto guardada ✅\n\n💵 Escribe el monto para registrar el gasto:\n(o escribe `cancelar` para solo guardar la foto)",
        parse_mode="Markdown"
    )

@auth_check
async def quick_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain number messages as quick expense."""
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)

    try:
        amount = float(parts[0].replace(",", "").replace("S/", "").replace("s/", "").replace("$", ""))
        if amount <= 0:
            return
    except (ValueError, IndexError):
        # Check if there's a pending photo
        if "pending_photo" in context.user_data:
            if text.lower() in ("cancelar", "cancel", "no"):
                photo = context.user_data.pop("pending_photo", None)
                await update.message.reply_text("📸 Foto guardada sin registro de gasto.")
                return
            try:
                amount = float(text.replace(",", "").replace("S/", "").replace("s/", ""))
                if amount <= 0:
                    return
            except ValueError:
                return
        else:
            return

    desc = parts[1] if len(parts) > 1 else ""
    uid = update.effective_user.id
    context.user_data["amount"] = amount
    context.user_data["tx_type"] = "gasto"
    context.user_data["quick_desc"] = desc

    cats = get_categories(uid, "gasto")
    if not cats:
        seed_categories(uid)
        cats = get_categories(uid, "gasto")

    keyboard = []
    row = []
    for cat in cats:
        row.append(InlineKeyboardButton(cat["name"], callback_data=f"quick|{cat['name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    photo_note = "📸 + " if "pending_photo" in context.user_data else ""
    desc_text = f"\n📝 {desc}" if desc else ""
    await update.message.reply_text(
        f"⚡ {photo_note}*Gasto: {fmt(amount)}*{desc_text}\n\nCategoría:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def quick_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("|", 1)[1]
    context.user_data["category"] = category
    amount = context.user_data.get("amount", 0)

    await query.edit_message_text(
        f"⚡ *{fmt(amount)}* → {category}\n\n💳 Método de pago:",
        reply_markup=payment_keyboard("qpay"),
        parse_mode="Markdown"
    )

async def quick_payment_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payment = query.data.split("|")[1]
    uid = query.from_user.id
    amount = context.user_data.get("amount", 0)
    category = context.user_data.get("category", "🎁 Otros")
    desc = context.user_data.get("quick_desc", "")
    photo_path = context.user_data.pop("pending_photo", None)

    add_transaction(uid, "gasto", category, amount, desc, payment, photo_path)
    today_total = get_today_total(uid)

    text = (
        f"✅ *Gasto registrado*\n\n"
        f"💸 {category}\n"
        f"💵 {fmt(amount)}\n"
        f"💳 {payment}\n"
    )
    if desc:
        text += f"📝 {desc}\n"
    if photo_path:
        text += f"📸 Foto guardada\n"
    text += f"\n📊 Total hoy: {fmt(today_total)}"
    if sheets_sync.is_enabled():
        text += f"\n📋 Sincronizado con Google Sheets"

    await query.edit_message_text(text, parse_mode="Markdown")
    context.user_data.clear()

# ══════════════════════════════════════════════
# RECURRING / FIXED TRANSACTIONS
# ══════════════════════════════════════════════

@auth_check
async def cmd_fijo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 Gasto Fijo", callback_data="rec_type|gasto"),
            InlineKeyboardButton("💰 Ingreso Fijo", callback_data="rec_type|ingreso"),
        ],
        [InlineKeyboardButton("❌ Cancelar", callback_data="rec_cancel")],
    ])
    await update.message.reply_text(
        "🔄 *Nuevo Gasto/Ingreso Fijo*\n\n¿Qué tipo?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return REC_TYPE

async def rec_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "rec_cancel":
        await query.edit_message_text("❌ Cancelado")
        return ConversationHandler.END

    tx_type = query.data.split("|")[1]
    context.user_data["rec_type"] = tx_type
    uid = query.from_user.id

    cats = get_categories(uid, tx_type)
    if not cats:
        seed_categories(uid)
        cats = get_categories(uid, tx_type)

    keyboard = []
    row = []
    for cat in cats:
        row.append(InlineKeyboardButton(cat["name"], callback_data=f"rec_cat|{cat['name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    tipo_label = "Gasto" if tx_type == "gasto" else "Ingreso"
    await query.edit_message_text(
        f"🔄 *{tipo_label} Fijo*\n\nSelecciona categoría:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return REC_CAT

async def rec_cat_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split("|", 1)[1]
    context.user_data["rec_category"] = category

    await query.edit_message_text(
        f"🔄 *{category}*\n\n💵 Escribe el monto fijo mensual:",
        parse_mode="Markdown"
    )
    return REC_AMOUNT

async def rec_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace("S/", "").replace("s/", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Monto inválido:")
        return REC_AMOUNT

    context.user_data["rec_amount"] = amount
    await update.message.reply_text(
        f"💵 {fmt(amount)} mensual\n\n📝 Descripción (o *no* para omitir):",
        parse_mode="Markdown"
    )
    return REC_DESC

async def rec_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc.lower() in ("no", "n", "-", "skip"):
        desc = ""
    context.user_data["rec_desc"] = desc

    await update.message.reply_text(
        "📅 ¿Qué día del mes se cobra/paga? (1-28)\nEjemplo: `1` para el primero del mes",
        parse_mode="Markdown"
    )
    return REC_DAY

async def rec_day_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        day = int(update.message.text.strip())
        if day < 1 or day > 28:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Día inválido (1-28):")
        return REC_DAY

    context.user_data["rec_day"] = day
    await update.message.reply_text(
        f"📅 Día {day} de cada mes\n\n💳 Método de pago:",
        reply_markup=payment_keyboard("rec_pay"),
        parse_mode="Markdown"
    )
    return REC_PAY

async def rec_payment_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payment = query.data.split("|")[1]
    uid = query.from_user.id
    tx_type = context.user_data["rec_type"]
    category = context.user_data["rec_category"]
    amount = context.user_data["rec_amount"]
    desc = context.user_data.get("rec_desc", "")
    day = context.user_data["rec_day"]

    add_recurring(uid, tx_type, category, amount, desc, payment, day)

    tipo_label = "Gasto" if tx_type == "gasto" else "Ingreso"
    text = (
        f"✅ *{tipo_label} fijo registrado*\n\n"
        f"🔄 {category}\n"
        f"💵 {fmt(amount)} mensual\n"
        f"📅 Día {day} de cada mes\n"
        f"💳 {payment}\n"
    )
    if desc:
        text += f"📝 {desc}\n"
    text += f"\nSe registrará automáticamente cada mes."

    await query.edit_message_text(text, parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END

@auth_check
async def cmd_fijos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rows = get_recurring(uid)

    if not rows:
        await update.message.reply_text("No tienes gastos/ingresos fijos configurados.\nUsa /fijo para agregar uno.")
        return

    text = "🔄 *Gastos e Ingresos Fijos*\n" + "─" * 28 + "\n\n"

    total_gastos = 0
    total_ingresos = 0

    for r in rows:
        emoji = "💸" if r["type"] == "gasto" else "💰"
        desc = f" — {r['description']}" if r["description"] else ""
        text += f"{emoji} *#{r['id']}* {r['category']}\n   {fmt(r['amount'])} · Día {r['day_of_month']} · {r['payment_method']}{desc}\n\n"
        if r["type"] == "gasto":
            total_gastos += r["amount"]
        else:
            total_ingresos += r["amount"]

    text += f"{'─' * 28}\n"
    text += f"💰 Ingresos fijos: {fmt(total_ingresos)}/mes\n"
    text += f"💸 Gastos fijos: {fmt(total_gastos)}/mes\n"
    text += f"📊 Disponible: {fmt(total_ingresos - total_gastos)}/mes\n"
    text += f"\nUsa /quitarfijo para desactivar uno."

    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_quitarfijo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rows = get_recurring(uid)

    if not rows:
        await update.message.reply_text("No tienes fijos configurados.")
        return

    keyboard = []
    for r in rows:
        emoji = "💸" if r["type"] == "gasto" else "💰"
        label = f"{emoji} {r['category']} · {fmt(r['amount'])}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"del_rec|{r['id']}")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="del_rec|cancel")])

    await update.message.reply_text(
        "🗑️ *¿Cuál fijo quieres desactivar?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def delete_recurring_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")[1]
    if data == "cancel":
        await query.edit_message_text("❌ Cancelado")
        return

    uid = query.from_user.id
    delete_recurring(int(data), uid)
    await query.edit_message_text("✅ Fijo desactivado")

# ══════════════════════════════════════════════
# INFO COMMANDS
# ══════════════════════════════════════════════

@auth_check
async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ingresos, gastos = get_month_summary(uid)
    balance = ingresos - gastos
    ahorro_pct = (balance / ingresos * 100) if ingresos > 0 else 0
    by_category = get_summary_by_category(uid, days=30)

    bar_max = max((row["total"] for row in by_category), default=1)

    text = (
        f"📊 *Resumen del Mes*\n{'─' * 28}\n\n"
        f"💰 Ingresos:  {fmt(ingresos)}\n"
        f"💸 Gastos:    {fmt(gastos)}\n"
        f"{'─' * 28}\n"
        f"📊 Balance:   {fmt(balance)}\n"
        f"📈 Ahorro:    {ahorro_pct:.1f}%\n\n"
    )

    if by_category:
        text += "*Gastos por categoría:*\n"
        for row in by_category:
            bar_len = int((row["total"] / bar_max) * 8) if bar_max > 0 else 0
            bar = "█" * bar_len + "░" * (8 - bar_len)
            pct = (row["total"] / gastos * 100) if gastos > 0 else 0
            text += f"`{bar}` {row['category']}\n  {fmt(row['total'])} ({pct:.0f}%) · {row['count']} registros\n"

    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT category, amount, description, payment_method, photo_path
        FROM transactions
        WHERE user_id = ? AND type = 'gasto' AND DATE(created_at) = ?
        ORDER BY created_at DESC
    """, (uid, today)).fetchall()
    conn.close()

    total = sum(r["amount"] for r in rows)
    text = f"📅 *Gastos de Hoy*\n{'─' * 28}\n\n"

    if not rows:
        text += "🎉 ¡No has gastado nada hoy!"
    else:
        for r in rows:
            desc = f" — {r['description']}" if r["description"] else ""
            photo = " 📸" if r["photo_path"] else ""
            text += f"• {r['category']} → {fmt(r['amount'])}{desc}{photo}\n  _{r['payment_method']}_\n"
        text += f"\n{'─' * 28}\n💸 *Total: {fmt(total)}*"

    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_recientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rows = get_recent(uid, 10)

    text = f"🕐 *Últimos Movimientos*\n{'─' * 28}\n\n"

    if not rows:
        text += "No hay movimientos registrados."
    else:
        for r in rows:
            emoji = "💸" if r["type"] == "gasto" else "💰"
            dt = datetime.fromisoformat(r["created_at"]).strftime("%d/%m %H:%M")
            desc = f" — {r['description']}" if r["description"] else ""
            photo = " 📸" if r["photo_path"] else ""
            text += f"{emoji} `{dt}` {r['category']}\n   {fmt(r['amount'])} · {r['payment_method']}{desc}{photo}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")

@auth_check
async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    deleted = delete_last_transaction(uid)
    if deleted:
        await update.message.reply_text(
            f"🗑️ *Eliminado:* {deleted['category']} → {fmt(deleted['amount'])}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("No hay registros para eliminar.")

# ══════════════════════════════════════════════
# RECURRING JOB (runs daily)
# ══════════════════════════════════════════════

async def daily_recurring_job(context: ContextTypes.DEFAULT_TYPE):
    """Apply recurring transactions and notify users."""
    applied = apply_recurring_transactions()
    # Group by user
    by_user = {}
    for r in applied:
        by_user.setdefault(r["user_id"], []).append(r)

    for uid, items in by_user.items():
        text = "🔄 *Registros automáticos de hoy:*\n\n"
        for r in items:
            emoji = "💸" if r["type"] == "gasto" else "💰"
            text += f"{emoji} {r['category']} → {fmt(r['amount'])}\n"
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
        except Exception:
            pass

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        print("❌ Set TELEGRAM_BOT_TOKEN")
        return

    init_db()

    # Setup Google Sheets
    if sheets_sync.is_enabled():
        if sheets_sync.setup_sheet_headers():
            print("📋 Google Sheets connected")
        else:
            print("⚠️ Google Sheets configured but failed to connect")
    else:
        print("ℹ️ Google Sheets not configured (optional)")

    app = Application.builder().token(TOKEN).build()

    # ── Conversation: /gasto ──
    gasto_conv = ConversationHandler(
        entry_points=[CommandHandler("gasto", cmd_gasto)],
        per_message=False,
        states={
            AMOUNT: [
                CallbackQueryHandler(category_selected, pattern=r"^cat_"),
                CallbackQueryHandler(cancel_conversation, pattern=r"^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received),
            ],
            PAYMENT: [CallbackQueryHandler(payment_selected, pattern=r"^pay\|")],
            DESCRIPTION: [
                MessageHandler(filters.PHOTO, photo_in_conversation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, description_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    # ── Conversation: /ingreso ──
    ingreso_conv = ConversationHandler(
        entry_points=[CommandHandler("ingreso", cmd_ingreso)],
        per_message=False,
        states={
            AMOUNT: [
                CallbackQueryHandler(category_selected, pattern=r"^cat_"),
                CallbackQueryHandler(cancel_conversation, pattern=r"^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, amount_received),
            ],
            PAYMENT: [CallbackQueryHandler(payment_selected, pattern=r"^pay\|")],
            DESCRIPTION: [
                MessageHandler(filters.PHOTO, photo_in_conversation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, description_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    # ── Conversation: /fijo ──
    fijo_conv = ConversationHandler(
        entry_points=[CommandHandler("fijo", cmd_fijo)],
        per_message=False,
        states={
            REC_TYPE: [
                CallbackQueryHandler(rec_type_selected, pattern=r"^rec_type\|"),
                CallbackQueryHandler(cancel_conversation, pattern=r"^rec_cancel$"),
            ],
            REC_CAT: [CallbackQueryHandler(rec_cat_selected, pattern=r"^rec_cat\|")],
            REC_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rec_amount_received)],
            REC_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, rec_desc_received)],
            REC_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, rec_day_received)],
            REC_PAY: [CallbackQueryHandler(rec_payment_selected, pattern=r"^rec_pay\|")],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("recientes", cmd_recientes))
    app.add_handler(CommandHandler("borrar", cmd_borrar))
    app.add_handler(CommandHandler("fijos", cmd_fijos))
    app.add_handler(CommandHandler("quitarfijo", cmd_quitarfijo))

    app.add_handler(gasto_conv)
    app.add_handler(ingreso_conv)
    app.add_handler(fijo_conv)

    # Callback handlers for quick flow and delete recurring
    app.add_handler(CallbackQueryHandler(quick_category_selected, pattern=r"^quick\|"))
    app.add_handler(CallbackQueryHandler(quick_payment_selected, pattern=r"^qpay\|"))
    app.add_handler(CallbackQueryHandler(delete_recurring_handler, pattern=r"^del_rec\|"))

    # Photo handler (quick flow)
    app.add_handler(MessageHandler(filters.PHOTO, quick_photo))

    # Quick expense: plain number
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, quick_expense))

    # Daily job for recurring transactions (runs at 8:00 AM Lima time = 13:00 UTC)
    job_queue = app.job_queue
    if job_queue:
        from datetime import time as dt_time
        job_queue.run_daily(daily_recurring_job, time=dt_time(hour=13, minute=0, second=0))

    print("🤖 GastosBot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
