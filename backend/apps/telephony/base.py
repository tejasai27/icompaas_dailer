from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DialRequest:
    lead_id: int
    to_number: str
    from_number: str
    callback_url: str
    caller_id: str | None = None
    metadata: dict | None = None
    max_duration_seconds: int | None = None


@dataclass
class DialResponse:
    provider_call_id: str
    accepted: bool
    raw: dict


@dataclass
class WebhookEvent:
    provider_call_id: str
    event_type: str
    amd_result: str | None
    raw: dict


class TelephonyProvider(ABC):
    @abstractmethod
    def initiate_call(self, request: DialRequest) -> DialResponse:
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(self, payload: dict) -> WebhookEvent:
        raise NotImplementedError

    @abstractmethod
    def hangup(self, provider_call_id: str) -> None:
        raise NotImplementedError
