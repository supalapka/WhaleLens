import logging
import time

import httpx

from services.schemas import SecurityResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.gopluslabs.io/api/v1/token_security"
CACHE_TTL = 3600
_cache: dict[str, tuple[float, SecurityResult]] = {}

GOPLUS_CHAIN_MAP = {
    "ETH": "1",
    "BSC": "56",
    "BASE": "8453",
    "ARBITRUM": "42161",
    "POLYGON": "137",
    "OPTIMISM": "10",
}

FAIL_FLAGS = (
    "is_honeypot",
    "cannot_sell_all",
    "owner_change_balance",
    "slippage_modifiable",
    "hidden_owner",
    "can_take_back_ownership",
    "is_mintable",
    "transfer_pausable",
    "selfdestruct",
    "is_blacklisted",
    "personal_slippage_modifiable",
    "trading_cooldown",
    "anti_whale_modifiable",
)

TAX_THRESHOLD = 0.1
MIN_LIQUIDITY_USD = 10_000
MAX_CREATOR_PERCENT = 0.05
MAX_TOP_HOLDER_PERCENT = 0.20
MIN_LP_LOCK_PERCENT = 0.80
MIN_HOLDER_COUNT = 10

DEAD_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}


async def check_token_security(token_address: str, chain: str) -> SecurityResult | None:
    key = f"{token_address.lower()}:{chain}"
    if key in _cache:
        cached_at, cached_data = _cache[key]
        if time.monotonic() - cached_at < CACHE_TTL:
            logger.debug("GoPlus cache hit for %s on %s", token_address, chain)
            return cached_data
        del _cache[key]

    chain_id = GOPLUS_CHAIN_MAP.get(chain)
    if not chain_id:
        logger.error("Unsupported chain for GoPlus: %s", chain)
        return None

    url = f"{BASE_URL}/{chain_id}"
    params = {"contract_addresses": token_address.lower()}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)

    if response.status_code != 200:
        logger.error("GoPlus returned %s for %s on %s", response.status_code, token_address, chain)
        return None

    data = response.json()
    result = data.get("result", {})
    token_data = result.get(token_address.lower())
    if not token_data:
        logger.warning("No GoPlus data for %s on %s", token_address, chain)
        return None

    security = evaluate_security(token_data)
    _cache[key] = (time.monotonic(), security)
    return security


def _parse_tax(value) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _check_lp_lock(token_data: dict) -> tuple[bool, float]:
    lp_holders: list[dict] = token_data.get("lp_holders", [])
    if not lp_holders:
        return False, 0.0

    locked_percent = sum(
        _parse_float(h.get("percent"))
        for h in lp_holders
        if h.get("address", "").lower() in DEAD_ADDRESSES or h.get("is_locked") == 1
    )
    return locked_percent >= MIN_LP_LOCK_PERCENT, locked_percent


def _check_creator_token_percent(token_data: dict) -> float:
    return _parse_float(token_data.get("creator_percent"))


def _check_top_holder(token_data: dict) -> tuple[str | None, float]:
    holders: list[dict] = token_data.get("holders", [])
    real_holders = [
        h for h in holders
        if h.get("address", "").lower() not in DEAD_ADDRESSES
        and not h.get("is_contract")
    ]
    if not real_holders:
        return None, 0.0

    top = max(real_holders, key=lambda h: _parse_float(h.get("percent")))
    return top.get("address"), _parse_float(top.get("percent"))


def _check_liquidity(token_data: dict) -> float:
    dex_list: list[dict] = token_data.get("dex", [])
    return sum(_parse_float(d.get("liquidity")) for d in dex_list)


def evaluate_security(token_data: dict) -> SecurityResult:
    failed_checks: list[str] = []
    warnings: list[str] = []

    for flag in FAIL_FLAGS:
        if token_data.get(flag) == "1":
            failed_checks.append(flag)

    buy_tax = _parse_tax(token_data.get("buy_tax"))
    sell_tax = _parse_tax(token_data.get("sell_tax"))

    if buy_tax is None:
        failed_checks.append("buy_tax_unknown")
    elif buy_tax > TAX_THRESHOLD:
        failed_checks.append(f"buy_tax_high:{buy_tax * 100:.1f}pct")

    if sell_tax is None:
        failed_checks.append("sell_tax_unknown")
    elif sell_tax > TAX_THRESHOLD:
        failed_checks.append(f"sell_tax_high:{sell_tax * 100:.1f}pct")

    lp_locked, lp_locked_pct = _check_lp_lock(token_data)
    if not lp_locked:
        failed_checks.append(f"lp_not_locked:{lp_locked_pct * 100:.1f}pct_locked")

    creator_pct = _check_creator_token_percent(token_data)
    if creator_pct > MAX_CREATOR_PERCENT:
        failed_checks.append(f"creator_holds_tokens:{creator_pct * 100:.1f}pct")

    top_addr, top_pct = _check_top_holder(token_data)
    if top_pct > MAX_TOP_HOLDER_PERCENT:
        failed_checks.append(f"top_holder_concentration:{top_pct * 100:.1f}pct@{top_addr}")

    liquidity = _check_liquidity(token_data)
    if liquidity < MIN_LIQUIDITY_USD:
        failed_checks.append(f"low_liquidity:{liquidity:.0f}usd")

    holder_count = int(token_data.get("holder_count", 0))
    if holder_count < MIN_HOLDER_COUNT:
        warnings.append(f"low_holder_count:{holder_count}")

    if token_data.get("honeypot_with_same_creator") == "1":
        failed_checks.append("creator_has_honeypot_history")

    return SecurityResult(
        is_safe=len(failed_checks) == 0,
        failed_checks=failed_checks,
        warnings=warnings,
        buy_tax=buy_tax,
        sell_tax=sell_tax,
        liquidity_usd=liquidity,
        lp_locked_percent=lp_locked_pct,
        creator_token_percent=creator_pct,
        holder_count=holder_count,
    )