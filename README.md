# WhaleLens

Whale wallet tracker — monitors DEX swaps, scores them (0-100) via GoPlus + DexScreener + 7-factor engine, alerts to Telegram.

## Setup

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
alembic upgrade head
uvicorn main:app --reload
```

## Structure

```
main.py                  Webhook endpoint
services/processor.py    Pipeline orchestrator
services/scoring/        Scoring engine
services/checkers/       GoPlus, DexScreener
services/notifier/       Telegram alerts
models/                  ORM (wallet, transaction, alert)
```
