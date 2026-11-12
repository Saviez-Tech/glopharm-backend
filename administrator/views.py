from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework.permissions import IsAdminUser

from administrator.filters import PeriodFilterError, apply_period_filter
from administrator.helper import admin_lab_tests, distinct_customers, paid_payments, stat_card, with_display_status,stock_status,TWO_PLACES
from administrator.service import PrescribeError, save_prescription
from ecommerce.models import Order, Product
from ecommerce.orderservice import cancel_order, update_order_status
from ecommerce.pagination import StandardPagination
from labtest.models import LabTest, Prescription
from labtest.serializers import STATUS_LABELS
from .serializers import  AdminLabTestDetailSerializer, AdminLabTestListSerializer, AdminOrderSerializer, OrderStatusUpdateSerializer, PrescribeSerializer, ProductWriteSerializer
from ecommerce.serializers import ProductDetailSerializer
from ecommerce.utils import APIResponse
from rest_framework.views import APIView

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from django.contrib.auth import get_user_model

from datetime import date, datetime, timedelta
from django.db.models.functions import Lower, TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
 
from ecommerce.models import Order, Payment, Product
from ecommerce.pagination import StandardPagination
from ecommerce.utils import APIResponse
 
AdminPermission = IsAdminUser  # swap for the permission class your other admin views use

class AdminProductStatsView(APIView):
    """GET /manage/products/stats/  (staff only) -> the four dashboard cards."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        # One query for all four numbers.
        stats = Product.objects.aggregate(
            total_products=Count("id"),
            in_stock=Count("id", filter=Q(stock__gt=0)),
            out_of_stock=Count("id", filter=Q(stock=0)),
            catalog_value=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("price") * F("stock"),
                        output_field=DecimalField(max_digits=20, decimal_places=2),
                    )
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            ),
        )

        return APIResponse.success(
            message="Product stats retrieved successfully.",
            data={
                "total_products": stats["total_products"],
                "in_stock": stats["in_stock"],
                "out_of_stock": stats["out_of_stock"],
                "catalog_value": f"{stats['catalog_value']:.2f}",
            },
        )


class AdminProductCreateView(APIView):
    """POST /manage/products/  (staff only)"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = ProductWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)

        product = serializer.save()
        return APIResponse.success(
            message="Product created successfully.",
            data=ProductDetailSerializer(product).data,
            status_code=201,
        )


class AdminProductDetailView(APIView):
    """
    PUT    /manage/products/<id>/  -> full update
    PATCH  /manage/products/<id>/  -> partial update (send only what changes)
    DELETE /manage/products/<id>/
    """

    permission_classes = [IsAdminUser]

    def _update(self, request, pk, partial):
        with transaction.atomic():
            # Row lock so an edit can't overwrite stock changed by a checkout at the same moment.
            product = Product.objects.select_for_update().filter(pk=pk).first()
            if product is None:
                return APIResponse.error("Product not found.", status_code=404)

            serializer = ProductWriteSerializer(product, data=request.data, partial=partial)
            if not serializer.is_valid():
                return APIResponse.validation_error(serializer.errors)
            product = serializer.save()

        return APIResponse.success(
            message="Product updated successfully.",
            data=ProductDetailSerializer(product).data,
        )

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def delete(self, request, pk):
        deleted, _ = Product.objects.filter(pk=pk).delete()
        if not deleted:
            return APIResponse.error("Product not found.", status_code=404)
        return APIResponse.success(message="Product deleted successfully.")
    
    
    






class AdminOrderPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_data(self, data):
        return {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        }


