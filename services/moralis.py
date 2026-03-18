import logging

import httpx

from config import settings
from models.constants import TRANSFER_TOPIC
from services.schemas import ERC20Transfer, RawLog
from models.constants import FACTORY_BY_CHAIN

logger = logging.getLogger(__name__)

API_BASE_URL = "https://deep-index.moralis.io/api/v2.2"
STREAMS_BASE_URL = "https://api.moralis-streams.com/streams/evm"
_decimals_cache: dict[str, int] = {}
SUPPORTED_CHAINS = ["0x1", "0x38", "0x2105", "0xa4b1"]


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.moralis_api_key,
        "Content-Type": "application/json",
    }


async def create_stream() -> str:
    body = {
        "webhookUrl": settings.webhook_url,
        "description": "WhaleLens wallet tracker",
        "tag": "whalelens",
        "chainIds": SUPPORTED_CHAINS,
        "includeNativeTxs": True,
        "includeContractLogs": True,
        "status": "active",
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(STREAMS_BASE_URL, headers=_headers(), json=body)
        if response.status_code != 200:
            logger.error("Moralis create_stream failed: %s %s", response.status_code, response.text)
            response.raise_for_status()
        stream_id = response.json()["id"]
    logger.info("Created Moralis stream: %s", stream_id)
    return stream_id


async def subscribe_addresses(stream_id: str, addresses: list[str]) -> dict:
    url = f"{STREAMS_BASE_URL}/{stream_id}/address"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_headers(), json={"address": addresses})
        response.raise_for_status()
        result = response.json()
    logger.info("Subscribed %d addresses to Moralis stream %s", len(addresses), stream_id)
    return result


async def get_token_decimals(token_address: str, chain_id: str) -> int:
    key = f"{chain_id}:{token_address.lower()}"
    if key in _decimals_cache:
        return _decimals_cache[key]

    url = f"{API_BASE_URL}/erc20/metadata"
    params = {"addresses[]": token_address, "chain": chain_id}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers(), params=params, timeout=10)

    if response.status_code != 200:
        logger.warning("Moralis metadata failed for %s, defaulting to 18 decimals", token_address)
        return 18

    items = response.json()
    if items and isinstance(items, list):
        decimals = int(items[0].get("decimals", 18))
    else:
        decimals = 18

    _decimals_cache[key] = decimals
    return decimals


async def fetch_tx_logs(tx_hash: str, chain_id: str, triggered_by: list[str]) -> list[RawLog]:
    url = f"{API_BASE_URL}/transaction/{tx_hash}"
    params = {"chain": chain_id}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers(), params=params, timeout=10)

    if response.status_code != 200:
        logger.warning("Moralis fetch_tx_logs failed for %s: %s", tx_hash, response.status_code)
        return []

    data = response.json()
    raw_logs = []
    logger.info("fetch_tx_logs %s: got %d logs", tx_hash[:10], len(data.get("logs", [])))
    for log in data.get("logs", []):
        raw_logs.append(RawLog(
            transactionHash=tx_hash,
            address=log.get("address", ""),
            topic0=log.get("topic0"),
            topic1=log.get("topic1"),
            topic2=log.get("topic2"),
            data=log.get("data", "0x"),
            triggered_by=triggered_by,
        ))
    return raw_logs


async def decode_logs_to_transfers(logs: list[RawLog], chain_id: str) -> list[ERC20Transfer]:
    transfers = []
    for log in logs:
        if log.topic0 != TRANSFER_TOPIC or not log.topic1 or not log.topic2:
            continue

        token_address = log.address.lower()
        from_addr = "0x" + log.topic1[-40:]
        to_addr = "0x" + log.topic2[-40:]
        raw_amount = int(log.data, 16) if log.data and log.data != "0x" else 0

        decimals = await get_token_decimals(token_address, chain_id)
        amount = raw_amount / (10 ** decimals)

        transfers.append(ERC20Transfer(
            transactionHash=log.transactionHash,
            contract=token_address,
            from_address=from_addr,
            to=to_addr,
            valueWithDecimals=str(amount),
            triggered_by=log.triggered_by,
        ))
    return transfers


async def create_pair_stream(chain_ids: list[str]) -> str:
    abi = [{
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "token0", "type": "address"},
            {"indexed": True, "name": "token1", "type": "address"},
            {"indexed": False, "name": "pair", "type": "address"},
            {"indexed": False, "name": "allPairsLength", "type": "uint256"},
        ],
        "name": "PairCreated",
        "type": "event",
    }]
    body = {
        "webhookUrl": settings.webhook_url.split("/webhook")[0] + "/webhook/pairs",
        "description": "WhaleLens new pair tracker",
        "tag": "whalelens-pairs",
        "chainIds": chain_ids,
        "includeContractLogs": True,
        "abi": abi,
        "topic0": ["0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"],
        "status": "active",
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(STREAMS_BASE_URL, headers=_headers(), json=body)
        if response.status_code != 200:
            logger.error("Moralis create_pair_stream failed: %s %s", response.status_code, response.text)
            response.raise_for_status()
        stream_id = response.json()["id"]

    factories = []

    for chain in chain_ids:
        factories += FACTORY_BY_CHAIN.get(chain, [])

    if not factories:
        raise ValueError("No factories configured for chains")

    url = f"{STREAMS_BASE_URL}/{stream_id}/address"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=_headers(),
            json={"address": factories}
        )
        response.raise_for_status()

    logger.info("Created pair stream: %s", stream_id)
    return stream_id


async def get_token_metadata(token_address: str, chain_id: str) -> dict | None:
    url = f"{API_BASE_URL}/erc20/metadata"
    params = {"addresses[]": token_address, "chain": chain_id}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers(), params=params, timeout=10)

    if response.status_code != 200:
        logger.warning("Moralis metadata failed for %s", token_address)
        return None

    items = response.json()
    if items and isinstance(items, list):
        return items[0]
    return None


async def delete_stream() -> None:
    url = f"{STREAMS_BASE_URL}/{settings.moralis_stream_id}"
    async with httpx.AsyncClient() as client:
        response = await client.delete(url, headers=_headers())
        response.raise_for_status()
    logger.info("Deleted Moralis stream: %s", settings.moralis_stream_id)
