import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import pandas as pd
from dotenv import load_dotenv
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError
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
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ACTION_KEYWORDS = {
    "sale": ["sale", "sales", "సేల్", "సేల్స్", "అమ్మకం", "విక్రయం"],
    "purchase": ["purchase", "purchases", "పర్చేస్", "కొనుగోలు", "ఖర్చు"],
    "stock": ["stock", "స్టాక్", "నిల్వ"],
    "inventory": ["inventory", "ఇన్వెంటరీ"],
    "report": ["report", "రిపోర్ట్"],
    "profit": ["profit", "లాభం"],
    "vendors": ["vendor", "vendors", "వెండర్", "వెండర్లు", "సప్లయర్"],
}

STOP_WORDS = {
    "add", "create", "entry", "record", "chey", "cheyyi", "చేయి", "చేయండి",
    "ki", "lo", "ga", "rupees", "rs", "rs.", "₹", "amount", "mode",
    "sale", "sales", "purchase", "purchases", "stock", "vendor", "vendors",
}

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "thousand": 1000, "lakh": 100000,
    "lakhs": 100000,
    "ఒకటి": 1, "రెండు": 2, "మూడు": 3, "నాలుగు": 4, "ఐదు": 5,
    "ఆరు": 6, "ఏడు": 7, "ఎనిమిది": 8, "తొమ్మిది": 9, "పది": 10,
    "పదకొండు": 11, "పన్నెండు": 12, "పదమూడు": 13, "పద్నాలుగు": 14,
    "పదిహేను": 15, "పదహారు": 16, "పదిహేడు": 17, "పద్దెనిమిది": 18,
    "పంతొమ్మిది": 19, "ఇరవై": 20, "ముప్పై": 30, "నలభై": 40,
    "యాభై": 50, "అరవై": 60, "డెబ్బై": 70, "ఎనభై": 80,
    "తొంభై": 90, "వంద": 100, "నూరు": 100, "వెయ్యి": 1000,
    "వేలు": 1000, "వేల": 1000, "లక్ష": 100000,
}


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


def contains_keyword(text: str, action: str) -> bool:
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in ACTION_KEYWORDS[action])


def extract_amount(text: str) -> float | None:
    numeric_match = re.search(r"(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)", text, re.IGNORECASE)
    if numeric_match:
        return float(numeric_match.group(1).replace(",", ""))

    tokens = re.findall(r"[A-Za-z]+|[\u0C00-\u0C7F]+", text.lower())
    total = 0
    current = 0
    found = False

    for token in tokens:
        value = NUMBER_WORDS.get(token)
        if value is None:
            continue

        found = True
        if value == 100:
            current = max(current, 1) * value
        elif value >= 1000:
            total += max(current, 1) * value
            current = 0
        else:
            current += value

    if not found:
        return None

    return float(total + current)


def clean_tokens(text: str) -> list[str]:
    text_without_numbers = re.sub(r"(?:₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?", " ", text, flags=re.IGNORECASE)
    tokens = re.findall(r"[A-Za-z0-9_.-]+|[\u0C00-\u0C7F]+", text_without_numbers)
    all_action_words = {word.lower() for words in ACTION_KEYWORDS.values() for word in words}

    cleaned = []
    for token in tokens:
        lowered = token.lower().strip()
        if (
            lowered
            and lowered not in STOP_WORDS
            and lowered not in all_action_words
            and lowered not in NUMBER_WORDS
            and lowered not in {"cash", "online", "upi", "card", "నగదు"}
        ):
            cleaned.append(token)

    return cleaned


def detect_payment_mode(text: str) -> str:
    lower_text = text.lower()
    if "online" in lower_text or "upi" in lower_text or "గూగుల్" in lower_text:
        return "online"
    if "card" in lower_text:
        return "card"
    if "cash" in lower_text or "నగదు" in lower_text:
        return "cash"
    return "cash"


