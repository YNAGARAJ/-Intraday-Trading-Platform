from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class SignalGenerated(_message.Message):
    __slots__ = ("signal_id", "symbol", "exchange", "direction", "confidence", "entry_price", "stop_loss", "target1", "target2", "atr", "confirming_indicators", "confirming_timeframes", "candlestick_pattern", "strategy_id", "generated_at_ms", "expires_at_ms", "regime")
    SIGNAL_ID_FIELD_NUMBER: _ClassVar[int]
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    EXCHANGE_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    ENTRY_PRICE_FIELD_NUMBER: _ClassVar[int]
    STOP_LOSS_FIELD_NUMBER: _ClassVar[int]
    TARGET1_FIELD_NUMBER: _ClassVar[int]
    TARGET2_FIELD_NUMBER: _ClassVar[int]
    ATR_FIELD_NUMBER: _ClassVar[int]
    CONFIRMING_INDICATORS_FIELD_NUMBER: _ClassVar[int]
    CONFIRMING_TIMEFRAMES_FIELD_NUMBER: _ClassVar[int]
    CANDLESTICK_PATTERN_FIELD_NUMBER: _ClassVar[int]
    STRATEGY_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_MS_FIELD_NUMBER: _ClassVar[int]
    REGIME_FIELD_NUMBER: _ClassVar[int]
    signal_id: str
    symbol: str
    exchange: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss: float
    target1: float
    target2: float
    atr: float
    confirming_indicators: _containers.RepeatedScalarFieldContainer[str]
    confirming_timeframes: _containers.RepeatedScalarFieldContainer[str]
    candlestick_pattern: str
    strategy_id: str
    generated_at_ms: int
    expires_at_ms: int
    regime: str
    def __init__(self, signal_id: _Optional[str] = ..., symbol: _Optional[str] = ..., exchange: _Optional[str] = ..., direction: _Optional[str] = ..., confidence: _Optional[float] = ..., entry_price: _Optional[float] = ..., stop_loss: _Optional[float] = ..., target1: _Optional[float] = ..., target2: _Optional[float] = ..., atr: _Optional[float] = ..., confirming_indicators: _Optional[_Iterable[str]] = ..., confirming_timeframes: _Optional[_Iterable[str]] = ..., candlestick_pattern: _Optional[str] = ..., strategy_id: _Optional[str] = ..., generated_at_ms: _Optional[int] = ..., expires_at_ms: _Optional[int] = ..., regime: _Optional[str] = ...) -> None: ...

class OrderIntent(_message.Message):
    __slots__ = ("signal_id", "symbol", "exchange", "side", "order_type", "quantity", "limit_price", "stop_loss", "target1", "target2", "position_size_pct", "risk_amount", "strategy_id", "client_order_id", "requested_at_ms", "is_priority")
    SIGNAL_ID_FIELD_NUMBER: _ClassVar[int]
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    EXCHANGE_FIELD_NUMBER: _ClassVar[int]
    SIDE_FIELD_NUMBER: _ClassVar[int]
    ORDER_TYPE_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_PRICE_FIELD_NUMBER: _ClassVar[int]
    STOP_LOSS_FIELD_NUMBER: _ClassVar[int]
    TARGET1_FIELD_NUMBER: _ClassVar[int]
    TARGET2_FIELD_NUMBER: _ClassVar[int]
    POSITION_SIZE_PCT_FIELD_NUMBER: _ClassVar[int]
    RISK_AMOUNT_FIELD_NUMBER: _ClassVar[int]
    STRATEGY_ID_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    IS_PRIORITY_FIELD_NUMBER: _ClassVar[int]
    signal_id: str
    symbol: str
    exchange: str
    side: str
    order_type: str
    quantity: int
    limit_price: float
    stop_loss: float
    target1: float
    target2: float
    position_size_pct: float
    risk_amount: float
    strategy_id: str
    client_order_id: str
    requested_at_ms: int
    is_priority: bool
    def __init__(self, signal_id: _Optional[str] = ..., symbol: _Optional[str] = ..., exchange: _Optional[str] = ..., side: _Optional[str] = ..., order_type: _Optional[str] = ..., quantity: _Optional[int] = ..., limit_price: _Optional[float] = ..., stop_loss: _Optional[float] = ..., target1: _Optional[float] = ..., target2: _Optional[float] = ..., position_size_pct: _Optional[float] = ..., risk_amount: _Optional[float] = ..., strategy_id: _Optional[str] = ..., client_order_id: _Optional[str] = ..., requested_at_ms: _Optional[int] = ..., is_priority: bool = ...) -> None: ...

