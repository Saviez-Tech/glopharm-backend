from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ecommerce.models import Order, Payment


class AdminRevenueChartDateFilterTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(admin)
        self.url = "/api/gload/dashboard/revenue-chart/"

    def create_paid_payment(self, paid_on, amount, reference):
        order = Order.objects.create(
            customer_name="Test Customer",
            customer_email=f"{reference}@example.com",
            customer_phone="123456789",
            shipping_address="1 Test Street",
            shipping_city="Test City",
            shipping_state="Test State",
            status=Order.Status.PROCESSING,
            payment_status=Order.PaymentStatus.PAID,
            subtotal=amount,
            referral_discount=Decimal("0.00"),
            total=amount,
        )
        Payment.objects.create(
            order=order,
            reference=reference,
            amount=amount,
            status=Payment.Status.SUCCESS,
            authorization_url="https://paystack.test/authorize",
            paid_at=timezone.make_aware(
                datetime.combine(paid_on, time(hour=12))
            ),
        )

    def create_order_on(self, created_on, reference):
        order = Order.objects.create(
            customer_name="Test Customer",
            customer_email=f"{reference}@example.com",
            customer_phone="123456789",
            shipping_address="1 Test Street",
            shipping_city="Test City",
            shipping_state="Test State",
            status=Order.Status.PENDING,
            payment_status=Order.PaymentStatus.UNPAID,
            subtotal=Decimal("10.00"),
            referral_discount=Decimal("0.00"),
            total=Decimal("10.00"),
        )
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.make_aware(datetime.combine(created_on, time(hour=12)))
        )
        order.refresh_from_db(fields=("created_at",))
        return order

    def test_selected_date_returns_only_one_daily_point(self):
        selected_date = date(2026, 6, 3)
        self.create_paid_payment(selected_date, Decimal("25.50"), "selected")
        self.create_paid_payment(
            date(2026, 6, 2), Decimal("10.00"), "previous-day"
        )
        self.create_paid_payment(
            date(2026, 6, 4), Decimal("15.00"), "next-day"
        )

        response = self.client.get(
            self.url,
            {"date": selected_date.isoformat(), "range": "year"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["range"], "day")
        self.assertEqual(data["total_revenue"], "25.50")
        self.assertEqual(data["total_transactions"], 1)
        self.assertEqual(
            data["points"],
            [
                {
                    "date": "2026-06-03",
                    "label": "Jun 3",
                    "revenue": "25.50",
                    "transactions": 1,
                }
            ],
        )

        stats_response = self.client.get(
            "/api/gload/dashboard/stats/",
            {"date": selected_date.isoformat()},
        )
        stats = stats_response.json()["data"]
        self.assertEqual(stats["range"], "day")
        self.assertEqual(stats["date"], selected_date.isoformat())
        self.assertEqual(stats["total_revenue"]["value"], data["total_revenue"])
        self.assertEqual(stats["total_transactions"]["value"], data["total_transactions"])

    def test_selected_date_with_no_payments_returns_zero_point(self):
        response = self.client.get(self.url, {"date": "2026-06-03"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["range"], "day")
        self.assertEqual(data["total_revenue"], "0.00")
        self.assertEqual(data["total_transactions"], 0)
        self.assertEqual(data["points"][0]["revenue"], "0.00")
        self.assertEqual(data["points"][0]["transactions"], 0)

    def test_invalid_selected_date_returns_bad_request(self):
        for value in ("2026-02-30", "2026-6-03", "not-a-date"):
            with self.subTest(date=value):
                response = self.client.get(self.url, {"date": value})
                self.assertEqual(response.status_code, 400)

    def test_existing_ranges_keep_their_response_shape(self):
        self.create_paid_payment(
            timezone.localdate(), Decimal("42.00"), "range-payment"
        )
        for chart_range, expected_points in (
            ("week", 7),
            ("month", 30),
            ("year", 12),
        ):
            with self.subTest(range=chart_range):
                response = self.client.get(self.url, {"range": chart_range})

                self.assertEqual(response.status_code, 200)
                data = response.json()["data"]
                self.assertEqual(data["range"], chart_range)
                self.assertEqual(len(data["points"]), expected_points)

                stats_response = self.client.get(
                    "/api/gload/dashboard/stats/",
                    {"range": chart_range},
                )
                stats = stats_response.json()["data"]
                self.assertEqual(stats["total_revenue"]["value"], data["total_revenue"])
                self.assertEqual(
                    stats["total_transactions"]["value"], data["total_transactions"]
                )

    def test_dashboard_cards_keep_all_time_values_without_a_filter(self):
        self.create_paid_payment(date(2020, 1, 1), Decimal("42.00"), "old-payment")

        stats_response = self.client.get("/api/gload/dashboard/stats/")

        self.assertEqual(stats_response.status_code, 200)
        stats = stats_response.json()["data"]
        self.assertEqual(stats["total_revenue"]["value"], "42.00")
        self.assertEqual(stats["total_transactions"]["value"], 1)

    def test_orders_list_can_be_filtered_to_a_specific_date(self):
        selected_order = self.create_order_on(date(2026, 6, 3), "selected-order")
        self.create_order_on(date(2026, 6, 2), "previous-order")
        self.create_order_on(date(2026, 6, 4), "next-order")

        response = self.client.get(
            "/api/gload/manage/orders/",
            {"date": "2026-06-03"},
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["order_number"], selected_order.order_number)

    def test_order_stats_use_the_same_specific_date_filter(self):
        self.create_order_on(date(2026, 6, 3), "selected-order")
        self.create_order_on(date(2026, 6, 2), "previous-order")
        self.create_order_on(date(2026, 6, 4), "next-order")

        response = self.client.get(
            "/api/gload/manage/orders/stats/",
            {"date": "2026-06-03"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["period"], {"filter": "date", "value": "2026-06-03"})
        self.assertEqual(data["total_orders"], 1)
