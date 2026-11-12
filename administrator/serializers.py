
from rest_framework import serializers

from administrator.helper import edit_block_reason, initials, patient_name
from ecommerce.models import Order, OrderItem, Payment, Product, ProductSpecification
from django.db import transaction

from labtest.models import LabTest
from labtest.serializers import LabTestFileSerializer, PrescriptionItemSerializer


STATUS_LABELS = {
    "under_review": "Awaiting Review",
    "prescription_ready": "Prescribed",
    "completed": "Completed",
    "rejected": "Rejected",
}
ACTIONS = {
    "under_review": ("review", "Review & Prescribe"),
    "prescription_ready": ("edit", "View / Edit"),
    "completed": ("view", "View"),
    "rejected": ("view", "View"),
}
MAX_MEDICINES = 20

class ProductWriteSerializer(serializers.ModelSerializer):
    """Admin create/update. If `specifications` is sent, it replaces the existing list."""

    specifications = serializers.ListField(
        child=serializers.DictField(), required=False, max_length=50
    )

    class Meta:
        model = Product
        fields = (
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
            "specifications",
        )
        extra_kwargs = {
            "original_price": {"min_value": 0},
            "price": {"min_value": 0},
        }

    def validate_specifications(self, value):
        cleaned = []
        for raw in value:
            name = str(raw.get("name") or "").strip()
            spec_value = str(raw.get("value") or "").strip()
            if not name or not spec_value:
                raise serializers.ValidationError("Each specification needs a name and a value.")
            if len(name) > 100 or len(spec_value) > 255:
                raise serializers.ValidationError(
                    "A specification name (max 100) or value (max 255) is too long."
                )
            cleaned.append({"name": name, "value": spec_value})
        return cleaned

    def validate(self, attrs):
        # On a partial update, fall back to the saved values.
        original = attrs.get("original_price", getattr(self.instance, "original_price", None))
        price = attrs.get("price", getattr(self.instance, "price", None))
        if original is not None and price is not None and price > original:
            raise serializers.ValidationError("Price cannot be higher than the original price.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        specs = validated_data.pop("specifications", [])
        product = Product.objects.create(**validated_data)
        ProductSpecification.objects.bulk_create(
            [ProductSpecification(product=product, **spec) for spec in specs]
        )
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        specs = validated_data.pop("specifications", None)
        product = super().update(instance, validated_data)
        if specs is not None:
            product.specifications.all().delete()
            ProductSpecification.objects.bulk_create(
                [ProductSpecification(product=product, **spec) for spec in specs]
            )
        return product


class AdminOrderItemSerializer(serializers.ModelSerializer):
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


class AdminPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("reference", "amount", "status", "paid_at", "created_at")


class AdminOrderSerializer(serializers.ModelSerializer):
    """Full order for the admin table row + its expanded details."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    payment_status_label = serializers.CharField(
        source="get_payment_status_display", read_only=True
    )
    customer = serializers.SerializerMethodField()
    shipping = serializers.SerializerMethodField()
    items = AdminOrderItemSerializer(many=True, read_only=True)
    payments = AdminPaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "order_number",
            "created_at",
            "status",
            "status_label",
            "payment_status",
            "payment_status_label",
            "customer",
            "shipping",
            "items",
            "subtotal",
            "referral_discount",
            "total",
            "payments",
        )

    def get_customer(self, obj):
        return {
            "name": obj.customer_name,
            "email": obj.customer_email,
            "phone": obj.customer_phone,
            "is_guest": obj.user_id is None,
            "user_id": obj.user_id,
        }

    def get_shipping(self, obj):
        return {
            "address": obj.shipping_address,
            "city": obj.shipping_city,
            "state": obj.shipping_state,
        }


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)
    


class AdminLabTestListSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="display_status", read_only=True)
    status_label = serializers.SerializerMethodField()
    action = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    patient = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
 
    class Meta:
        model = LabTest
        fields = [
            "reference", "test_name", "patient", "created_at", "file",
            "status", "status_label", "action", "action_label",
        ]
 
    def get_status_label(self, obj):
        return STATUS_LABELS.get(obj.display_status, obj.display_status)
 
    def get_action(self, obj):
        return ACTIONS.get(obj.display_status, ("view", "View"))[0]
 
    def get_action_label(self, obj):
        return ACTIONS.get(obj.display_status, ("view", "View"))[1]
 
    def get_patient(self, obj):
        name = patient_name(obj.user)
        return {
            "id": obj.user_id,
            "name": name,
            "initials": initials(name),
            "email": getattr(obj.user, "email", ""),
        }
 
    def get_file(self, obj):
        first = next(iter(obj.files.all()), None)
        if first is None:
            return None
        return {"file_url": first.file_url, "original_name": first.original_name}
 
 
class AdminLabTestDetailSerializer(AdminLabTestListSerializer):
    files = LabTestFileSerializer(many=True, read_only=True)
    prescription = serializers.SerializerMethodField()
 
    class Meta(AdminLabTestListSerializer.Meta):
        fields = AdminLabTestListSerializer.Meta.fields + [
            "symptoms", "reviewed_at", "files", "prescription",
        ]
 
    def get_prescription(self, obj):
        prescription = getattr(obj, "prescription", None)
        if prescription is None:
            return None
        order = prescription.order
        reason = edit_block_reason(prescription)
        return {
            "doctor_name": prescription.doctor_name,
            "doctor_note": prescription.doctor_note,
            "issued_at": prescription.issued_at,
            "items": PrescriptionItemSerializer(prescription.items.all(), many=True).data,
            "total": prescription.total,
            "order": (
                {
                    "order_number": order.order_number,
                    "status": order.status,
                    "payment_status": order.payment_status,
                }
                if order
                else None
            ),
            "can_edit": reason is None,
            "edit_blocked_reason": reason,
        }
 
 
class PrescribeItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    dosage_instructions = serializers.CharField(max_length=255)
    quantity = serializers.IntegerField(min_value=1, max_value=100, default=1)
 
 
class PrescribeSerializer(serializers.Serializer):
    doctor_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    doctor_note = serializers.CharField(
        max_length=3000, required=False, allow_blank=True, default=""
    )
    items = PrescribeItemSerializer(many=True, allow_empty=False)
 
    def validate_items(self, items):
        if len(items) > MAX_MEDICINES:
            raise serializers.ValidationError(f"At most {MAX_MEDICINES} medicines per prescription.")
 
        merged = {}
        for item in items:  # same product twice -> one row, quantities added
            row = merged.setdefault(item["product_id"], dict(item, quantity=0))
            row["quantity"] += item["quantity"]
        if any(row["quantity"] > 100 for row in merged.values()):
            raise serializers.ValidationError("Quantity per medicine can't exceed 100.")
 
        found = set(Product.objects.filter(id__in=merged).values_list("id", flat=True))
        missing = sorted(set(merged) - found)
        if missing:
            raise serializers.ValidationError(f"Unknown product id(s): {missing}.")
        return list(merged.values())