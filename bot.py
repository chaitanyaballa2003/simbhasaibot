import os
from datetime import datetime
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SALES_FILE = BASE_DIR / "sales.csv"
PURCHASE_FILE = BASE_DIR / "purchases.csv"
STOCK_FILE = BASE_DIR / "inventory.csv"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def read_csv(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(file_path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def append_csv(file_path: Path, data: dict) -> None:
    record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **data,
    }
    new_row = pd.DataFrame([record])

    if not file_path.exists():
        new_row.to_csv(file_path, index=False)
        return

    current = read_csv(file_path)
    columns = list(dict.fromkeys([*current.columns, *new_row.columns]))
    current = current.reindex(columns=columns)
    new_row = new_row.reindex(columns=columns)
    pd.concat([current, new_row], ignore_index=True).to_csv(file_path, index=False)


def numeric_total(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def money(amount: float) -> str:
    return f"Rs. {amount:,.2f}"


def business_totals() -> dict:
    sales = read_csv(SALES_FILE)
    purchases = read_csv(PURCHASE_FILE)
    sales_total = numeric_total(sales, "amount")
    purchases_total = numeric_total(purchases, "amount")

    return {
        "sales": sales,
        "purchases": purchases,
        "sales_total": sales_total,
        "purchases_total": purchases_total,
        "profit": sales_total - purchases_total,
    }


def inventory_lines(limit: int = 10) -> list[str]:
    stock = read_csv(STOCK_FILE)
    if stock.empty or "item" not in stock.columns or "quantity" not in stock.columns:
        return []

    return [
        f"{row['item']} - {row['quantity']}"
        for _, row in stock.tail(limit).iterrows()
    ]


def vendor_lines(limit: int = 10) -> list[str]:
    purchases = read_csv(PURCHASE_FILE)
    if purchases.empty or "vendor" not in purchases.columns or "amount" not in purchases.columns:
        return []

    grouped = purchases.copy()
    grouped["amount"] = pd.to_numeric(grouped["amount"], errors="coerce").fillna(0)
    totals = grouped.groupby("vendor", dropna=False)["amount"].sum().sort_values(ascending=False)
    return [f"{vendor}: {money(amount)}" for vendor, amount in totals.head(limit).items()]


def snapshot_for_ai() -> str:
    totals = business_totals()
    inventory = inventory_lines(limit=20)
    vendors = vendor_lines(limit=20)

    return (
        "Current restaurant data:\n"
        f"- Total sales: {money(totals['sales_total'])}\n"
        f"- Total purchases: {money(totals['purchases_total'])}\n"
        f"- Profit: {money(totals['profit'])}\n"
        f"- Recent inventory: {', '.join(inventory) if inventory else 'No inventory recorded'}\n"
        f"- Vendor purchases: {', '.join(vendors) if vendors else 'No vendor purchases recorded'}"
    )


def require_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    placeholder_tokens = {"YOUR_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN"}
    if not token or token in placeholder_tokens:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN. Create a bot in Telegram with @BotFather, "
            "then add TELEGRAM_BOT_TOKEN=your_token to the .env file."
        )
    return token


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Restaurant AI Bot PRO Activated!\n\n"
        "Commands:\n"
        "/sale 12000 cash\n"
        "/purchase chicken 5000 vendor_name\n"
        "/stock chicken 50kg\n"
        "/inventory\n"
        "/report\n"
        "/profit\n"
        "/vendors\n\n"
        "You can also ask: Today profit? Chicken stock? Top expenses?"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /sale 12000 cash")
        return

    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Amount must be a number. Example: /sale 12000 cash")
        return

    mode = context.args[1]
    note = " ".join(context.args[2:])

    append_csv(SALES_FILE, {
        "amount": amount,
        "mode": mode,
        "note": note,
    })

    await update.message.reply_text(f"Sale added: {money(amount)} via {mode}")


async def purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /purchase chicken 5000 vendor")
        return

    item = context.args[0]

    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number. Example: /purchase chicken 5000 vendor")
        return

    vendor = context.args[2]
    note = " ".join(context.args[3:])

    append_csv(PURCHASE_FILE, {
        "item": item,
        "amount": amount,
        "vendor": vendor,
        "note": note,
    })

    await update.message.reply_text(f"Purchase added: {item} for {money(amount)}")


async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /stock chicken 50kg")
        return

    item = context.args[0]
    quantity = " ".join(context.args[1:])

    append_csv(STOCK_FILE, {
        "item": item,
        "quantity": quantity,
    })

    await update.message.reply_text(f"Stock updated: {item} - {quantity}")


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = inventory_lines(limit=20)
    if not lines:
        await update.message.reply_text("No inventory data yet.")
        return

    await update.message.reply_text("Inventory\n\n" + "\n".join(lines))


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    totals = business_totals()

    await update.message.reply_text(
        "Report\n\n"
        f"Sales: {money(totals['sales_total'])}\n"
        f"Purchases: {money(totals['purchases_total'])}\n"
        f"Profit: {money(totals['profit'])}"
    )


async def profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    totals = business_totals()
    await update.message.reply_text(f"Profit: {money(totals['profit'])}")


async def vendors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = vendor_lines(limit=20)
    if not lines:
        await update.message.reply_text("No vendor purchase data yet.")
        return

    await update.message.reply_text("Vendors\n\n" + "\n".join(lines))


async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if openai_client is None:
        await update.message.reply_text("AI is not configured. Add OPENAI_API_KEY to .env.")
        return

    user_message = update.message.text

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise restaurant business assistant. "
                        "Use the provided restaurant data when answering questions "
                        "about sales, purchases, profit, inventory, and vendors. "
                        "If the data is missing, say what has not been recorded yet.\n\n"
                        f"{snapshot_for_ai()}"
                    ),
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
        )

        reply = response.choices[0].message.content or "I could not generate a reply."
        await update.message.reply_text(reply)

    except Exception as exc:
        await update.message.reply_text(f"AI Error: {exc}")


def main():
    app = ApplicationBuilder().token(require_token()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("sale", sale))
    app.add_handler(CommandHandler("purchase", purchase))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("profit", profit))
    app.add_handler(CommandHandler("vendors", vendors))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat))

    print("Restaurant AI Bot PRO running...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(f"Error: {exc}")