def extract_vendor(text: str) -> str:
    match = re.search(
        r"(?:vendor|supplier|వెండర్|సప్లయర్)\s+([A-Za-z0-9_.-]+|[\u0C00-\u0C7F]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return "unknown"


def extract_quantity(text: str, item: str = "") -> str:
    quantity_match = re.search(
        r"(\d[\d,]*(?:\.\d+)?\s*(?:kg|kgs|kilogram|grams|g|ltr|liter|litre|pieces|pcs|packets|bags|కేజీ|లీటర్)?)",
        text,
        re.IGNORECASE,
    )
    if quantity_match:
        return quantity_match.group(1).strip()

    amount = extract_amount(text)
    if amount is not None:
        return str(amount).rstrip("0").rstrip(".")

    tokens = clean_tokens(text)
    if item and item in tokens:
        tokens.remove(item)
    return " ".join(tokens[1:]).strip() if len(tokens) > 1 else ""


def simple_command_parse(text: str) -> dict:
    amount = extract_amount(text)

    if contains_keyword(text, "sale"):
        return {
            "action": "sale",
            "amount": amount,
            "mode": detect_payment_mode(text),
            "note": text,
        }

    if contains_keyword(text, "purchase"):
        tokens = clean_tokens(text)
        vendor = extract_vendor(text)
        item = tokens[0] if tokens else ""
        if vendor in tokens and len(tokens) > 1:
            item = next((token for token in tokens if token != vendor), item)
        return {
            "action": "purchase",
            "item": item,
            "amount": amount,
            "vendor": vendor,
            "note": text,
        }

    if contains_keyword(text, "stock"):
        tokens = clean_tokens(text)
        item = tokens[0] if tokens else ""
        quantity = extract_quantity(text, item)
        if item and quantity:
            return {
                "action": "stock",
                "item": item,
                "quantity": quantity,
                "note": text,
            }
        return {"action": "inventory"}

    for action in ("report", "profit", "vendors", "inventory"):
        if contains_keyword(text, action):
            return {"action": action}

    return {"action": "unknown"}


def looks_like_command(text: str) -> bool:
    return extract_amount(text) is not None or any(
        contains_keyword(text, action) for action in ACTION_KEYWORDS
    )


def normalize_action_data(data: dict) -> dict:
    action = str(data.get("action", "unknown")).lower().strip()
    if action not in {"sale", "purchase", "stock", "inventory", "report", "profit", "vendors", "chat", "unknown"}:
        action = "unknown"

    amount = data.get("amount")
    try:
        amount = float(amount) if amount not in (None, "", "null") else None
    except (TypeError, ValueError):
        amount = None

    return {
        "action": action,
        "amount": amount,
        "mode": str(data.get("mode") or "cash").strip(),
        "item": str(data.get("item") or "").strip(),
        "quantity": str(data.get("quantity") or "").strip(),
        "vendor": str(data.get("vendor") or "unknown").strip(),
        "note": str(data.get("note") or "").strip(),
    }


def ai_command_parse(text: str) -> dict:
    if openai_client is None:
        return {"action": "unknown"}

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You convert Telugu, English, or Telugu-English mixed restaurant bot commands into JSON. "
                    "Return only a JSON object. JSON keys: action, amount, mode, item, quantity, vendor, note. "
                    "action must be one of sale, purchase, stock, inventory, report, profit, vendors, chat, unknown. "
                    "Use sale when user records restaurant sales. Use purchase when user records buying/expense/vendor purchase. "
                    "Use stock when user updates inventory quantity. Use inventory/report/profit/vendors for those reports. "
                    "If required details are missing, still choose the closest action and leave missing fields empty/null."
                ),
            },
            {"role": "user", "content": text},
        ],
    )

    raw = response.choices[0].message.content or "{}"
    return normalize_action_data(json.loads(raw))


def interpret_command(text: str, allow_ai: bool = True) -> tuple[dict, Exception | None]:
    parsed = normalize_action_data(simple_command_parse(text))
    if parsed["action"] != "unknown":
        return parsed, None

    if not allow_ai or openai_client is None:
        return parsed, None

    try:
        return ai_command_parse(text), None
    except Exception as exc:
        return parsed, exc


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


def add_sale_record(amount: float, mode: str = "cash", note: str = "") -> str:
    append_csv(SALES_FILE, {
        "amount": amount,
        "mode": mode or "cash",
        "note": note,
    })
    return f"Sale added: {money(amount)} via {mode or 'cash'}"


def add_purchase_record(item: str, amount: float, vendor: str = "unknown", note: str = "") -> str:
    append_csv(PURCHASE_FILE, {
        "item": item,
        "amount": amount,
        "vendor": vendor or "unknown",
        "note": note,
    })
    return f"Purchase added: {item} for {money(amount)}"


def add_stock_record(item: str, quantity: str) -> str:
    append_csv(STOCK_FILE, {
        "item": item,
        "quantity": quantity,
    })
    return f"Stock updated: {item} - {quantity}"


def inventory_text() -> str:
    lines = inventory_lines(limit=20)
    if not lines:
        return "No inventory data yet."
    return "Inventory\n\n" + "\n".join(lines)


def report_text() -> str:
    totals = business_totals()
    return (
        "Report\n\n"
        f"Sales: {money(totals['sales_total'])}\n"
        f"Purchases: {money(totals['purchases_total'])}\n"
        f"Profit: {money(totals['profit'])}"
    )


def profit_text() -> str:
    totals = business_totals()
    return f"Profit: {money(totals['profit'])}"


def vendors_text() -> str:
    lines = vendor_lines(limit=20)
    if not lines:
        return "No vendor purchase data yet."
    return "Vendors\n\n" + "\n".join(lines)


