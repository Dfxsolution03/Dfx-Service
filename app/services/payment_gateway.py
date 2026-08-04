"""
Payment gateway extension points — Module 10 (Payment Management Infrastructure).

NOTHING in this file calls an external API, requires an API key, or is wired
into any route or service in this codebase. It exists purely so that a real
gateway (Razorpay, Cashfree, Stripe, PhonePe, etc.) can be added later without
redesigning the Payment model or PaymentService.

Do not implement these classes as part of Module 10. Gateway integration,
webhook signature verification, and settlement logic are explicitly out of
scope until the client finalizes which gateway(s) to use.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class PaymentGatewayProvider(ABC):
    """
    Abstract interface a future concrete gateway adapter (e.g. RazorpayProvider,
    CashfreeProvider) would implement. No subclass exists yet.
    """

    @abstractmethod
    async def initiate_payment(
        self, *, amount: float, currency: str, payment_reference: str
    ) -> Dict[str, Any]:
        """Would create a payment session/order with the external gateway and
        return whatever the caller needs to redirect/render a checkout (e.g. an
        order ID or checkout URL). Not implemented — raises on call."""
        raise NotImplementedError(
            "No payment gateway is integrated yet. This is an extension point for a future module."
        )

    @abstractmethod
    async def verify_payment(self, *, gateway_transaction_id: str) -> Dict[str, Any]:
        """Would query the gateway to confirm a transaction's final status.
        Not implemented — raises on call."""
        raise NotImplementedError(
            "No payment gateway is integrated yet. This is an extension point for a future module."
        )


class PaymentWebhookHandler:
    """
    Placeholder for a future inbound webhook endpoint (e.g. POST /webhooks/payment-gateway).
    No route registers this handler anywhere in the API — adding one, along with
    signature verification and idempotency handling, is future work tied to
    whichever gateway is chosen.
    """

    async def handle_callback(self, payload: Dict[str, Any]) -> None:
        raise NotImplementedError(
            "Webhook handling is not implemented. This is an extension point for a future module."
        )
