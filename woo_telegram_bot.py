"""
Telegram Bot - WooCommerce Auto Order
======================================
Cara pakai:
    Isi Environment Variables di Railway:
        TELEGRAM_TOKEN  = token dari BotFather
        WC_URL          = https://tokokamu.com
        WC_KEY          = ck_xxx...
        WC_SECRET       = cs_xxx...
        ALLOWED_USERS   = 123456789  (Telegram user ID kamu)

Format perintah di Telegram:
        Order: RapidGator 1 Minggu
        Email: customer@gmail.com
        Notes:
        Email: user@example.com
        Password: abc123
        Login: https://rapidgator.net
"""

import os
import logging
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ============================================================
# KONFIGURASI — diambil dari environment variables Railway
# ============================================================
TELEGRAM_TOKEN = os.environ.get("8766843552:AAEwptX0X3TWJHSkZ-Xm_R_n-3nGNyyjpkg", "")
WC_URL         = os.environ.get("https://premixstore.com", "").rstrip("/")
WC_KEY         = os.environ.get("ck_c5f5ea7bf235bef6502b75e9b22367145647291b", "")
WC_SECRET      = os.environ.get("cs_b6feb65c406644104916e58cfe3c0870c653107e", "")

_allowed      = os.environ.get("6058576490", "")
ALLOWED_USERS = [int(x.strip()) for x in _allowed.split(",") if x.strip().isdigit()]

# Mapping nama produk (huruf kecil) → WooCommerce Product ID
# Sesuaikan dengan produk di toko kamu!
PRODUCT_MAP = {
    "rapidgator 1 minggu" : 101,
    "rapidgator 1 bulan"  : 102,
    "rapidgator 3 bulan"  : 103,
    "rapidgator 6 bulan"  : 104,
    "rapidgator 1 tahun"  : 105,
}
# ============================================================

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


# ── Parser ───────────────────────────────────────────────────

def parse_perintah(text: str) -> dict | None:
    """
    Parse format:
        Order: <produk>
        Email: <email customer>
        Notes:
        <baris bebas multiline>
    """
    lines  = text.strip().splitlines()
    result = {"order": None, "email": None, "notes": []}
    mode   = None

    for line in lines:
        stripped = line.strip()
        lower    = stripped.lower()

        if lower.startswith("order:"):
            result["order"] = stripped.split(":", 1)[1].strip()
            mode = "order"
        elif lower.startswith("email:") and result["email"] is None:
            result["email"] = stripped.split(":", 1)[1].strip()
            mode = "email"
        elif lower.startswith("notes:"):
            after = stripped.split(":", 1)[1].strip()
            if after:
                result["notes"].append(after)
            mode = "notes"
        elif mode == "notes" and stripped:
            result["notes"].append(stripped)

    result["notes_text"] = "\n".join(result["notes"]).strip()

    if result["order"] and result["email"]:
        return result
    return None


# ── WooCommerce ──────────────────────────────────────────────

def cari_product_id(nama_produk: str) -> int | None:
    """Cari product ID dari PRODUCT_MAP, fallback ke WooCommerce API."""
    key = nama_produk.lower().strip()

    if key in PRODUCT_MAP:
        return PRODUCT_MAP[key]

    try:
        r = requests.get(
            f"{WC_URL}/wp-json/wc/v3/products",
            params={"search": nama_produk, "per_page": 5},
            auth=(WC_KEY, WC_SECRET),
            timeout=10,
        )
        products = r.json()
        if isinstance(products, list) and products:
            log.info(f"Produk ditemukan via API: {products[0]['name']} (ID: {products[0]['id']})")
            return products[0]["id"]
    except Exception as e:
        log.error(f"Error saat cari produk: {e}")

    return None


