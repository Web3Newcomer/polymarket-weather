"""订单数据模型"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """订单类型"""
    FOK = "FOK"  # Fill-Or-Kill
    FAK = "FAK"  # Fill-And-Kill
    GTC = "GTC"  # Good-Til-Cancelled
    GTD = "GTD"  # Good-Til-Date


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    LIVE = "live"
    MATCHED = "matched"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OrderRequest:
    """订单请求"""
    token_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    order_type: OrderType = OrderType.FOK


@dataclass
class Order:
    """订单"""
    id: str
    token_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    status: OrderStatus
    order_type: OrderType
    filled_size: Decimal = Decimal("0")
