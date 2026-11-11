from django.db import transaction
from rest_framework import serializers

from ecommerce.serializers import CheckoutSerializer

from .models import LabTest, LabTestFile, PrescriptionItem
from .validators import validate_lab_file_url

STATUS_LABELS = {
    "under_review": "Under Review",
    "prescription_ready": "Prescription Ready",
    "completed": "Completed",
    "rejected": "Rejected",
}


class LabTestCreateSerializer(serializers.Serializer):
    """Input for POST /lab-tests/. The frontend uploads to Cloudinary first, then sends the URL."""

    test_name = serializers.CharField(max_length=200)
    file_url = serializers.URLField(max_length=500, validators=[validate_lab_file_url])
    file_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    symptoms = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def create(self, validated_data):
        with transaction.atomic():
            lab_test = LabTest.objects.create(
                user=self.context["user"],
                test_name=validated_data["test_name"].strip(),
                symptoms=validated_data["symptoms"].strip(),
            )
            LabTestFile.objects.create(
                lab_test=lab_test,
                file_url=validated_data["file_url"],
                original_name=validated_data["file_name"],
            )
        return lab_test


class LabTestCheckoutSerializer(CheckoutSerializer):
    """Same delivery/contact fields as the normal checkout, but no items:
    the cart is built from the prescription on the server."""

    items = None


class LabTestFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabTestFile
        fields = ["id", "file_url", "original_name", "uploaded_at"]


class PrescriptionItemSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(source="product.name", read_only=True)
    unit_price = serializers.DecimalField(
        source="product.price", max_digits=12, decimal_places=2, read_only=True
    )
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = PrescriptionItem
        fields = [
            "id", "product_id", "name", "dosage_instructions",
            "quantity", "unit_price", "line_total",
        ]


class LabTestSerializer(serializers.ModelSerializer):
    """Used for both the list and the detail. Expects the queryset from selectors.lab_tests_for()."""

    status = serializers.CharField(source="display_status", read_only=True)
    status_label = serializers.SerializerMethodField()
    files = LabTestFileSerializer(many=True, read_only=True)
    prescription = serializers.SerializerMethodField()

    class Meta:
        model = LabTest
        fields = [
            "reference", "test_name", "symptoms", "status", "status_label",
            "created_at", "reviewed_at", "files", "prescription",
        ]

    def get_status_label(self, obj):
        return STATUS_LABELS.get(obj.display_status, obj.display_status)

    def get_prescription(self, obj):
        prescription = getattr(obj, "prescription", None)
        if prescription is None:
            return None
        order = prescription.order
        if order is not None and order.status == "cancelled":
            order = None  # a cancelled order can't be paid; the user can check out again
        return {
            "doctor_name": prescription.doctor_name,
            "doctor_note": prescription.doctor_note,
            "issued_at": prescription.issued_at,
            "items": PrescriptionItemSerializer(prescription.items.all(), many=True).data,
            "total": prescription.total,
            # Lets the frontend resume payment for an existing unpaid order.
            "order_number": order.order_number if order else None,
            "payment_status": order.payment_status if order else None,
        }