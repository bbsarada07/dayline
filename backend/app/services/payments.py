"""Payment providers (spec 5.8).

Only `demo` is implemented: it records `paid_demo` once the student has
confirmed, and no money moves. The UI labels this step
"Demo payment — no money moves".
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PaymentResult:
    status: str  # paid_demo (or, for a real provider, paid)
    reference: str


class PaymentProvider(Protocol):
    name: str

    def charge(self, amount_paise: int, description: str) -> PaymentResult:
        """Take payment for one item after the student confirmed it."""
        ...

    def refund(self, reference: str, amount_paise: int) -> None:
        """Give money back for a cancelled item."""
        ...


class DemoPaymentProvider:
    name = "demo"

    def charge(self, amount_paise: int, description: str) -> PaymentResult:
        return PaymentResult(status="paid_demo", reference=f"demo:{description}")

    def refund(self, reference: str, amount_paise: int) -> None:
        return None  # nothing was taken, so nothing to give back


class UpiPaymentProvider:
    """Not implemented. A real UPI integration needs:

    - a merchant account with a payment gateway (Razorpay, Cashfree, PhonePe PG...)
      and its API keys in .env, never in code;
    - charge() to create a gateway order and return a UPI intent / collect
      request; the item stays `unpaid` until the gateway confirms;
    - a webhook route that verifies the gateway's signature and only then marks
      the item paid (never trust the browser's word that it paid);
    - refund() to call the gateway's refund API, plus reconciliation for
      payments whose webhook never arrives.
    """

    name = "upi"

    def charge(self, amount_paise: int, description: str) -> PaymentResult:
        raise NotImplementedError("UPI payments are not set up. Use the demo provider.")

    def refund(self, reference: str, amount_paise: int) -> None:
        raise NotImplementedError("UPI payments are not set up. Use the demo provider.")


def provider() -> PaymentProvider:
    return DemoPaymentProvider()
