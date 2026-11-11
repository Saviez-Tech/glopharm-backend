from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import LabTest, LabTestFile, Prescription, PrescriptionItem


def mark_ready_if_has_items(prescription):
    """Flip the lab test to "Prescription Ready" once there is at least one medicine."""
    lab_test = prescription.lab_test
    if prescription.items.exists() and lab_test.status == LabTest.Status.UNDER_REVIEW:
        lab_test.status = LabTest.Status.PRESCRIPTION_READY
        lab_test.reviewed_at = timezone.now()
        lab_test.save(update_fields=["status", "reviewed_at"])


class LabTestFileInline(admin.TabularInline):
    model = LabTestFile
    extra = 0
    readonly_fields = ("uploaded_at",)


class PrescriptionInline(admin.StackedInline):
    """
    Write the prescription straight from the lab test page.
    Django can't nest inlines, so the medicines are added on the prescription's own
    page; the link below takes you there once the prescription is saved.
    """

    model = Prescription
    max_num = 1
    extra = 1
    can_delete = False
    fields = ("doctor_name", "doctor_note", "medicines")
    readonly_fields = ("medicines",)

    @admin.display(description="Medicines")
    def medicines(self, obj):
        if not obj or not obj.pk:
            return "Save this lab test first, then add the medicines here."
        opts = Prescription._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
        count = obj.items.count()
        label = f"Edit medicines ({count})" if count else "Add medicines"
        return format_html('<a class="button" href="{}">{}</a>', url, label)


@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ("reference", "test_name", "user", "status", "has_prescription", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "test_name", "user__email")
    readonly_fields = ("reference", "created_at")
    inlines = [LabTestFileInline, PrescriptionInline]

    @admin.display(boolean=True, description="Prescription")
    def has_prescription(self, obj):
        return Prescription.objects.filter(lab_test=obj).exists()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        prescription = Prescription.objects.filter(lab_test=form.instance).first()
        if prescription:
            mark_ready_if_has_items(prescription)


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 1
    raw_id_fields = ("product",)


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("lab_test", "doctor_name", "issued_at", "order")
    raw_id_fields = ("lab_test",)
    readonly_fields = ("order",)
    inlines = [PrescriptionItemInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        mark_ready_if_has_items(form.instance)