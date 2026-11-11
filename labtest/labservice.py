from collections import defaultdict

from django.db import transaction

from ecommerce.models import Order
from ecommerce.orderservice import CheckoutError, create_order

from .models import Prescription


def checkout_prescription(*, user, lab_test, delivery):
    """
    Turn a prescription into an order using the normal checkout (create_order), so
    stock locking, pricing and validation behave exactly like a regular purchase.

    Returns (order, created). `created` is False when an unpaid order already exists
    for this prescription and is being reused (the customer closed the payment page).

    The prescription row is locked, so a double-click can't create two orders.
    Doesn't call Paystack: the view does that outside this transaction.
    """
    with transaction.atomic():
        try:
            prescription = Prescription.objects.select_for_update().get(lab_test=lab_test)
        except Prescription.DoesNotExist:
            raise CheckoutError("No prescription is ready for this test.")

        items = list(prescription.items.all())
        if not items:
            raise CheckoutError("This prescription has no medicines yet.")

        existing = prescription.order
        if existing is not None:
            if existing.payment_status == Order.PaymentStatus.PAID:
                raise CheckoutError("This prescription has already been paid for.")
            if existing.status != Order.Status.CANCELLED:
                return existing, False  # unpaid and still open: just get a new payment link

        # Cart comes from the server. Merge duplicates, because create_order keeps
        # only the last quantity if the same product appears twice.
        cart = defaultdict(int)
        for item in items:
            cart[item.product_id] += item.quantity

        data = {
            **delivery,
            "items": [{"product_id": pid, "quantity": qty} for pid, qty in cart.items()],
        }
        order = create_order(user=user, data=data)

        prescription.order = order
        prescription.save(update_fields=["order"])
        return order, True