class OrderFilled(_message.Message):
    __slots__ = ("signal_id", "order_id", "client_order_id", "symbol", "exchange", "status", "filled_quantity", "filled_price", "slippage_pct", "rejection_reason", "broker", "placed_at_ms", "filled_at_ms")
    SIGNAL_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    EXCHANGE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    FILLED_QUANTITY_FIELD_NUMBER: _ClassVar[int]
    FILLED_PRICE_FIELD_NUMBER: _ClassVar[int]
    SLIPPAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    REJECTION_REASON_FIELD_NUMBER: _ClassVar[int]
    BROKER_FIELD_NUMBER: _ClassVar[int]
    PLACED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    FILLED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    signal_id: str
    order_id: str
    client_order_id: str
    symbol: str
    exchange: str
    status: str
    filled_quantity: int
    filled_price: float
    slippage_pct: float
    rejection_reason: str
    broker: str
    placed_at_ms: int
    filled_at_ms: int
    def __init__(self, signal_id: _Optional[str] = ..., order_id: _Optional[str] = ..., client_order_id: _Optional[str] = ..., symbol: _Optional[str] = ..., exchange: _Optional[str] = ..., status: _Optional[str] = ..., filled_quantity: _Optional[int] = ..., filled_price: _Optional[float] = ..., slippage_pct: _Optional[float] = ..., rejection_reason: _Optional[str] = ..., broker: _Optional[str] = ..., placed_at_ms: _Optional[int] = ..., filled_at_ms: _Optional[int] = ...) -> None: ...

class RegimeChanged(_message.Message):
    __slots__ = ("regime", "confidence", "adx", "rsi", "vwap_deviation", "volume_delta", "vix", "classified_at_ms")
    REGIME_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    ADX_FIELD_NUMBER: _ClassVar[int]
    RSI_FIELD_NUMBER: _ClassVar[int]
    VWAP_DEVIATION_FIELD_NUMBER: _ClassVar[int]
    VOLUME_DELTA_FIELD_NUMBER: _ClassVar[int]
    VIX_FIELD_NUMBER: _ClassVar[int]
    CLASSIFIED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    regime: str
    confidence: float
    adx: float
    rsi: float
    vwap_deviation: float
    volume_delta: float
    vix: float
    classified_at_ms: int
    def __init__(self, regime: _Optional[str] = ..., confidence: _Optional[float] = ..., adx: _Optional[float] = ..., rsi: _Optional[float] = ..., vwap_deviation: _Optional[float] = ..., volume_delta: _Optional[float] = ..., vix: _Optional[float] = ..., classified_at_ms: _Optional[int] = ...) -> None: ...

class AgentHeartbeat(_message.Message):
    __slots__ = ("agent_name", "status", "timestamp_ms", "last_action")
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    LAST_ACTION_FIELD_NUMBER: _ClassVar[int]
    agent_name: str
    status: str
    timestamp_ms: int
    last_action: str
    def __init__(self, agent_name: _Optional[str] = ..., status: _Optional[str] = ..., timestamp_ms: _Optional[int] = ..., last_action: _Optional[str] = ...) -> None: ...

class KillSwitchActivated(_message.Message):
    __slots__ = ("trigger", "triggered_by", "daily_pnl_pct", "timestamp_ms")
    TRIGGER_FIELD_NUMBER: _ClassVar[int]
    TRIGGERED_BY_FIELD_NUMBER: _ClassVar[int]
    DAILY_PNL_PCT_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    trigger: str
    triggered_by: str
    daily_pnl_pct: float
    timestamp_ms: int
    def __init__(self, trigger: _Optional[str] = ..., triggered_by: _Optional[str] = ..., daily_pnl_pct: _Optional[float] = ..., timestamp_ms: _Optional[int] = ...) -> None: ...

class ReconciliationMismatch(_message.Message):
    __slots__ = ("symbol", "field", "internal_value", "broker_value", "detected_at_ms")
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    FIELD_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_VALUE_FIELD_NUMBER: _ClassVar[int]
    BROKER_VALUE_FIELD_NUMBER: _ClassVar[int]
    DETECTED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    symbol: str
    field: str
    internal_value: str
    broker_value: str
    detected_at_ms: int
    def __init__(self, symbol: _Optional[str] = ..., field: _Optional[str] = ..., internal_value: _Optional[str] = ..., broker_value: _Optional[str] = ..., detected_at_ms: _Optional[int] = ...) -> None: ...
