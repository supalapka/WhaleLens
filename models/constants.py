from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChainConfig:
    hex_id: str
    name: str
    short_name: str
    gecko_network: str
    wrapped_native: str
    factories: list[str] = field(default_factory=list)


CHAINS: list[ChainConfig] = [
    ChainConfig(
        hex_id="0x1",
        name="ethereum",
        short_name="ETH",
        gecko_network="eth",
        wrapped_native="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    ),
    ChainConfig(
        hex_id="0x38",
        name="bsc",
        short_name="BSC",
        gecko_network="bsc",
        wrapped_native="0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        factories=["0xca143ce32fe78f1f7019d7d551a6402fc5350c73"],
    ),
    ChainConfig(
        hex_id="0x2105",
        name="base",
        short_name="BASE",
        gecko_network="base",
        wrapped_native="0x4200000000000000000000000000000000000006",
        factories=["0x8909dc15e40173ff4699343b6eb8132c65e18ec6"],
    ),
    ChainConfig(
        hex_id="0xa4b1",
        name="arbitrum",
        short_name="ARBITRUM",
        gecko_network="arbitrum",
        wrapped_native="0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
        factories=["0xc35dadb65012ec5796536bd9864ed8773abc74c4"],
    ),
]

CHAIN_MAP: dict[str, str] = {c.hex_id: c.short_name for c in CHAINS}

CHAIN_BY_SHORT_NAME: dict[str, ChainConfig] = {c.short_name: c for c in CHAINS}

FACTORY_BY_CHAIN: dict[str, list[str]] = {
    c.hex_id: c.factories for c in CHAINS if c.factories
}

WRAPPED_NATIVE: set[str] = {c.wrapped_native for c in CHAINS}

WRAPPED_NATIVE_BY_CHAIN: dict[str, str] = {c.hex_id: c.wrapped_native for c in CHAINS}

DEXSCREENER_TO_CHAIN_HEX: dict[str, str] = {c.name: c.hex_id for c in CHAINS}

DEXSCREENER_TO_GECKO_NETWORK: dict[str, str] = {c.name: c.gecko_network for c in CHAINS}

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

STABLECOINS: dict[str, int] = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": 6,
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,
    "0x6b175474e89094c44da98b954eedeac495271d0f": 18,
    "0x55d398326f99059ff775485246999027b3197955": 18,
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": 18,
    "0xe9e7cea3dedca5984780bafc599bd69add087d56": 18,
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": 6,
    "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": 6,
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831": 6,
    "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8": 6,
}

KNOWN_TOKENS: set[str] = WRAPPED_NATIVE | set(STABLECOINS)

ALCHEMY_RPC_URLS: dict[str, str] = {
    "0x1": "https://eth-mainnet.g.alchemy.com/v2",
    "0x38": "https://bnb-mainnet.g.alchemy.com/v2",
    "0x2105": "https://base-mainnet.g.alchemy.com/v2",
}

AVG_BLOCK_TIME: dict[str, int] = {
    "0x1": 12,
    "0x38": 3,
    "0x2105": 2,
}
