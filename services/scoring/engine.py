def score_liquidity(liquidity_usd: float) -> float:
    if liquidity_usd < 30_000:
        return 0
    if liquidity_usd < 100_000:
        return 12
    if liquidity_usd < 300_000:
        return 20
    if liquidity_usd < 800_000:
        return 15
    return 8


def score_buy_amount(usd: float) -> float:
    if usd < 5_000:
        return 2
    if usd < 20_000:
        return 8
    if usd < 100_000:
        return 15
    return 20


def score_whale_count(count: int) -> float:
    if count == 1:
        return 5
    if count == 2:
        return 12
    if count == 3:
        return 18
    return 20


def score_credibility(score: float) -> float:
    return round(min(score, 1) * 15, 2)


def score_time_gap(hours: float, whale_count: int) -> float:
    if whale_count < 2:
        return 0
    if hours < 1:
        return 10
    if hours < 6:
        return 7
    if hours < 24:
        return 4
    return 0


def score_buy_pressure(buy_usd: float, liquidity_usd: float) -> float:
    ratio = buy_usd / liquidity_usd
    if ratio < 0.01:
        return 2
    if ratio < 0.03:
        return 6
    if ratio < 0.08:
        return 12
    return 16


def score_price_impact(pct: float) -> float:
    if pct > 10:
        return 0
    if pct > 5:
        return 6
    if pct > 2:
        return 10
    return 8


from services.schemas import ScoreResult


def compute_score(factors: dict) -> ScoreResult:
    breakdown = {
        "liquidity": score_liquidity(factors["liquidity_usd"]),
        "buy_amount": score_buy_amount(factors["buy_amount_usd"]),
        "whale_count": score_whale_count(factors["whale_count"]),
        "credibility": score_credibility(factors["wallet_credibility"]),
        "time_gap": score_time_gap(factors["time_gap_hours"], factors["whale_count"]),
        "buy_pressure": score_buy_pressure(factors["buy_amount_usd"], factors["liquidity_usd"]),
        "price_impact": score_price_impact(factors["price_impact_pct"]),
    }
    total = max(0.0, min(100.0, sum(breakdown.values())))
    return ScoreResult(total=total, breakdown=breakdown)
