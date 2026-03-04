import os

from .base import TelephonyProvider
from .exotel import ExotelProvider
from .plivo import PlivoProvider


def get_provider() -> TelephonyProvider:
    provider = os.getenv("TELEPHONY_PROVIDER", "exotel").strip().lower()
    if provider == "plivo":
        return PlivoProvider()
    return ExotelProvider()
