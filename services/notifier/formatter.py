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


def make_bar(got: float, max_: float, width: int = 10) -> str:
    filled = round((got / max_) * width) if max_ > 0 else 0
    return "\u2588" * filled + "\u2591" * (width - filled)


def build_message(alert_data: dict) -> str:
    token_address = alert_data["token_address"]
    short_address = token_address[:6] + "..." + token_address[-4:]
    breakdown = alert_data["breakdown"]

    factor_lines = []
    for key, label in FACTOR_LABELS.items():
        got = breakdown.get(key, 0)
        max_ = FACTOR_MAX[key]
        bar = make_bar(got, max_)
        factor_lines.append(f"{label:<14} {bar} {got}/{max_}")

    whale_lines = f"\u00b7 {alert_data['wallet_label']} \u2014 ${alert_data['buy_amount_usd']:,.0f}"

    score = alert_data["score"]
    score_bar = make_bar(score, 100)

    return (
        f"\U0001f40b *WHALE ALERT* \u2014 {alert_data['chain']}\n"
        f"\n"
        f"\U0001fa99 *{alert_data['symbol']}* \u00b7 `{short_address}`\n"
        f"\U0001f4ca Score: *{score:.0f}/100* {score_bar}\n"
        f"\n"
        f"\U0001f45b *Whales in this token:*\n"
        f"{whale_lines}\n"
        f"\n"
        f"\U0001f4a7 Liquidity:     *${alert_data['liquidity_usd']:,.0f}*\n"
        f"\U0001f4c8 Price Impact:  *{alert_data['price_impact_pct']:.1f}%*\n"
        f"\U0001f4c5 Token Age:     *{alert_data['token_age_days']}d*\n"
        f"\U0001f4b1 24h Txns:      *{alert_data['txns_24h']:,}*\n"
        f"\n"
        f"\U0001f50d *Score Breakdown:*\n"
        f"```\n{chr(10).join(factor_lines)}\n```\n"
        f"\n"
        f"\U0001f517 [DexScreener](https://dexscreener.com/ethereum/{token_address})"
        f" \u00b7 [Etherscan](https://etherscan.io/token/{token_address})"
    )
