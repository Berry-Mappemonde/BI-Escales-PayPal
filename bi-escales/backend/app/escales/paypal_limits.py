"""A Captain chat turn has at most three PayPal resource attempts, excluding OAuth."""
from dataclasses import dataclass, field
import threading
from typing import Any


class PayPalCallLimitExceeded(RuntimeError):
    pass


@dataclass
class PayPalCallBudget:
    remaining: int = 3
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def consume(self) -> None:
        with self._lock:
            if self.remaining <= 0:
                raise PayPalCallLimitExceeded("PayPal read limit reached for this turn (3 calls)")
            self.remaining -= 1