class AdminOrderStatsView(APIView):
    """
    GET /manage/orders/stats/   (staff only)
    Same date filters as the list: ?period= | ?date= | ?month= | ?year=
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            queryset, period = apply_period_filter(Order.objects.all(), request.query_params)
        except PeriodFilterError as exc:
            return APIResponse.error(str(exc), status_code=400)

        Status = Order.Status
        Pay = Order.PaymentStatus

        # One query for every number on the page.
        stats = queryset.aggregate(
            total_orders=Count("id"),
            # "Sold" = paid and not cancelled. Goods value only (no delivery fee).
            total_amount_sold=Coalesce(
                Sum("total", filter=Q(payment_status=Pay.PAID) & ~Q(status=Status.CANCELLED)),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
            # Paid orders still waiting to be shipped / delivered.
            orders_to_fulfil=Count(
                "id", filter=Q(status__in=[Status.PROCESSING, Status.OUT_FOR_DELIVERY])
            ),
            # Placed but not paid yet (stock is being held for these).
            awaiting_payment=Count("id", filter=Q(status=Status.PENDING, payment_status=Pay.UNPAID)),
            **{f"status_{value}": Count("id", filter=Q(status=value)) for value in Status.values},
        )

        return APIResponse.success(
            message="Order stats retrieved successfully.",
            data={
                "period": period,
                "total_orders": stats["total_orders"],
                "total_amount_sold": f"{stats['total_amount_sold']:.2f}",
                "orders_to_fulfil": stats["orders_to_fulfil"],
                "awaiting_payment": stats["awaiting_payment"],
                "by_status": {value: stats[f"status_{value}"] for value in Status.values},
            },
        )


class AdminOrderListView(APIView):
    """
    GET /manage/orders/   (staff only), newest first.

    Date filter (same as the cards): ?period= | ?date= | ?month= | ?year=
    Extra filters: ?status=  ?payment_status=  ?q= (order number, name, email, phone)
    Pagination:    ?page=  ?page_size=
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        params = request.query_params

        # 3 queries per page: orders, their items, their payments.
        queryset = Order.objects.prefetch_related("items", "payments")

        try:
            queryset, _ = apply_period_filter(queryset, params)
        except PeriodFilterError as exc:
            return APIResponse.error(str(exc), status_code=400)

        status = params.get("status")
        if status:
            if status not in Order.Status.values:
                return APIResponse.error("Invalid status filter.", status_code=400)
            queryset = queryset.filter(status=status)

        payment_status = params.get("payment_status")
        if payment_status:
            if payment_status not in Order.PaymentStatus.values:
                return APIResponse.error("Invalid payment_status filter.", status_code=400)
            queryset = queryset.filter(payment_status=payment_status)

        search = (params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(order_number__icontains=search)
                | Q(customer_name__icontains=search)
                | Q(customer_email__icontains=search)
                | Q(customer_phone__icontains=search)
            )

        paginator = AdminOrderPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = AdminOrderSerializer(page, many=True)

        return APIResponse.success(
            message="Orders retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )


# What an admin may change an order TO, from each current status.
ALLOWED_TRANSITIONS = {
    Order.Status.PENDING: {Order.Status.CANCELLED},  # unpaid; it moves on by itself once paid
    Order.Status.PROCESSING: {Order.Status.OUT_FOR_DELIVERY, Order.Status.DELIVERED},
    Order.Status.OUT_FOR_DELIVERY: {Order.Status.DELIVERED},
    Order.Status.DELIVERED: set(),
    Order.Status.CANCELLED: set(),
}


class AdminOrderStatusView(APIView):
    """
    PATCH /manage/orders/<order_number>/status/   (staff only)
    Body: {"status": "out_for_delivery", "note": "optional message for the customer"}

    Every change is added to the customer's Track Order timeline. Marking an order
    delivered credits the buyer's cashback and the referrer's reward (through
    update_order_status -> log_status_change -> award_delivery_rewards).
    """

    permission_classes = [IsAdminUser]

    def patch(self, request, order_number):
        serializer = OrderStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)

        new_status = serializer.validated_data["status"]
        note = serializer.validated_data.get("note", "").strip()

        with transaction.atomic():
            # Lock the row so two admins can't change the same order at once.
            order = Order.objects.select_for_update().filter(order_number=order_number).first()
            if order is None:
                return APIResponse.error("Order not found.", status_code=404)

            if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
                return APIResponse.error(
                    f"Cannot change an order from {order.get_status_display()} "
                    f"to {Order.Status(new_status).label}.",
                    status_code=400,
                )

            if new_status == Order.Status.CANCELLED:
                if order.payment_status != Order.PaymentStatus.UNPAID:
                    return APIResponse.error(
                        "Paid orders can't be cancelled here. Refund the customer first.",
                        status_code=400,
                    )
                # Cancels and puts the stock back.
                order = cancel_order(order, note=note or "Order cancelled")
            else:
                if order.payment_status != Order.PaymentStatus.PAID:
                    return APIResponse.error("This order hasn't been paid yet.", status_code=400)
                order = update_order_status(order, new_status, note)

        order = Order.objects.prefetch_related("items", "payments").get(pk=order.pk)
        return APIResponse.success(
            message="Order status updated successfully.",
            data=AdminOrderSerializer(order).data,
        )
        


