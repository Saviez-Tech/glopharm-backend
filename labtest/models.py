import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

# Point these at your shop app's models if the labels differ, e.g. in settings.py:
#   LABTESTS_PRODUCT_MODEL = "store.Product"
#   LABTESTS_ORDER_MODEL = "store.Order"
PRODUCT_MODEL = getattr(settings, "LABTESTS_PRODUCT_MODEL", "ecommerce.Product")
ORDER_MODEL = getattr(settings, "LABTESTS_ORDER_MODEL", "ecommerce.Order")

from .validators import validate_lab_file_url


class LabTest(models.Model):
    class Status(models.TextChoices):
        UNDER_REVIEW = "under_review", "Under Review"
        PRESCRIPTION_READY = "prescription_ready", "Prescription Ready"
        REJECTED = "rejected", "Rejected"

    reference = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lab_tests"
    )
    test_name = models.CharField(max_length=200)
    symptoms = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UNDER_REVIEW, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} - {self.test_name}"

    def save(self, *args, **kwargs):
        if not self.reference:
            # Temporary unique value, replaced with LAB-<id> once we have the pk.
            self.reference = f"TMP-{uuid.uuid4().hex[:12]}"
            super().save(*args, **kwargs)
            self.reference = f"LAB-{self.pk:03d}"
            kwargs.pop("force_insert", None)
            super().save(update_fields=["reference"])
        else:
            super().save(*args, **kwargs)


class LabTestFile(models.Model):
    """The report itself lives in Cloudinary (uploaded by the frontend); we only keep its URL."""

    lab_test = models.ForeignKey(LabTest, on_delete=models.CASCADE, related_name="files")
    file_url = models.URLField(max_length=500, validators=[validate_lab_file_url])
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name or self.file_url


class Prescription(models.Model):
    lab_test = models.OneToOneField(
        LabTest, on_delete=models.CASCADE, related_name="prescription"
    )
    doctor_name = models.CharField(max_length=120)
    doctor_note = models.TextField(blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    # Set when the user checks out; lets us derive "Completed" from the order.
    order = models.OneToOneField(
        ORDER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescription",
    )

    def __str__(self):
        return f"Prescription for {self.lab_test.reference}"

    @property
    def total(self):
        return sum(
            (item.line_total for item in self.items.all()), Decimal("0")
        )


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(PRODUCT_MODEL, on_delete=models.PROTECT, related_name="+")
    dosage_instructions = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.product} x{self.quantity}"

    @property
    def line_total(self):
        # Assumes Product has a `price` field. Adjust if yours is named differently.
        return self.product.price * self.quantity