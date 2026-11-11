from django.contrib import admin

from .models import PointsTransaction, RewardAccount


class ReadOnlyAdmin(admin.ModelAdmin):
    """Balances only change through the ledger (services.py), never by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RewardAccount)
class RewardAccountAdmin(ReadOnlyAdmin):
    list_display = ("user", "referral_code", "points_balance", "referred_by", "created_at")
    search_fields = ("referral_code", "user__username", "user__email")
    list_per_page = 50


@admin.register(PointsTransaction)
class PointsTransactionAdmin(ReadOnlyAdmin):
    list_display = ("user", "points", "reason", "order", "created_at")
    list_filter = ("reason", "created_at")
    search_fields = ("user__username", "user__email", "order__order_number")
    list_per_page = 50