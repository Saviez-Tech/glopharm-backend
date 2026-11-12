from decimal import Decimal
 
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import (
    Case, CharField, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When,
)
from django.db.models.functions import Lower

from ecommerce.models import Order, Payment
from labtest.models import LabTest

 
LOW_STOCK_THRESHOLD = 10  # at or below this a product shows as "Low Stock"
TWO_PLACES = Decimal("0.01")
 
 

def with_display_status(queryset):
    """
    The status the dashboard shows. "completed" = the prescription's order is paid,
    otherwise the stored status. Same rule as the patient API, so counts never disagree.
    """
    return queryset.annotate(
        display_status=Case(
            When(
                prescription__order__payment_status=Order.PaymentStatus.PAID,
                then=Value("completed"),
            ),
            default=F("status"),
            output_field=CharField(),
        )
    )
 
 
def admin_lab_tests():
    return with_display_status(
        LabTest.objects.select_related("user", "prescription", "prescription__order")
        .prefetch_related("files", "prescription__items__product")
    )
 
 
def patient_name(user):
    full = getattr(user, "get_full_name", None)
    name = (full() if callable(full) else "") or getattr(user, "full_name", "") or getattr(user, "name", "")
    return (name or "").strip() or getattr(user, "email", "") or str(user)
 
 
def initials(name):
    parts = name.replace("@", " ").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"
 
 
def edit_block_reason(prescription):
    """Why a prescription can't be edited any more, or None if it can."""
    order = prescription.order if prescription else None
    if order is None or order.status == Order.Status.CANCELLED:
        return None
    if order.payment_status == Order.PaymentStatus.PAID:
        return "This prescription has been paid for and can no longer be edited."
    return (
        "The patient has already started checkout for this prescription. "
        "Cancel the order first if you need to change it."
    )


def paid_payments():
    """Money actually received: successful Paystack payments on orders marked paid."""
    return Payment.objects.filter(
        status=Payment.Status.SUCCESS, order__payment_status=Order.PaymentStatus.PAID
    )
 
 
def distinct_customers(queryset):
    """Unique buyers (by email, so guests count too)."""
    return (
        queryset.annotate(buyer=Lower("order__customer_email")).values("buyer").distinct().count()
    )
 
 
def stat_card(now, then, money=False):
    """
    `now` is the all-time total; `then` is the same total as it stood a week ago.
    change_percent is how much the total grew over that week (null if there was
    nothing a week ago to compare with).
    """
    now, then = Decimal(now), Decimal(then)
    change = round(float((now - then) / then * 100), 1) if then else None
    if not change:
        trend = "flat"
    else:
        trend = "up" if change > 0 else "down"
    return {
        "value": str(now.quantize(TWO_PLACES)) if money else int(now),
        "change_percent": change,
        "trend": trend,
    }
 
 
def stock_status(stock):
    if stock <= 0:
        return "danger", "Out of Stock"
    if stock <= LOW_STOCK_THRESHOLD:
        return "warning", "Low Stock"
    return "success", "In Stock"
 
 