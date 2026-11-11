from django.db.models import Prefetch, Q
from rest_framework.views import APIView

from .models import OrderItem, Product, ProductSpecification
from .pagination import StandardPagination
from .serializers import OrderListSerializer, ProductDetailSerializer, ProductListSerializer
from .utils import APIResponse, OrderPagination  
from rest_framework.permissions import AllowAny, IsAuthenticated
import json
from . import paystack
from .models import Order, Payment
from .paystack import PaystackError
from .utils import APIResponse  
from .serializers import CheckoutSerializer, OrderSerializer, PaymentSerializer
from .orderservice import (
    CheckoutError,
    cancel_order,
    confirm_payment,
    create_order,
    mark_payment_failed,
    start_payment,
)


class ProductListView(APIView):
    permission_classes = [AllowAny]  # Allow any user (authenticated or not) to access this view.
    """
    GET /products/
    Optional query params: category, subcategory, page, page_size
    """

    def get(self, request):
        # .only() fetches just the columns the list serializer needs
        # (skips the heavy description and extra image columns).
        queryset = Product.objects.only(*ProductListSerializer.Meta.fields)

        category = request.query_params.get("category")
        subcategory = request.query_params.get("subcategory")
        if category:
            queryset = queryset.filter(category=category)
        if subcategory:
            queryset = queryset.filter(subcategory=subcategory)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ProductListSerializer(page, many=True)

        return APIResponse.success(
            message="Products retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )


class ProductSearchView(APIView):
    
    permission_classes = [AllowAny] 
    """
    GET /products/search/?q=<text>
    Optional query params: category, subcategory, page, page_size

    Each word in q must match the name, category or subcategory
    (case-insensitive), so "red shoe" finds "Red Running Shoes".
    """

    MIN_QUERY_LENGTH = 2
    MAX_TERMS = 5

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()

        if len(query) < self.MIN_QUERY_LENGTH:
            return APIResponse.error(
                f"Search query must be at least {self.MIN_QUERY_LENGTH} characters.",
                status_code=400,
            )

        queryset = Product.objects.only(*ProductListSerializer.Meta.fields)

        for term in query.split()[: self.MAX_TERMS]:
            queryset = queryset.filter(
                Q(name__icontains=term)
                | Q(category__icontains=term)
                | Q(subcategory__icontains=term)
            )

        category = request.query_params.get("category")
        subcategory = request.query_params.get("subcategory")
        if category:
            queryset = queryset.filter(category=category)
        if subcategory:
            queryset = queryset.filter(subcategory=subcategory)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ProductListSerializer(page, many=True)

        return APIResponse.success(
            message="Search completed successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )


class ProductDetailView(APIView):
    """GET /products/<id>/  (includes specifications)"""
    
    permission_classes = [AllowAny] 

    def get(self, request, pk):
        # 2 queries total: one for the product, one for all its specifications.
        product = (
            Product.objects.prefetch_related(
                Prefetch(
                    "specifications",
                    queryset=ProductSpecification.objects.only(
                        "id", "product_id", "name", "value"
                    ),
                )
            )
            .filter(pk=pk)
            .first()
        )

        if product is None:
            return APIResponse.error("Product not found.", status_code=404)

        return APIResponse.success(
            message="Product retrieved successfully.",
            data=ProductDetailSerializer(product).data,
        )
        




class CheckoutView(APIView):
    """
    POST /orders/checkout/
    Open to guests and logged-in users. If a valid auth token is sent, the order
    is linked to that user (so they can track it); otherwise it is a guest order.
    Returns the order plus the Paystack link for the goods total.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)
        from referrals.referalservice import set_referrer  

        code = serializer.validated_data.get("referral_code")
        if code:
            if not request.user.is_authenticated:
                return APIResponse.error("Please log in or sign up to use a referral code.", status_code=400)
            if not set_referrer(request.user, code):
                return APIResponse.error("This referral code can't be applied to your account.", status_code=400)

        try:
            order = create_order(user=request.user, data=serializer.validated_data)
        except CheckoutError as exc:
            return APIResponse.error(exc.message, status_code=exc.status_code)

        try:
            payment = start_payment(order)
        except PaystackError:
            # Don't leave stock locked up behind an order nobody can pay for.
            cancel_order(order, note="Payment could not be started")
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


class PayOrderView(APIView):
    """
    POST /orders/<order_number>/pay/
    Gets a fresh Paystack link for an unpaid order (e.g. the customer closed the
    payment page). Logged-in owners need nothing extra; guests must send the
    email they ordered with: {"customer_email": "..."}.
    """

    permission_classes = [AllowAny]

    def post(self, request, order_number):
        order = Order.objects.filter(order_number=order_number).first()

        if order is None or not self._can_access(request, order):
            return APIResponse.error("Order not found.", status_code=404)

        if order.payment_status == Order.PaymentStatus.PAID:
            return APIResponse.error("This order has already been paid.", status_code=400)
        if order.status == Order.Status.CANCELLED:
            return APIResponse.error("This order was cancelled.", status_code=400)

        try:
            payment = start_payment(order)
        except PaystackError:
            return APIResponse.error(
                "We couldn't start your payment. Please try again.", status_code=502
            )

        return APIResponse.success(
            message="Payment link created.",
            data={"payment": PaymentSerializer(payment).data},
        )

    @staticmethod
    def _can_access(request, order):
        if request.user.is_authenticated and order.user_id == request.user.id:
            return True
        email = str(request.data.get("customer_email") or "").strip().lower()
        return bool(email) and email == order.customer_email.lower()


class VerifyPaymentView(APIView):
    """
    GET /orders/payment/verify/?reference=...
    The frontend calls this on the page Paystack redirects back to. It asks
    Paystack for the real result, so it never relies on the redirect itself.
    """

    permission_classes = [AllowAny]

    MESSAGES = {
        Payment.Status.SUCCESS: "Payment successful.",
        Payment.Status.FAILED: "Payment failed. You can try again.",
        Payment.Status.PENDING: "Payment is still pending.",
    }

    def get(self, request):
        reference = request.query_params.get("reference") or request.query_params.get("trxref")
        if not reference:
            return APIResponse.error("Payment reference is required.", status_code=400)

        payment = Payment.objects.select_related("order").filter(reference=reference).first()
        if payment is None:
            return APIResponse.error("Payment not found.", status_code=404)

        if payment.status == Payment.Status.PENDING:
            try:
                data = paystack.verify_transaction(reference)
            except PaystackError:
                return APIResponse.error(
                    "Could not verify payment right now. Please try again shortly.",
                    status_code=502,
                )

            if data.get("status") == "success":
                confirm_payment(reference, data)
            elif data.get("status") == "failed":
                mark_payment_failed(reference, data.get("gateway_response") or "")

            payment = Payment.objects.select_related("order").get(pk=payment.pk)

        return APIResponse.success(
            message=self.MESSAGES[payment.status],
            data={
                "reference": payment.reference,
                "payment_status": payment.status,
                "order_number": payment.order.order_number,
                "order_status": payment.order.status,
            },
        )


class PaystackWebhookView(APIView):
    """
    POST /orders/payment/webhook/
    Set this URL in your Paystack dashboard (Settings > API Keys & Webhooks).
    Paystack calls it server-to-server, so payments are confirmed even if the
    customer closes the browser before being redirected back.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # Read the raw body first: the signature is computed over the exact bytes.
        raw_body = request.body
        signature = request.headers.get("x-paystack-signature")

        if not paystack.is_valid_webhook_signature(raw_body, signature):
            return APIResponse.error("Invalid signature.", status_code=401)

        try:
            payload = json.loads(raw_body)
        except ValueError:
            return APIResponse.error("Invalid payload.", status_code=400)

        if payload.get("event") == "charge.success":
            data = payload.get("data") or {}
            reference = data.get("reference")
            if reference and Payment.objects.filter(reference=reference).exists():
                confirm_payment(reference, data)

        # Always 200 for valid, signed requests so Paystack stops retrying.
        return APIResponse.success(message="Webhook received.")
    
    


class OrderListView(APIView):
    """
    GET /orders/                     -> my orders, newest first
    GET /orders/?status=delivered    -> filter by status
    Logged-in users only; always scoped to the caller's own orders.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            Order.objects.filter(user=request.user)
            .only("id", "order_number", "status", "payment_status", "total", "created_at")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=OrderItem.objects.only(
                        "id",
                        "order_id",
                        "product_id",
                        "product_name",
                        "product_image",
                        "unit_price",
                        "quantity",
                    ),
                )
            )
        )

        status = request.query_params.get("status")
        if status:
            if status not in Order.Status.values:
                return APIResponse.error("Invalid status filter.", status_code=400)
            queryset = queryset.filter(status=status)

        paginator = OrderPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = OrderListSerializer(page, many=True)

        return APIResponse.success(
            message="Orders retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )
        



