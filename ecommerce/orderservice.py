import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Product 

from . import paystack
from .models import Order, OrderItem, OrderStatusHistory, Payment


class CheckoutError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- checkout


@transaction.atomic
def create_order(*, user, data):
    """
    Create an order and deduct stock atomically.

    Product rows are locked with SELECT ... FOR UPDATE, so two customers buying
    the last unit at the same moment can't both succeed. Locks are taken in id
    order so concurrent checkouts can't deadlock each other.
    """
    requested = {item["product_id"]: item["quantity"] for item in data["items"]}

    products = {
        product.id: product
        for product in Product.objects.select_for_update()
        .filter(id__in=requested.keys())
        .order_by("id")
        .only("id", "name", "image", "price", "stock")
    }

    if set(requested) - set(products):
        raise CheckoutError("Some products in your cart are no longer available.")

    # Check stock for everything before changing anything.
    for product_id in sorted(requested):
        product = products[product_id]
        quantity = requested[product_id]
        if product.stock < quantity:
            if product.stock == 0:
                message = f'"{product.name}" is out of stock.'
            else:
                message = f'Only {product.stock} of "{product.name}" left in stock.'
            raise CheckoutError(message, status_code=409)

    # Prices always come from the database, never from the client.
    subtotal = Decimal("0.00")
    order_items = []
    for product_id, quantity in requested.items():
        product = products[product_id]
        subtotal += product.price * quantity
        order_items.append(
            dict(
                product=product,
                product_name=product.name,
                product_image=product.image,
                unit_price=product.price,
                quantity=quantity,
            )
        )
        product.stock -= quantity

    order = Order.objects.create(
        user=user if user is not None and user.is_authenticated else None,
        customer_name=data["customer_name"],
        customer_email=data["customer_email"],
        customer_phone=data["customer_phone"],
        shipping_address=data["shipping_address"],
        shipping_city=data["shipping_city"],
        shipping_state=data["shipping_state"],
        subtotal=subtotal,
        total=subtotal,  # referral discount is wired in a later step
    )

    OrderItem.objects.bulk_create([OrderItem(order=order, **item) for item in order_items])
    Product.objects.bulk_update(products.values(), ["stock"])
    OrderStatusHistory.objects.create(
        order=order, status=Order.Status.PENDING, note="Order placed"
    )

    return order


@transaction.atomic
def cancel_order(order, note="Order cancelled"):
    """
    Cancel an unpaid, pending order and put its stock back. Does nothing if the
    order has already been paid or moved on, so it is safe to call defensively.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if (
        order.status != Order.Status.PENDING
        or order.payment_status != Order.PaymentStatus.UNPAID
    ):
        return order

    items = list(order.items.filter(product__isnull=False))
    products = {
        product.id: product
        for product in Product.objects.select_for_update()
        .filter(id__in=[item.product_id for item in items])
        .order_by("id")
        .only("id", "stock")
    }
    for item in items:
        products[item.product_id].stock += item.quantity
    Product.objects.bulk_update(products.values(), ["stock"])

    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(order=order, status=order.status, note=note)
    return order


# ----------------------------------------------------------------- payment


def start_payment(order):
    """
    Create a Paystack transaction for the order's total (goods only) and store it.
    Raises paystack.PaystackError if Paystack can't be reached. Deliberately NOT
    inside a DB transaction: no row locks are held during the network call.
    """
    reference = f"GLOPAY-{uuid.uuid4().hex[:20].upper()}"

    data = paystack.initialize_transaction(
        email=order.customer_email,
        amount=order.total,
        reference=reference,
        callback_url=getattr(settings, "PAYSTACK_CALLBACK_URL", None),
        metadata={"order_number": order.order_number},
    )

    return Payment.objects.create(
        order=order,
        reference=reference,
        amount=order.total,
        authorization_url=data["authorization_url"],
        access_code=data.get("access_code", ""),
    )


@transaction.atomic
def confirm_payment(reference, gateway_data):
    """
    Mark a payment successful and move the order forward. Idempotent: the verify
    endpoint and the webhook can both call it, in any order, any number of times.
    """
    payment = Payment.objects.select_for_update().get(reference=reference)
    if payment.status == Payment.Status.SUCCESS:
        return payment

    # Never trust the status alone; check Paystack really charged the right amount.
    if (
        gateway_data.get("amount") != paystack.to_kobo(payment.amount)
        or (gateway_data.get("currency") or paystack.CURRENCY) != paystack.CURRENCY
    ):
        payment.status = Payment.Status.FAILED
        payment.gateway_response = "Amount mismatch"
        payment.save(update_fields=["status", "gateway_response", "updated_at"])
        return payment

    payment.status = Payment.Status.SUCCESS
    payment.paid_at = timezone.now()
    payment.gateway_response = (gateway_data.get("gateway_response") or "")[:255]
    payment.save(update_fields=["status", "paid_at", "gateway_response", "updated_at"])

    order = Order.objects.select_for_update().get(pk=payment.order_id)

    if order.payment_status == Order.PaymentStatus.PAID:
        # Customer paid twice (e.g. an old payment link). Flag it for a refund.
        OrderStatusHistory.objects.create(
            order=order,
            status=order.status,
            note=f"Duplicate payment received ({reference}). Refund required.",
        )
    elif order.status == Order.Status.CANCELLED:
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=["payment_status", "updated_at"])
        OrderStatusHistory.objects.create(
            order=order,
            status=order.status,
            note=f"Payment received ({reference}) after cancellation. Refund or reinstate.",
        )
    else:
        order.payment_status = Order.PaymentStatus.PAID
        order.status = Order.Status.PROCESSING
        order.save(update_fields=["payment_status", "status", "updated_at"])
        OrderStatusHistory.objects.create(
            order=order, status=order.status, note="Payment confirmed"
        )

    return payment


def mark_payment_failed(reference, message=""):
    Payment.objects.filter(reference=reference, status=Payment.Status.PENDING).update(
        status=Payment.Status.FAILED,
        gateway_response=message[:255],
        updated_at=timezone.now(),
    )