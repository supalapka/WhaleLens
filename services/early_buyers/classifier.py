import bisect
from collections import defaultdict
from datetime import datetime, timezone

from services.early_buyers.schemas import (
    BuySummary,
    ClassifiedSwap,
    EarlyBuyerRecord,
    OhlcvCandle,
    PricedSwap,
    SellSummary,
    TokenTransfer,
    _r2,
    _r_price,
)

MIN_BUY_USD = 50.0
MIN_SOLD_RATIO_PCT = 1.0
MIN_PROFIT_PCT = 500.0


def classify_transfers(
    transfers: list[TokenTransfer],
    pool_addresses: set[str],
) -> tuple[list[ClassifiedSwap], list[ClassifiedSwap]]:
    buys: list[ClassifiedSwap] = []
    sells: list[ClassifiedSwap] = []

    for t in transfers:
        amount = t.token_amount
        if amount <= 0:
            continue

        ts = t.timestamp_dt

        if t.from_address in pool_addresses:
            buys.append(ClassifiedSwap(
                wallet_address=t.to_address,
                token_amount=amount,
                timestamp=ts,
                tx_hash=t.transaction_hash,
            ))
        elif t.to_address in pool_addresses:
            sells.append(ClassifiedSwap(
                wallet_address=t.from_address,
                token_amount=amount,
                timestamp=ts,
                tx_hash=t.transaction_hash,
            ))

    return buys, sells


def assign_usd_prices(
    swaps: list[ClassifiedSwap],
    candles: list[OhlcvCandle],
) -> list[PricedSwap]:
    if not candles:
        return []

    timestamps = [c.timestamp for c in candles]
    priced: list[PricedSwap] = []

    for swap in swaps:
        swap_ts = int(swap.timestamp.timestamp())
        idx = bisect.bisect_left(timestamps, swap_ts)

        if idx == 0:
            nearest = candles[0]
        elif idx >= len(candles):
            nearest = candles[-1]
        else:
            before = candles[idx - 1]
            after = candles[idx]
            nearest = (
                before
                if abs(before.timestamp - swap_ts) <= abs(after.timestamp - swap_ts)
                else after
            )

        price = nearest.close
        priced.append(PricedSwap(
            wallet_address=swap.wallet_address,
            token_amount=swap.token_amount,
            timestamp=swap.timestamp,
            tx_hash=swap.tx_hash,
            price_usd=price,
            usd_value=swap.token_amount * price,
        ))

    return priced


def aggregate_wallets(
    buys: list[PricedSwap],
    sells: list[PricedSwap],
    start_ts: int,
    end_ts: int,
) -> list[EarlyBuyerRecord]:
    all_buys: dict[str, list[PricedSwap]] = defaultdict(list)
    for b in buys:
        all_buys[b.wallet_address].append(b)

    all_sells: dict[str, list[PricedSwap]] = defaultdict(list)
    for s in sells:
        all_sells[s.wallet_address].append(s)

    records: list[EarlyBuyerRecord] = []
    for wallet, wallet_buys in all_buys.items():
        total_bought_tokens = sum(b.token_amount for b in wallet_buys)
        total_bought_usd = sum(b.usd_value for b in wallet_buys)
        if total_bought_tokens == 0:
            continue
        avg_buy_price = total_bought_usd / total_bought_tokens

        wallet_sells = all_sells.get(wallet, [])
        total_sold_tokens = sum(s.token_amount for s in wallet_sells)
        total_sold_usd = sum(s.usd_value for s in wallet_sells)
        sell_count = len(wallet_sells)

        if total_sold_tokens > total_bought_tokens:
            total_sold_tokens = total_bought_tokens
            total_sold_usd = total_sold_tokens * (
                total_sold_usd / sum(s.token_amount for s in wallet_sells)
            ) if wallet_sells else 0.0

        avg_sell_price = (
            total_sold_usd / total_sold_tokens if total_sold_tokens > 0 else 0.0
        )

        sold_ratio_pct = (
            min((total_sold_tokens / total_bought_tokens) * 100, 100.0)
            if total_bought_tokens > 0
            else 0.0
        )

        profit_pct = (
            ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
            if avg_buy_price > 0 and avg_sell_price > 0
            else 0.0
        )

        profit_abs_usd = total_sold_usd - (total_sold_tokens * avg_buy_price)

        first_buy_time = min(b.timestamp for b in wallet_buys)
        first_sell_time = min(s.timestamp for s in wallet_sells) if wallet_sells else None
        last_sell_time = max(s.timestamp for s in wallet_sells) if wallet_sells else None

        records.append(EarlyBuyerRecord(
            wallet=wallet,
            buy=BuySummary(
                first_time=first_buy_time,
                tokens=_r2(total_bought_tokens),
                usd=_r2(total_bought_usd),
                avg_price=_r_price(avg_buy_price),
            ),
            sell=SellSummary(
                count=sell_count,
                first_time=first_sell_time,
                last_time=last_sell_time,
                tokens=_r2(total_sold_tokens),
                usd=_r2(total_sold_usd),
                avg_price=_r_price(avg_sell_price),
            ),
            sold_pct=_r2(sold_ratio_pct),
            profit_pct=_r2(profit_pct),
            profit_usd=_r2(profit_abs_usd),
        ))

    return records


def apply_filters(records: list[EarlyBuyerRecord]) -> list[EarlyBuyerRecord]:
    filtered = [
        r for r in records
        if r.buy.usd >= MIN_BUY_USD
        and r.sold_pct >= MIN_SOLD_RATIO_PCT
        and r.profit_pct >= MIN_PROFIT_PCT
    ]
    filtered.sort(key=lambda r: r.profit_pct, reverse=True)
    return filtered


