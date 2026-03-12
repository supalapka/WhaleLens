import logging

import httpx

from services.schemas import SecurityResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.gopluslabs.io/api/v1/token_security"

GOPLUS_CHAIN_MAP = {
    "ETH": "1",
    "BSC": "56",
    "BASE": "8453",
    "ARBITRUM": "42161",
    "POLYGON": "137",
    "OPTIMISM": "10",
}

FAIL_FLAGS = ("is_honeypot", "cannot_sell_all", "owner_change_balance", "slippage_modifiable")
TAX_THRESHOLD = 0.1


async def check_token_security(token_address: str, chain: str) -> SecurityResult | None:
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

    return evaluate_security(token_data)


def _parse_tax(value) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def evaluate_security(token_data: dict) -> SecurityResult:
    failed_checks: list[str] = []

    for flag in FAIL_FLAGS:
        if token_data.get(flag) == "1":
            failed_checks.append(flag)

    buy_tax = _parse_tax(token_data.get("buy_tax"))
    sell_tax = _parse_tax(token_data.get("sell_tax"))

    if buy_tax is None:
        failed_checks.append("buy_tax_unknown")
    elif buy_tax > TAX_THRESHOLD:
        failed_checks.append("buy_tax")

    if sell_tax is None:
        failed_checks.append("sell_tax_unknown")
    elif sell_tax > TAX_THRESHOLD:
        failed_checks.append("sell_tax")

    return SecurityResult(
        is_safe=len(failed_checks) == 0,
        failed_checks=failed_checks,
        buy_tax=buy_tax,
        sell_tax=sell_tax,
    )