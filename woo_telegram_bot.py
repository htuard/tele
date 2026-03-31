"""
Telegram Bot - WooCommerce Auto Order
======================================
Requirements:
    pip install python-telegram-bot requests

Cara pakai:
    1. Isi TELEGRAM_TOKEN, WC_URL, WC_KEY, WC_SECRET di bawah
    2. Jalankan: python woo_telegram_bot.py
    3. Chat bot dengan format perintah yang sudah ditentukan
"""

import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ============================================================
# KONFIGURASI — isi sesuai data kamu
# ============================================================
TELEGRAM_TOKEN = "8766843552:AAEwptX0X3TWJHSkZ-Xm_R_n-3nGNyyjpkg"
WC_URL         = "https://premixstore.com"          # URL WooCommerce tanpa trailing slash
WC_KEY         = "ck_9a9d7d5a4296b8f8b022190be25bcf6bd5e1e99b"   # Consumer Key
WC_SECRET      = "cs_d757b5552d02acc24051b012828514d0d17b2b76"   # Consumer Secret

# Daftar Telegram user_id yang boleh pakai bot (whitelist)
# Kosongkan list untuk menonaktifkan whitelist: ALLOWED_USERS = []
ALLOWED_USERS = [6058576490]  # Ganti dengan Telegram user ID kamu

# Mapping nama produk → WooCommerce product ID
# Tambahkan produk sesuai toko kamu
PRODUCT_MAP = {
    "rapidgator 1 minggu"  : 101,
    "rapidgator 1 bulan"   : 102,
    "rapidgator 3 bulan"   : 103,
    # tambahkan produk lain di sini
}
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


def parse_perintah(text: str) -> dict | None:
    """
    Parse pesan dengan format:
        Order: <nama produk>
        Email: <email customer>
        Notes: <teks bebas, bisa multiline>
    """
    lines  = text.strip().splitlines()
    result = {"order": None, "email": None, "notes": []}
    mode   = None

    for line in lines:
        lower = line.strip().lower()
        if lower.startswith("order:"):
            result["order"] = line.split(":", 1)[1].strip()
            mode = "order"
        elif lower.startswith("email:") and result["email"] is None:
            result["email"] = line.split(":", 1)[1].strip()
            mode = "email"
        elif lower.startswith("notes:"):
            after = line.split(":", 1)[1].strip()
            if after:
                result["notes"].append(after)
            mode = "notes"
        elif mode == "notes":
            result["notes"].append(line.strip())

    result["notes"] = "\n".join(result["notes"]).strip()

    if result["order"] and result["email"]:
        return result
    return None


def cari_product_id(nama_produk: str) -> int | None:
    """Cari product ID dari PRODUCT_MAP, fallback ke WooCommerce API jika tidak ada."""
    key = nama_produk.lower().strip()
    if key in PRODUCT_MAP:
        return PRODUCT_MAP[key]

    # Fallback: cari by nama via API
    try:
        r = requests.get(
            f"{WC_URL}/wp-json/wc/v3/products",
            params={"search": nama_produk, "per_page": 5},
            auth=(WC_KEY, WC_SECRET),
            timeout=10
        )
        products = r.json()
        if isinstance(products, list) and products:
            return products[0]["id"]
    except Exception as e:
        logging.error(f"Error cari produk: {e}")

    return None


def buat_order(product_id: int, email: str, notes: str) -> dict:
    """Buat order di WooCommerce dan tambahkan customer note."""
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
        ]
    }

    r = requests.post(
        f"{WC_URL}/wp-json/wc/v3/orders",
        json=payload,
        auth=(WC_KEY, WC_SECRET),
        timeout=15
    )
    order = r.json()

    if "id" not in order:
        raise Exception(f"Gagal buat order: {order}")

    order_id = order["id"]

    # Tambahkan order note (customer_note=True → email dikirim ke customer)
    if notes:
        requests.post(
            f"{WC_URL}/wp-json/wc/v3/orders/{order_id}/notes",
            json={"note": notes, "customer_note": True},
            auth=(WC_KEY, WC_SECRET),
            timeout=10
        )

    return order


# ============================================================
# Handler Telegram
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya bot order otomatis WooCommerce.\n\n"
        "Kirim perintah dengan format:\n\n"
        "<code>Order: RapidGator 1 Minggu\n"
        "Email: customer@gmail.com\n"
        "Notes:\n"
        "Email: user@example.com\n"
        "Password: abc123\n"
        "Login: https://example.com</code>",
        parse_mode="HTML"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Cek whitelist
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("⛔ Kamu tidak memiliki akses ke bot ini.")
        return

    text = update.message.text or ""
    data = parse_perintah(text)

    if not data:
        await update.message.reply_text(
            "⚠️ Format perintah tidak dikenali.\n\n"
            "Gunakan format:\n"
            "<code>Order: nama produk\nEmail: email@customer.com\nNotes: isi catatan</code>",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text("⏳ Memproses order...")

    product_id = cari_product_id(data["order"])
    if not product_id:
        await update.message.reply_text(
            f"❌ Produk <b>{data['order']}</b> tidak ditemukan.\n"
            "Pastikan nama produk sesuai atau tambahkan ke PRODUCT_MAP.",
            parse_mode="HTML"
        )
        return

    try:
        order = buat_order(product_id, data["email"], data["notes"])
        order_id  = order["id"]
        order_num = order.get("number", order_id)
        total     = order.get("total", "-")
        currency  = order.get("currency", "")

        await update.message.reply_text(
            f"✅ <b>Order berhasil dibuat!</b>\n\n"
            f"📦 Order #: <code>{order_num}</code>\n"
            f"🛒 Produk: {data['order']}\n"
            f"📧 Customer: {data['email']}\n"
            f"💰 Total: {currency} {total}\n\n"
            f"📬 Email + notes sudah dikirim ke customer.",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Error buat order: {e}")
        await update.message.reply_text(
            f"❌ Gagal membuat order.\nError: <code>{str(e)}</code>",
            parse_mode="HTML"
        )


# ============================================================
# Main
# ============================================================

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot berjalan... tekan Ctrl+C untuk berhenti.")
    app.run_polling()


if __name__ == "__main__":
    main()
