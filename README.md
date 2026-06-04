# Restaurant AI Bot PRO

Telegram bot for restaurant sales, purchases, inventory, vendor tracking, simple reports, dashboard data, and AI business questions.

## Features

- Sales and purchase entry from Telegram
- Inventory updates
- Profit and vendor reports
- AI answers using your current restaurant CSV data
- Telugu voice notes for sales, purchases, stock updates, and reports
- Flask dashboard API at `/dashboard`
- Local CSV storage

## Setup

1. Create a Telegram bot:
   - Open Telegram and message `@BotFather`
   - Send `/newbot`
   - Copy the bot token

2. Create `.env` in this folder:

```env
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
OPENAI_API_KEY=YOUR_OPENAI_KEY
OPENAI_MODEL=gpt-4o-mini
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run the bot:

```bash
python bot.py
```

## Telegram Commands

```text
/start
/help
/sale 12000 cash
/sale 8500 online
/purchase chicken 5000 vendor_name
/stock chicken 50kg
/inventory
/report
/profit
/vendors
```

You can also ask normal questions, such as:

```text
Today profit?
Chicken stock?
Top expenses?
Monthly sales?
```

## Voice Commands

Send a Telegram voice note in Telugu, English, or mixed wording:

```text
12000 cash sale add chey
chicken 5000 vendor Raju purchase
chicken 50kg stock
profit entha?
report ivvu
```

The bot transcribes the voice note, detects the action, updates data when needed, and replies as a text message.

## Dashboard API

Run:

```bash
python dashboard_api.py
```

Open:

```text
http://127.0.0.1:5000/dashboard
```
