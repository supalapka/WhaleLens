from collections import defaultdict
from dataclasses import dataclass

from models.constants import TRANSFER_TOPIC
from services.early_buyers.schemas import (
    BuySummary,
    ClassifiedSwap,
    EarlyBuyerRecord,
    PricedSwap,
    SellSummary,
    TokenTransfer,
    _r2,
    _r_price,
)


@dataclass(frozen=True)
class QuoteTokenConfig:
    address: str
    decimals: int
    to_usd: float

MIN_BUY_USD = 100.0
MIN_SOLD_RATIO_PCT = 1.0
MIN_PROFIT_PCT = 1000.0


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


def assign_swap_prices(
    swaps: list[ClassifiedSwap],
    quote_usd_by_tx: dict[str, float],
) -> list[PricedSwap]:
    base_by_tx: dict[str, float] = defaultdict(float)
    for swap in swaps:
        base_by_tx[swap.tx_hash] += swap.token_amount

    priced: list[PricedSwap] = []
    for swap in swaps:
        total_quote_usd = quote_usd_by_tx.get(swap.tx_hash, 0)
        total_base = base_by_tx.get(swap.tx_hash, 0)
        if total_quote_usd <= 0 or total_base <= 0:
            continue

        price_usd = total_quote_usd / total_base
        usd_value = swap.token_amount * price_usd

        priced.append(PricedSwap(
            wallet_address=swap.wallet_address,
            token_amount=swap.token_amount,
            timestamp=swap.timestamp,
            tx_hash=swap.tx_hash,
            price_usd=price_usd,
            usd_value=usd_value,
        ))

    return priced


def _parse_receipt_quote_flows(
    logs: list[dict],
    quote_configs: list[QuoteTokenConfig],
) -> dict[str, tuple[float, float]]:
    quote_addrs = {q.address: q for q in quote_configs}
    flows: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for log in logs:
        contract = log.get("address", "").lower()
        cfg = quote_addrs.get(contract)
        if not cfg:
            continue
        topics = log.get("topics", [])
        if len(topics) < 3 or topics[0] != TRANSFER_TOPIC:
            continue
        from_addr = "0x" + topics[1][-40:]
        to_addr = "0x" + topics[2][-40:]
        raw_amount = log.get("data", "0x0")
        amount = int(raw_amount, 16) / (10 ** cfg.decimals)

        flows[from_addr]["out"] += amount * cfg.to_usd
        flows[to_addr]["in"] += amount * cfg.to_usd

    return {addr: (f.get("in", 0), f.get("out", 0)) for addr, f in flows.items()}


def price_from_receipts(
    swaps: list[ClassifiedSwap],
    receipt_logs: dict[str, list[dict]],
    quote_configs: list[QuoteTokenConfig],
    is_buy: bool,
) -> list[PricedSwap]:
    base_by_key: dict[tuple[str, str], float] = defaultdict(float)
    for swap in swaps:
        base_by_key[(swap.tx_hash, swap.wallet_address)] += swap.token_amount

    priced: list[PricedSwap] = []
    for swap in swaps:
        logs = receipt_logs.get(swap.tx_hash)
        if not logs:
            continue
        wallet_flows = _parse_receipt_quote_flows(logs, quote_configs)
        inflow, outflow = wallet_flows.get(swap.wallet_address, (0, 0))
        net_usd = outflow - inflow if is_buy else inflow - outflow

        if net_usd <= 0:
            continue

        total_base = base_by_key.get((swap.tx_hash, swap.wallet_address), 0)
        if total_base <= 0:
            continue

        price_usd = net_usd / total_base
        usd_value = swap.token_amount * price_usd

        priced.append(PricedSwap(
            wallet_address=swap.wallet_address,
            token_amount=swap.token_amount,
            timestamp=swap.timestamp,
            tx_hash=swap.tx_hash,
            price_usd=price_usd,
            usd_value=usd_value,
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

        profit_abs_usd = total_sold_usd - total_bought_usd

        profit_pct = (
            (profit_abs_usd / total_bought_usd) * 100
            if total_bought_usd > 0
            else 0.0
        )

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


