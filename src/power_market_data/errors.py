"""Errors that callers can handle without knowing the source library."""


class PowerMarketDataError(Exception):
    """Base error for a failed request or invalid observation."""


class UnsupportedRequestError(PowerMarketDataError):
    """The requested product, date, or location is outside the contract."""


class UpstreamRequestError(PowerMarketDataError):
    """The source request failed or returned no observations."""


class SchemaError(PowerMarketDataError):
    """The upstream response does not have the expected structure."""


class ValidationError(PowerMarketDataError):
    """An observation violates the documented source/domain contract."""
