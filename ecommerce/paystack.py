"""
Paystack integration (thin client). Nothing in here touches the database.

Settings:
    PAYSTACK_SECRET_KEY    required  (sk_test_... / sk_live_...)
    PAYSTACK_CALLBACK_URL  optional  frontend page Paystack redirects to after payment
    PAYSTACK_BASE_URL      optional  default https://api.paystack.co
    PAYSTACK_TIMEOUT       optional  seconds, default 15
"""
import hashlib
import hmac
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

CURRENCY = "NGN"


class PaystackError(Exception):
    """Paystack was unreachable or rejected the request."""


def to_kobo(amount):
    """Naira (Decimal) -> kobo (int), rounded to the nearest kobo."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _secret_key():
    key = getattr(settings, "PAYSTACK_SECRET_KEY", None)
    if not key:
        raise ImproperlyConfigured("PAYSTACK_SECRET_KEY is not set.")
    return key


def _request(method, path, **kwargs):
    base_url = getattr(settings, "PAYSTACK_BASE_URL", "https://api.paystack.co")
    timeout = getattr(settings, "PAYSTACK_TIMEOUT", 15)

    try:
        response = requests.request(
            method,
            f"{base_url}{path}",
            headers={
                "Authorization": f"Bearer {_secret_key()}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            **kwargs,
        )
        body = response.json()
    except (requests.RequestException, ValueError):
        raise PaystackError("Could not reach Paystack.")

    if not response.ok or not body.get("status"):
        raise PaystackError(body.get("message") or "Paystack request failed.")

    return body["data"]


def initialize_transaction(*, email, amount, reference, callback_url=None, metadata=None):
    """
    Start a payment. `amount` is in naira. Returns Paystack's data dict, which
    includes `authorization_url` (send the customer there) and `access_code`.
    """
    payload = {
        "email": email,
        "amount": to_kobo(amount),
        "currency": CURRENCY,
        "reference": reference,
    }
    if callback_url:
        payload["callback_url"] = callback_url
    if metadata:
        payload["metadata"] = metadata

    return _request("POST", "/transaction/initialize", json=payload)


def verify_transaction(reference):
    """Ask Paystack for the real outcome of a transaction."""
    return _request("GET", f"/transaction/verify/{quote(reference, safe='')}")


def is_valid_webhook_signature(raw_body, signature):
    """Paystack signs the raw webhook body with HMAC-SHA512 using the secret key."""
    expected = hmac.new(_secret_key().encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature or "")