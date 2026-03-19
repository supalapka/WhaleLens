CHAIN_MAP: dict[str, str] = {
    "0x1": "ETH",
    "0x38": "BSC",
    "0x2105": "BASE",
    "0xa4b1": "ARBITRUM",
}

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

STABLECOINS: set[str] = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "0x6b175474e89094c44da98b954eedeac495271d0f",
    "0x55d398326f99059ff775485246999027b3197955",
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
    "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
    "0xff970a61a04b1ca14834a43f5de4533ebddb5cc8",
}

WRAPPED_NATIVE: set[str] = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
    "0x4200000000000000000000000000000000000006",
    "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
}

PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"


FACTORY_BY_CHAIN = {
    "0x38": ["0xca143ce32fe78f1f7019d7d551a6402fc5350c73"],  # PancakeSwap V2 (BSC)
    "0x2105": ["0x8909dc15e40173ff4699343b6eb8132c65e18ec6"],  # Uniswap V2 (Base)
    "0xa4b1": ["0xc35dadb65012ec5796536bd9864ed8773abc74c4"],  # SushiSwap V2 (Arbitrum)
}

KNOWN_TOKENS: set[str] = WRAPPED_NATIVE | STABLECOINS

WRAPPED_NATIVE_BY_CHAIN = {
    "0x38": "0xbb4cdb9cbd36b01bd1cbAEBF2De08d9173bc095c".lower(),  # WBNB
    "0x1": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2".lower(),   # WETH
    "0x2105": "0x4200000000000000000000000000000000000006".lower(), # WETH (Base)
    "0xa4b1": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1".lower(), # WETH (Arbitrum)
}

DEXSCREENER_TO_MORALIS_CHAIN: dict[str, str] = {
    "ethereum": "0x1",
    "bsc": "0x38",
    "base": "0x2105",
    "arbitrum": "0xa4b1",
}

DEXSCREENER_TO_GECKO_NETWORK: dict[str, str] = {
    "ethereum": "eth",
    "bsc": "bsc",
    "base": "base",
    "arbitrum": "arbitrum",
}