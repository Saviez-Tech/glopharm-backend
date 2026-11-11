from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

# These live in your shop app. Change "ecommerce" if your app has a different name.
from ecommerce.pagination import StandardPagination
from ecommerce.orderservice import CheckoutError, cancel_order, start_payment
from ecommerce.paystack import PaystackError
from ecommerce.serializers import OrderSerializer, PaymentSerializer
from ecommerce.utils import APIResponse

from .selectors import VALID_STATUSES, lab_tests_for
from .serializers import LabTestCreateSerializer, LabTestSerializer

from .models import LabTest, Prescription
from .selectors import VALID_STATUSES, lab_tests_for
from .serializers import LabTestCheckoutSerializer, LabTestCreateSerializer, LabTestSerializer
from .labservice import checkout_prescription
 
 
class LabTestListCreateView(APIView):
    """
    GET  /lab-tests/                       -> my lab tests, newest first
    GET  /lab-tests/?status=prescription_ready
         (under_review | prescription_ready | completed | rejected)
    POST /lab-tests/                       -> submit a new lab result
         JSON: {"test_name", "file_url", "file_name"?, "symptoms"?}
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = lab_tests_for(request.user)

        status = request.query_params.get("status")
        if status:
            if status not in VALID_STATUSES:
                return APIResponse.error("Invalid status filter.", status_code=400)
            queryset = queryset.filter(display_status=status)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = LabTestSerializer(page, many=True)

        return APIResponse.success(
            message="Lab tests retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )

    def post(self, request):
        serializer = LabTestCreateSerializer(
            data=request.data, context={"user": request.user}
        )
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)

        lab_test = serializer.save()
        # Re-fetch through the selector so the response has the same shape as the list.
        lab_test = lab_tests_for(request.user).get(pk=lab_test.pk)

        return APIResponse.success(
            message="Lab result submitted. A doctor will review it shortly.",
            data=LabTestSerializer(lab_test).data,
            status_code=201,
        )


class LabTestDetailView(APIView):
    """GET /lab-tests/<reference>/  e.g. /lab-tests/LAB-041/  (owner only)"""

    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        # Scoped to the caller, so someone else's test is a plain 404.
        lab_test = lab_tests_for(request.user).filter(reference=reference).first()
        if lab_test is None:
            return APIResponse.error("Lab test not found.", status_code=404)

        return APIResponse.success(
            message="Lab test retrieved successfully.",
            data=LabTestSerializer(lab_test).data,
        )
        

 
class LabTestCheckoutView(APIView):
    """
    POST /lab-tests/<reference>/checkout/
    1-click buy for a prescription. Send only delivery/contact details; the items
    come from the prescription and prices from the product catalogue, never the client.
    Returns the order plus the Paystack link, like POST /orders/checkout/.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request, reference):
        lab_test = LabTest.objects.filter(user=request.user, reference=reference).first()
        if lab_test is None:
            return APIResponse.error("Lab test not found.", status_code=404)
        if lab_test.status != LabTest.Status.PRESCRIPTION_READY:
            return APIResponse.error(
                "There is no prescription ready for checkout on this test.", status_code=400
            )
 
        serializer = LabTestCheckoutSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)
 
        delivery = dict(serializer.validated_data)
        code = delivery.pop("referral_code", None)
        if code:
            from referrals.referalservice import set_referrer
 
            if not set_referrer(request.user, code):
                return APIResponse.error(
                    "This referral code can't be applied to your account.", status_code=400
                )
 
        try:
            order, created = checkout_prescription(
                user=request.user, lab_test=lab_test, delivery=delivery
            )
        except CheckoutError as exc:
            return APIResponse.error(exc.message, status_code=exc.status_code)
 
        try:
            payment = start_payment(order)
        except PaystackError:
            if created:
                # Don't leave stock locked behind an order nobody can pay for.
                cancel_order(order, note="Payment could not be started")
                Prescription.objects.filter(lab_test=lab_test).update(order=None)
            return APIResponse.error(
                "We couldn't start your payment. Please try again.", status_code=502
            )
 
        return APIResponse.success(
            message="Order placed successfully. Complete your payment to confirm it.",
            data={
                "order": OrderSerializer(order).data,
                "payment": PaymentSerializer(payment).data,
            },
            status_code=201,
        )
 