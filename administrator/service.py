 
from django.utils import timezone

from django.db import transaction

from administrator.helper import edit_block_reason, patient_name
from labtest.models import LabTest, Prescription, PrescriptionItem


class PrescribeError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
 
 
def save_prescription(*, lab_test_id, admin_user, data):
    """Create or replace the prescription and mark the test Prescription Ready. Returns created?"""
    with transaction.atomic():
        lab_test = LabTest.objects.select_for_update().get(pk=lab_test_id)
        if lab_test.status == LabTest.Status.REJECTED:
            raise PrescribeError("This report was rejected, so it can't be prescribed.")
 
        prescription = Prescription.objects.select_for_update().filter(lab_test=lab_test).first()
        reason = edit_block_reason(prescription) if prescription else None
        if reason:
            raise PrescribeError(reason, status_code=409)
 
        doctor_name = (data.get("doctor_name") or "").strip() or patient_name(admin_user)
        created = prescription is None
        if created:
            prescription = Prescription.objects.create(
                lab_test=lab_test, doctor_name=doctor_name, doctor_note=data["doctor_note"]
            )
        else:
            prescription.doctor_name = doctor_name
            prescription.doctor_note = data["doctor_note"]
            prescription.order = None  # drop a cancelled order so the patient can check out again
            prescription.save(update_fields=["doctor_name", "doctor_note", "order"])
            prescription.items.all().delete()
 
        PrescriptionItem.objects.bulk_create(
            [
                PrescriptionItem(
                    prescription=prescription,
                    product_id=item["product_id"],
                    dosage_instructions=item["dosage_instructions"],
                    quantity=item["quantity"],
                )
                for item in data["items"]
            ]
        )
 
        lab_test.status = LabTest.Status.PRESCRIPTION_READY
        lab_test.reviewed_at = lab_test.reviewed_at or timezone.now()
        lab_test.save(update_fields=["status", "reviewed_at"])
        return created
 