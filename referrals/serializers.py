from rest_framework import serializers

from .models import PointsTransaction, RewardAccount


class ReferredFriendSerializer(serializers.ModelSerializer):
    """
    Expects the queryset annotations from ReferredFriendsView:
    has_order, has_delivered, reward_points.
    """

    STATUS_LABELS = {
        "first_order_delivered": "First Order Delivered",
        "order_processing": "Order Processing",
        "account_created": "Account Created",
    }

    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    joined_at = serializers.DateTimeField(source="user.date_joined", read_only=True)
    status = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    points_earned = serializers.SerializerMethodField()

    class Meta:
        model = RewardAccount
        fields = ("name", "email", "joined_at", "status", "status_label", "points_earned")

    def get_name(self, obj):
        profile = getattr(obj.user, "userprofile", None)
        return (profile.name if profile else None) or obj.user.get_username()

    def _status(self, obj):
        if obj.has_delivered:
            return "first_order_delivered"
        if obj.has_order:
            return "order_processing"
        return "account_created"

    def get_status(self, obj):
        return self._status(obj)

    def get_status_label(self, obj):
        return self.STATUS_LABELS[self._status(obj)]

    def get_points_earned(self, obj):
        return obj.reward_points or 0


class CashbackSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(
        source="order.order_number", read_only=True, default=None
    )
    order_total = serializers.DecimalField(
        source="order.total", max_digits=12, decimal_places=2, read_only=True, default=None
    )

    class Meta:
        model = PointsTransaction
        fields = ("order_number", "order_total", "points", "created_at")