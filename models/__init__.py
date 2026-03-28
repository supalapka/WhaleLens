from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from models.wallet import Wallet
from models.transaction import Transaction
from models.alert import Alert
from models.transfer_cache import TransferCache
from models.receipt_cache import ReceiptCache
from models.wallet_detection import WalletDetection
from models.skipped_wallet import SkippedWallet
from models.ohlcv_cache import OhlcvCache
