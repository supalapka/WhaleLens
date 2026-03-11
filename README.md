# WhaleLens

Whale/insider wallet tracker. Monitors on-chain DEX swaps from tracked wallets, scores them, and pushes alerts to Telegram.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs for Swagger UI.
