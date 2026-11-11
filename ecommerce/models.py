from django.db import models
import secrets
from django.conf import settings


class Product(models.Model):
    name = models.CharField(max_length=255)
    image = models.URLField(blank=True, null=True)
    image2 = models.URLField(blank=True, null=True)
    image3 = models.URLField(blank=True, null=True)
    image4 = models.URLField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    subcategory = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField()
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["-created_at", "-id"], name="product_created_idx"),
            models.Index(fields=["category", "subcategory"], name="product_category_idx"),
        ]

    def __str__(self):
        return self.name


class ProductSpecification(models.Model):
    # ForeignKey columns are indexed automatically by Django.
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="specifications",
    )
    name = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name}: {self.value}"




class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # created, awaiting payment
        PROCESSING = "processing", "Processing"  # paid, being prepared
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for Delivery"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    order_number = models.CharField(max_length=20, unique=True, editable=False)

    # Null for guest checkout. SET_NULL keeps the order if the account is deleted.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    # Customer + shipping snapshot (works for guests and logged-in users, and
    # stays correct even if the user later edits their profile).
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    shipping_address = models.TextField()
    shipping_city = models.CharField(max_length=100)
    shipping_state = models.CharField(max_length=100)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )

    # Money (goods only). total = subtotal - referral_discount.
    # The delivery fee is communicated to the customer separately and is not
    # part of the Paystack payment. Points are redeemed in the office, so they
    # never appear here.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    referral_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # "My orders" list (newest first) + status tabs.
            models.Index(fields=["user", "-created_at"], name="order_user_created_idx"),
            models.Index(fields=["user", "status"], name="order_user_status_idx"),
            models.Index(fields=["status", "-created_at"], name="order_status_created_idx"),
        ]

    def __str__(self):
        return f"#{self.order_number}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_order_number(cls):
        # e.g. GLO-482913. The unique constraint is the final guard against clashes.
        while True:
            number = f"GLO-{secrets.randbelow(900000) + 100000}"
            if not cls.objects.filter(order_number=number).exists():
                return number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")

    # Product may be deleted later; the order must still show what was bought.
    product = models.ForeignKey(
        Product, 
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )

    # Snapshots taken at purchase time (price/name can change afterwards).
    product_name = models.CharField(max_length=255)
    product_image = models.URLField(blank=True, null=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class OrderStatusHistory(models.Model):
    """One row per status change. Powers the 'Track Order' timeline modal."""

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_history"
    )
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "Order status history"

    def __str__(self):
        return f"{self.order.order_number}: {self.status}"


class Payment(models.Model):
    """
    One row per Paystack transaction attempt. An order can have several (e.g. the
    customer closed the payment page and retried), and a webhook for an older
    attempt still resolves to the right order.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    # PROTECT: financial records must never disappear with an order.
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    authorization_url = models.URLField(max_length=500)
    access_code = models.CharField(max_length=100, blank=True)
    gateway_response = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["order", "status"], name="payment_order_status_idx")]

    def __str__(self):
        return f"{self.reference} ({self.status})"