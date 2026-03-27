FACTOR_MAX = {
    "liquidity": 20,
    "buy_amount": 20,
    "whale_count": 20,
    "credibility": 15,
    "time_gap": 10,
    "buy_pressure": 16,
    "price_impact": 10,
}

FACTOR_LABELS = {
    "liquidity": "Liquidity",
    "buy_amount": "Buy Amount",
    "whale_count": "Whale Count",
    "credibility": "Credibility",
    "time_gap": "Time Gap",
    "buy_pressure": "Buy Pressure",
    "price_impact": "Price Impact",
}

CHAIN_INFO = {
    "0x38": {
        "label": "BSC",
        "dexscreener": "bsc",
        "explorer": "https://bscscan.com",
    },
    "0x1": {
        "label": "Ethereum",
        "dexscreener": "ethereum",
        "explorer": "https://etherscan.io",
    },
    "0x2105": {
        "label": "Base",
        "dexscreener": "base",
        "explorer": "https://basescan.org",
    },
    "0xa4b1": {
        "label": "Arbitrum",
        "dexscreener": "arbitrum",
        "explorer": "https://arbiscan.io",
    },
}


def make_bar(got: float, max_: float, width: int = 10) -> str:
    filled = round((got / max_) * width) if max_ > 0 else 0
    return "\u2588" * filled + "\u2591" * (width - filled)


from services.schemas import AlertData, TransactionEvent


_CHAIN_SLUGS = {k: v["dexscreener"] for k, v in CHAIN_INFO.items()}


def build_vip_message(event: TransactionEvent) -> str:
    token = event.token_symbol or event.token_address[:6] + "..." + event.token_address[-4:]
    chain_slug = _CHAIN_SLUGS.get(event.chain, "ethereum")
    return (
        f"\U0001f40b *VIP WALLET* \u2014 {event.chain}\n"
        f"\n"
        f"\u00b7 *{event.wallet_label}* bought *{token}*\n"
        f"  `{event.token_address}`\n"
        f"\n"
        f"\U0001f517 [DexScreener](https://dexscreener.com/{chain_slug}/{event.token_address})"
    )


def build_message(alert: AlertData) -> str:
    short_address = alert.token_address[:6] + "..." + alert.token_address[-4:]

    factor_lines = []
    for key, label in FACTOR_LABELS.items():
        got = alert.breakdown.get(key, 0)
        max_ = FACTOR_MAX[key]
        bar = make_bar(got, max_)
        factor_lines.append(f"{label:<14} {bar} {got}/{max_}")

    whale_lines = f"\u00b7 {alert.wallet_label} \u2014 ${alert.buy_amount_usd:,.0f}"
    score_bar = make_bar(alert.score, 100)

    return (
        f"\U0001f40b *WHALE ALERT* \u2014 {alert.chain}\n"
        f"\n"
        f"\U0001fa99 *{alert.symbol}* \u00b7 `{short_address}`\n"
        f"\U0001f4ca Score: *{alert.score:.0f}/100* {score_bar}\n"
        f"\n"
        f"\U0001f45b *Whales in this token:*\n"
        f"{whale_lines}\n"
        f"\n"
        f"\U0001f4a7 Liquidity:     *${alert.liquidity_usd:,.0f}*\n"
        f"\U0001f4c8 Price Impact:  *{alert.price_impact_pct:.1f}%*\n"
        f"\U0001f4c5 Token Age:     *{alert.token_age_days}d*\n"
        f"\U0001f4b1 24h Txns:      *{alert.txns_24h:,}*\n"
        f"\n"
        f"\U0001f50d *Score Breakdown:*\n"
        f"```\n{chr(10).join(factor_lines)}\n```\n"
        f"\n"
        f"\U0001f517 [DexScreener](https://dexscreener.com/ethereum/{alert.token_address})"
        f" \u00b7 [Etherscan](https://etherscan.io/token/{alert.token_address})"
    )


def build_pair_message(
    symbol: str,
    name: str,
    token_address: str,
    pair_address: str | None,
    chain_id: str,
    warnings: list[str] | None = None,
) -> str:
    chain = CHAIN_INFO.get(chain_id.lower())

    if not chain:
        chain = {
            "label": chain_id,
            "dexscreener": "ethereum",
            "explorer": "https://etherscan.io",
        }

    short_token = token_address[:6] + "..." + token_address[-4:]
    title = f"*{symbol}*" if not name else f"*{symbol}* ({name})"

    lines = [
        f"\U0001f195 *NEW PAIR* — {chain['label']}",
        "",
        f"\U0001fa99 {title}",
        f"\U0001f4cb Token: `{short_token}`",
    ]

    if pair_address:
        short_pair = pair_address[:6] + "..." + pair_address[-4:]
        lines.append(f"\U0001f4b1 Pair: `{short_pair}`")

    if warnings:
        lines += ["", "\u26a0\ufe0f *Warnings:*"]
        for w in warnings:
            lines.append(f"\u00b7 {w}")

    lines += [
        "",
        f"\U0001f517 [DexScreener](https://dexscreener.com/{chain['dexscreener']}/{token_address})"
        f" · [Explorer]({chain['explorer']}/token/{token_address})",
    ]

    return "\n".join(lines)