class AdminLabTestStatsView(APIView):
    """GET /admin/lab-tests/stats/ -> the four dashboard cards."""
 
    permission_classes = [IsAdminUser]
 
    def get(self, request):
        counts = with_display_status(LabTest.objects.all()).aggregate(
            total_reports=Count("id"),
            awaiting_review=Count("id", filter=Q(display_status="under_review")),
            awaiting_payment=Count("id", filter=Q(display_status="prescription_ready")),
            dispensed=Count("id", filter=Q(display_status="completed")),
        )
 
        # Value of prescriptions issued but not yet paid, at current prices.
        pending = (
            Prescription.objects.filter(lab_test__status=LabTest.Status.PRESCRIPTION_READY)
            .exclude(order__payment_status=Order.PaymentStatus.PAID)
            .aggregate(
                total=Sum(
                    ExpressionWrapper(
                        F("items__quantity") * F("items__product__price"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
            )["total"]
            or Decimal("0.00")
        )
 
        return APIResponse.success(
            message="Lab test stats retrieved successfully.",
            data={
                "awaiting_review": counts["awaiting_review"],
                "awaiting_payment": {
                    "count": counts["awaiting_payment"],
                    "pending_amount": str(pending),
                },
                "dispensed": counts["dispensed"],
                "total_reports": counts["total_reports"],
            },
        )
 
 
class AdminLabTestListView(APIView):
    """
    GET /admin/lab-tests/                      -> every uploaded result, newest first
    Optional: ?status=under_review|prescription_ready|completed|rejected
              ?search=<reference, test name, patient name or email>
              ?page=&page_size=
    """
 
    permission_classes = [IsAdminUser]
    VALID_STATUSES = set(STATUS_LABELS)
 
    def get(self, request):
        queryset = admin_lab_tests()
 
        status = request.query_params.get("status")
        if status:
            if status not in self.VALID_STATUSES:
                return APIResponse.error("Invalid status filter.", status_code=400)
            queryset = queryset.filter(display_status=status)
 
        search = (request.query_params.get("search") or "").strip()
        if search:
            user_fields = {f.name for f in get_user_model()._meta.get_fields()}
            query = Q(reference__icontains=search) | Q(test_name__icontains=search)
            for field in ("email", "first_name", "last_name", "full_name", "name"):
                if field in user_fields:
                    query |= Q(**{f"user__{field}__icontains": search})
            queryset = queryset.filter(query)
 
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return APIResponse.success(
            message="Lab tests retrieved successfully.",
            data=paginator.get_paginated_data(AdminLabTestListSerializer(page, many=True).data),
        )
 
 
class AdminLabTestDetailView(APIView):
    """GET /admin/lab-tests/<reference>/ -> files, symptoms, patient and prescription (if any)."""
 
    permission_classes = [IsAdminUser]
 
    def get(self, request, reference):
        lab_test = admin_lab_tests().filter(reference=reference).first()
        if lab_test is None:
            return APIResponse.error("Lab test not found.", status_code=404)
        return APIResponse.success(
            message="Lab test retrieved successfully.",
            data=AdminLabTestDetailSerializer(lab_test).data,
        )
 
 
class AdminPrescribeView(APIView):
    """
    POST /admin/lab-tests/<reference>/prescription/   create the prescription
    PUT  /admin/lab-tests/<reference>/prescription/   edit it (replaces the medicines)
    Both do the same thing, so the frontend can use either. The test becomes
    "Prescription Ready" and the patient can buy it straight away.
    """
 
    permission_classes = [IsAdminUser]
 
    def post(self, request, reference):
        lab_test = LabTest.objects.filter(reference=reference).first()
        if lab_test is None:
            return APIResponse.error("Lab test not found.", status_code=404)
 
        serializer = PrescribeSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)
 
        try:
            created = save_prescription(
                lab_test_id=lab_test.pk, admin_user=request.user, data=serializer.validated_data
            )
        except PrescribeError as exc:
            return APIResponse.error(exc.message, status_code=exc.status_code)
 
        refreshed = admin_lab_tests().get(pk=lab_test.pk)
        return APIResponse.success(
            message="Prescription issued." if created else "Prescription updated.",
            data=AdminLabTestDetailSerializer(refreshed).data,
            status_code=201 if created else 200,
        )
 
    put = post



 
 
class AdminDashboardStatsView(APIView):
    """GET /admin/dashboard/stats/ -> the four top cards."""
 
    permission_classes = [AdminPermission]
 
    def get(self, request):
        week_ago = timezone.now() - timedelta(days=7)
        payments = paid_payments()
        before = Q(paid_at__lt=week_ago)
 
        totals = payments.aggregate(
            revenue=Sum("amount"),
            revenue_then=Sum("amount", filter=before),
            transactions=Count("id"),
            transactions_then=Count("id", filter=before),
        )
 
        data = {
            "total_revenue": stat_card(
                totals["revenue"] or 0, totals["revenue_then"] or 0, money=True
            ),
            "total_customers": stat_card(
                distinct_customers(payments), distinct_customers(payments.filter(before))
            ),
            "total_transactions": stat_card(
                totals["transactions"], totals["transactions_then"]
            ),
            "total_products": stat_card(
                Product.objects.count(),
                Product.objects.filter(created_at__lt=week_ago).count(),
            ),
        }
        return APIResponse.success(message="Dashboard stats retrieved successfully.", data=data)
 
 
class AdminPopularProductsView(APIView):
    """
    GET /admin/dashboard/popular-products/            -> top 5 by units sold
    GET /admin/dashboard/popular-products/?limit=10   -> top N (max 50)
    GET /admin/dashboard/popular-products/?all=true   -> everything sold, paginated ("Show All")
    Sales = units sold on paid orders.
    """
 
    permission_classes = [AdminPermission]
 
    @staticmethod
    def _row(product):
        status, label = stock_status(product.stock)
        return {
            "id": product.id,
            "name": product.name,
            "image": product.image,
            "price": str(product.price),
            "sales": product.sales,
            "stock": product.stock,
            "status": status,
            "status_label": label,
        }
 
    def get(self, request):
        queryset = (
            Product.objects.annotate(
                sales=Sum(
                    "order_items__quantity",
                    filter=Q(order_items__order__payment_status=Order.PaymentStatus.PAID),
                )
            )
            .filter(sales__gt=0)
            .order_by("-sales", "id")
            .only("id", "name", "image", "price", "stock")
        )
 
        if request.query_params.get("all") == "true":
            paginator = StandardPagination()
            page = paginator.paginate_queryset(queryset, request, view=self)
            data = paginator.get_paginated_data([self._row(p) for p in page])
        else:
            try:
                limit = min(max(int(request.query_params.get("limit", 5)), 1), 50)
            except ValueError:
                limit = 5
            data = {"results": [self._row(p) for p in queryset[:limit]]}
 
        return APIResponse.success(message="Popular products retrieved successfully.", data=data)
 
 
class AdminRevenueChartView(APIView):
    """
    GET /admin/dashboard/revenue-chart/?range=week|month|year   (default week)
      week  -> last 7 days, one point per day
      month -> last 30 days, one point per day
      year  -> last 12 months, one point per month
    Empty days/months are included as 0 so the chart has no gaps.
    """
 
    permission_classes = [AdminPermission]
 
    @staticmethod
    def _as_date(value):
        return value.date() if isinstance(value, datetime) else value
 
    def get(self, request):
        chart_range = request.query_params.get("range", "week")
        if chart_range not in ("week", "month", "year"):
            return APIResponse.error("range must be week, month or year.", status_code=400)
 
        today = timezone.localdate()
        if chart_range == "year":
            buckets = []
            for back in range(11, -1, -1):
                month_index = today.year * 12 + (today.month - 1) - back
                buckets.append(date(month_index // 12, month_index % 12 + 1, 1))
            trunc = TruncMonth("paid_at")
            label = lambda d: d.strftime("%b")
        else:
            days = 7 if chart_range == "week" else 30
            buckets = [today - timedelta(days=n) for n in range(days - 1, -1, -1)]
            trunc = TruncDate("paid_at")
            label = (lambda d: d.strftime("%a")) if chart_range == "week" else (
                lambda d: f"{d:%b} {d.day}"
            )
 
        rows = (
            paid_payments()
            .filter(paid_at__date__gte=buckets[0])
            .annotate(bucket=trunc)
            .values("bucket")
            .annotate(revenue=Sum("amount"), transactions=Count("id"))
        )
        by_bucket = {self._as_date(r["bucket"]): r for r in rows}
 
        points, total, transactions = [], Decimal("0.00"), 0
        for bucket in buckets:
            row = by_bucket.get(bucket)
            revenue = row["revenue"] if row else Decimal("0.00")
            count = row["transactions"] if row else 0
            total += revenue
            transactions += count
            points.append(
                {
                    "date": bucket.isoformat(),
                    "label": label(bucket),
                    "revenue": str(revenue.quantize(TWO_PLACES)),
                    "transactions": count,
                }
            )
 
        return APIResponse.success(
            message="Revenue chart retrieved successfully.",
            data={
                "range": chart_range,
                "total_revenue": str(total.quantize(TWO_PLACES)),
                "total_transactions": transactions,
                "points": points,
            },
        )
 