def execute_bot_action(data: dict) -> str | None:
    action = data.get("action")

    if action == "sale":
        amount = data.get("amount")
        if amount is None:
            return "Sale amount cheppandi. Example: 12000 cash sale."
        return add_sale_record(amount, data.get("mode") or "cash", data.get("note") or "")

    if action == "purchase":
        amount = data.get("amount")
        item = data.get("item") or ""
        if amount is None or not item:
            return "Purchase item and amount cheppandi. Example: chicken 5000 vendor Raju purchase."
        return add_purchase_record(item, amount, data.get("vendor") or "unknown", data.get("note") or "")

    if action == "stock":
        item = data.get("item") or ""
        quantity = data.get("quantity") or ""
        if not item or not quantity:
            return "Stock item and quantity cheppandi. Example: chicken 50kg stock."
        return add_stock_record(item, quantity)

    if action == "inventory":
        return inventory_text()

    if action == "report":
        return report_text()

    if action == "profit":
        return profit_text()

    if action == "vendors":
        return vendors_text()

    return None


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


def ai_error_message(exc: Exception) -> str:
    error_text = str(exc).lower()

    if isinstance(exc, RateLimitError):
        if (
            "insufficient_quota" in error_text
            or "current quota" in error_text
            or "billing" in error_text
            or "run out of credits" in error_text
        ):
            return (
                "AI quota/credits ayipoyayi. OpenAI API billing or credits add cheyyali.\n\n"
                "Normal commands still work:\n"
                "/sale, /purchase, /stock, /inventory, /report, /profit, /vendors"
            )

        return "AI rate limit hit ayyindi. Konchem time tarvata malli try cheyyandi."

    if isinstance(exc, AuthenticationError):
        return "AI key problem undi. OPENAI_API_KEY correct ga set chesaro check cheyyali."

    if isinstance(exc, APIConnectionError):
        return "AI service ki connect avvalekapoyindi. Internet/server connection check cheyyali."

    if isinstance(exc, APIError):
        return "AI service temporary problem. Konchem time tarvata malli try cheyyandi."

    return "AI reply generate avvaledu. Konchem time tarvata malli try cheyyandi."


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
        "You can also send Telugu voice notes like:\n"
        "12000 cash sale add chey\n"
        "chicken 5000 vendor Raju purchase\n"
        "chicken 50kg stock\n\n"
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

    await update.message.reply_text(add_sale_record(amount, mode, note))


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

    await update.message.reply_text(add_purchase_record(item, amount, vendor, note))


async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /stock chicken 50kg")
        return

    item = context.args[0]
    quantity = " ".join(context.args[1:])

    await update.message.reply_text(add_stock_record(item, quantity))


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(inventory_text())


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(report_text())


async def profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(profit_text())


async def vendors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(vendors_text())


def generate_ai_reply(user_message: str) -> str:
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

    return response.choices[0].message.content or "I could not generate a reply."


def transcribe_audio_file(audio_path: Path) -> str:
    with audio_path.open("rb") as audio_file:
        transcription = openai_client.audio.transcriptions.create(
            model=OPENAI_TRANSCRIBE_MODEL,
            file=audio_file,
            language="te",
        )

    return getattr(transcription, "text", "").strip()


async def handle_natural_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    parsed, parse_error = interpret_command(
        user_message,
        allow_ai=looks_like_command(user_message),
    )
    action_reply = execute_bot_action(parsed)

    if action_reply:
        await update.message.reply_text(action_reply)
        return

    if parse_error is not None:
        await update.message.reply_text(ai_error_message(parse_error))
        return

    if openai_client is None:
        await update.message.reply_text("AI is not configured. Add OPENAI_API_KEY to .env.")
        return

    try:
        await update.message.reply_text(generate_ai_reply(user_message))

    except Exception as exc:
        await update.message.reply_text(ai_error_message(exc))


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if openai_client is None:
        await update.message.reply_text("Voice AI is not configured. Add OPENAI_API_KEY to .env.")
        return

    message_audio = update.message.voice or update.message.audio
    if message_audio is None:
        await update.message.reply_text("Voice message dorakaledu. Telegram voice note pampandi.")
        return

    suffix = ".ogg"
    if update.message.audio and update.message.audio.file_name:
        suffix = Path(update.message.audio.file_name).suffix or ".mp3"

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)

        telegram_file = await context.bot.get_file(message_audio.file_id)
        await telegram_file.download_to_drive(custom_path=temp_path)
        transcript = transcribe_audio_file(temp_path)

    except Exception as exc:
        await update.message.reply_text(ai_error_message(exc))
        return

    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    if not transcript:
        await update.message.reply_text("Voice clear ga artham kaaledu. Malli voice note pampandi.")
        return

    parsed, parse_error = interpret_command(transcript, allow_ai=True)
    action_reply = execute_bot_action(parsed)
    prefix = f"Voice text: {transcript}\n\n"

    if action_reply:
        await update.message.reply_text(prefix + action_reply)
        return

    if parse_error is not None:
        await update.message.reply_text(prefix + ai_error_message(parse_error))
        return

    try:
        await update.message.reply_text(prefix + generate_ai_reply(transcript))
    except Exception as exc:
        await update.message.reply_text(prefix + ai_error_message(exc))


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

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_text))

    print("Restaurant AI Bot PRO running...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(f"Error: {exc}")
