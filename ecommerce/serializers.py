from rest_framework import serializers
from .models import Product, ProductSpecification, Order, OrderItem, Payment

import re

class ProductSpecificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSpecification
        fields = ("id", "name", "value")


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight: no description, no specifications."""

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "image",
            "category",
            "subcategory",
            "original_price",
            "price",
            "stock",
        )


class ProductDetailSerializer(serializers.ModelSerializer):
    # Served from the prefetch cache, so no extra query per product.
    specifications = ProductSpecificationSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "image",
            "image2",
            "image3",
            "image4",
            "category",
            "subcategory",
            "description",
            "original_price",
            "price",
            "stock",
            "created_at",
            "updated_at",
            "specifications",
        )
        
        
PHONE_RE = re.compile(r"\+?[0-9\s\-]{7,20}")
MAX_ITEMS = 50
MAX_QUANTITY = 100


class CheckoutSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=100)
    customer_email = serializers.EmailField()
    customer_phone = serializers.CharField(max_length=20)
    shipping_address = serializers.CharField()
    shipping_city = serializers.CharField(max_length=100)
    shipping_state = serializers.CharField(max_length=100)
    items = serializers.ListField(
        child=serializers.DictField(), allow_empty=False, max_length=MAX_ITEMS
    )
    referral_code = serializers.CharField(required=False, allow_blank=True)

    def validate_customer_phone(self, value):
        if not PHONE_RE.fullmatch(value):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    def validate_items(self, value):
        # Validated by hand (instead of a nested serializer) so the API returns
        # one clean, flat error message.
        error = (
            f"Each item needs a valid product_id and a quantity "
            f"between 1 and {MAX_QUANTITY}."
        )
        merged = {}
        for raw in value:
            try:
                product_id = int(raw.get("product_id"))
                quantity = int(raw.get("quantity"))
            except (TypeError, ValueError):
                raise serializers.ValidationError(error)

            if product_id < 1 or not 1 <= quantity <= MAX_QUANTITY:
                raise serializers.ValidationError(error)

            # Same product sent twice -> merge the quantities.
            merged[product_id] = merged.get(product_id, 0) + quantity

        if any(qty > MAX_QUANTITY for qty in merged.values()):
            raise serializers.ValidationError(error)

        return [{"product_id": pid, "quantity": qty} for pid, qty in merged.items()]


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = (
            "product_id",
            "product_name",
            "product_image",
            "unit_price",
            "quantity",
            "line_total",
        )


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("reference", "amount", "status", "authorization_url")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "order_number",
            "status",
            "payment_status",
            "customer_name",
            "customer_email",
            "customer_phone",
            "shipping_address",
            "shipping_city",
            "shipping_state",
            "subtotal",
            "referral_discount",
            "total",
            "created_at",
            "items",
        )
        


class OrderListSerializer(serializers.ModelSerializer):
    """Compact card for the 'My orders' list."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    total_quantity = serializers.SerializerMethodField()
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "order_number",
            "status",
            "status_label",
            "payment_status",
            "total",
            "created_at",
            "total_quantity",
            "items",
        )

    def get_total_quantity(self, obj):
        # Uses the prefetched items, so no extra query.
        return sum(item.quantity for item in obj.items.all())