# Restaurant AI Bot PRO

Telegram bot for restaurant sales, purchases, inventory, vendor tracking, simple reports, dashboard data, and AI business questions.

## Features

- Sales and purchase entry from Telegram
- Inventory updates
- Profit and vendor reports
- AI answers using your current restaurant CSV data
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

## Dashboard API

Run:

```bash
python dashboard_api.py
```

Open:

```text
http://127.0.0.1:5000/dashboard
```
