from django.apps import apps
from django.db.models import CharField, Case, F, Value, When

from .models import ORDER_MODEL, LabTest

VALID_STATUSES = {"under_review", "prescription_ready", "completed", "rejected"}


def lab_tests_for(user):
    """
    The user's lab tests with everything the dashboard needs in a fixed number of
    queries. `display_status` is the status the UI shows: a test is "completed"
    once its prescription's order is paid, otherwise it keeps its stored status.
    Derived here so "completed" can never drift out of sync with the order.
    """
    Order = apps.get_model(ORDER_MODEL)
    return (
        LabTest.objects.filter(user=user)
        .select_related("prescription", "prescription__order")
        .prefetch_related("files", "prescription__items__product")
        .annotate(
            display_status=Case(
                When(
                    prescription__order__payment_status=Order.PaymentStatus.PAID,
                    then=Value("completed"),
                ),
                default=F("status"),
                output_field=CharField(),
            )
        )
    )