def buat_order(product_id: int, email: str, notes: str) -> dict:
    """Buat order di WooCommerce lalu kirim customer note via email."""
    payload = {
        "payment_method"      : "bacs",
        "payment_method_title": "Transfer Bank",
        "set_paid"            : True,
        "status"              : "processing",
        "billing": {
            "first_name": email.split("@")[0],
            "last_name" : "",
            "email"     : email,
        },
        "line_items": [
            {"product_id": product_id, "quantity": 1}
        ],
    }

    r = requests.post(
        f"{WC_URL}/wp-json/wc/v3/orders",
        json=payload,
        auth=(WC_KEY, WC_SECRET),
        timeout=15,
    )
    order = r.json()

    if "id" not in order:
        raise Exception(f"Gagal buat order: {order}")

    order_id = order["id"]
    log.info(f"Order #{order_id} berhasil dibuat untuk {email}")

    # Kirim order note ke customer (customer_note=True → email otomatis terkirim)
    if notes:
        note_r = requests.post(
            f"{WC_URL}/wp-json/wc/v3/orders/{order_id}/notes",
            json={"note": notes, "customer_note": True},
            auth=(WC_KEY, WC_SECRET),
            timeout=10,
        )
        log.info(f"Order note dikirim, status: {note_r.status_code}")

    return order


# ── Telegram Handlers ─────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Halo! Saya bot order otomatis WooCommerce.</b>\n\n"
        "Kirim perintah dengan format berikut:\n\n"
        "<code>"
        "Order: RapidGator 1 Minggu\n"
        "Email: customer@gmail.com\n"
        "Notes:\n"
        "Email: user@example.com\n"
        "Password: abc123\n"
        "Login: https://rapidgator.net"
        "</code>\n\n"
        "Gunakan /produk untuk melihat daftar produk tersedia.",
        parse_mode="HTML",
    )


async def cmd_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    daftar = "\n".join([f"• {nama.title()}" for nama in PRODUCT_MAP.keys()])
    await update.message.reply_text(
        f"📦 <b>Daftar Produk Tersedia:</b>\n\n{daftar}",
        parse_mode="HTML",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Cek whitelist
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ Kamu tidak memiliki akses ke bot ini.")
        log.warning(f"Akses ditolak untuk user_id: {user_id}")
        return

    text = update.message.text or ""
    data = parse_perintah(text)

    if not data:
        await update.message.reply_text(
            "⚠️ <b>Format perintah tidak dikenali.</b>\n\n"
            "Gunakan format:\n"
            "<code>"
            "Order: nama produk\n"
            "Email: email@customer.com\n"
            "Notes:\n"
            "isi catatan di sini"
            "</code>\n\n"
            "Ketik /produk untuk melihat daftar produk.",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text("⏳ Memproses order, mohon tunggu...")

    product_id = cari_product_id(data["order"])
    if not product_id:
        await update.message.reply_text(
            f"❌ Produk <b>{data['order']}</b> tidak ditemukan.\n\n"
            f"Ketik /produk untuk melihat daftar produk yang tersedia.",
            parse_mode="HTML",
        )
        return

    try:
        order     = buat_order(product_id, data["email"], data["notes_text"])
        order_num = order.get("number", order.get("id", "-"))
        total     = order.get("total", "-")
        currency  = order.get("currency", "")

        await update.message.reply_text(
            f"✅ <b>Order berhasil dibuat!</b>\n\n"
            f"📦 Order #  : <code>{order_num}</code>\n"
            f"🛒 Produk  : {data['order'].title()}\n"
            f"📧 Email   : {data['email']}\n"
            f"💰 Total   : {currency} {total}\n\n"
            f"📬 Detail login sudah dikirim ke email customer.",
            parse_mode="HTML",
        )

    except Exception as e:
        log.error(f"Error buat order: {e}")
        await update.message.reply_text(
            f"❌ <b>Gagal membuat order.</b>\n\nError: <code>{str(e)}</code>",
            parse_mode="HTML",
        )


# ── Main ──────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN belum diisi di environment variables!")
    if not WC_URL:
        raise ValueError("WC_URL belum diisi di environment variables!")
    if not WC_KEY or not WC_SECRET:
        raise ValueError("WC_KEY / WC_SECRET belum diisi di environment variables!")

    log.info("Bot starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("produk", cmd_produk))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot berjalan! Menunggu pesan...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
