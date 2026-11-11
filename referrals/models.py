from django.conf import settings
from django.db import models
from django.db.models import Q


class RewardAccount(models.Model):
    """
    One per user: their referral code, who referred them, and their points balance.
    Lives in its own table so the existing UserProfile does not need to change.
    Created lazily the first time it is needed.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reward_account"
    )
    referral_code = models.CharField(max_length=30, unique=True)
    # The user whose code this person signed up with (null = organic signup).
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referred_accounts",
    )
    # Always changed together with a PointsTransaction row (see services.py).
    points_balance = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.referral_code} ({self.points_balance} pts)"


class PointsTransaction(models.Model):
    """Ledger: every balance change is a row here. Positive = earned, negative = redeemed."""

    class Reason(models.TextChoices):
        REFERRAL_REWARD = "referral_reward", "Referral reward"
        PURCHASE_CASHBACK = "purchase_cashback", "Purchase cashback"
        REDEEMED = "redeemed", "Redeemed"
        ADJUSTMENT = "adjustment", "Adjustment"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="points_transactions"
    )
    points = models.IntegerField()
    reason = models.CharField(max_length=30, choices=Reason.choices)
    order = models.ForeignKey(
        "ecommerce.Order",  
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="points_transactions",
    )
    # For referral rewards: the friend whose order triggered it.
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "reason", "-created_at"], name="points_user_reason_idx"),
        ]
        constraints = [
            # An order can only ever earn cashback / a referral reward once per user.
            models.UniqueConstraint(
                fields=["user", "order", "reason"],
                condition=Q(reason__in=["referral_reward", "purchase_cashback"]),
                name="unique_points_per_order_reason",
            ),
            # A referrer is rewarded only once per referred friend.
            models.UniqueConstraint(
                fields=["user", "referred_user"],
                condition=Q(reason="referral_reward"),
                name="unique_referral_reward_per_friend",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.points:+d} ({self.reason})"