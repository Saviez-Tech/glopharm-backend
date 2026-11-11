from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from ecommerce.models import Order  # change to your orders app label

from . import config
from .models import PointsTransaction, RewardAccount
from ecommerce.utils import APIResponse  # adjust to wherever your APIResponse lives
from .serializers import CashbackSerializer, ReferredFriendSerializer
from .referalservice import get_or_create_account


def _money(value):
    return f"{Decimal(value):.2f}"


class RewardsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50

    def get_paginated_data(self, data):
        return {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        }


class ReferralSummaryView(APIView):
    """GET /referrals/summary/  -> the four stat cards + code + link + program rules."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        account = get_or_create_account(user)
        Reason = PointsTransaction.Reason

        stats = PointsTransaction.objects.filter(user=user).aggregate(
            referral_points=Coalesce(Sum("points", filter=Q(reason=Reason.REFERRAL_REWARD)), 0),
            referral_count=Count("id", filter=Q(reason=Reason.REFERRAL_REWARD)),
            cashback_points=Coalesce(Sum("points", filter=Q(reason=Reason.PURCHASE_CASHBACK)), 0),
            cashback_count=Count("id", filter=Q(reason=Reason.PURCHASE_CASHBACK)),
        )
        friends_invited = RewardAccount.objects.filter(referred_by=user).count()

        return APIResponse.success(
            message="Referral summary retrieved successfully.",
            data={
                "balance_points": account.points_balance,
                "balance_value": _money(account.points_balance * config.POINT_VALUE_NAIRA),
                "from_referrals": {
                    "points": stats["referral_points"],
                    "friends_purchased": stats["referral_count"],
                },
                "purchase_cashback": {
                    "points": stats["cashback_points"],
                    "orders": stats["cashback_count"],
                },
                "friends_invited": friends_invited,
                "referral_code": account.referral_code,
                "referral_link": f"{config.REFERRAL_LINK_BASE}{account.referral_code}",
                "program": {
                    "friend_discount": _money(config.REFERRED_FRIEND_DISCOUNT),
                    "referrer_reward_points": config.REFERRAL_REWARD_POINTS,
                    "referrer_reward_value": _money(
                        config.REFERRAL_REWARD_POINTS * config.POINT_VALUE_NAIRA
                    ),
                    "point_value_naira": _money(config.POINT_VALUE_NAIRA),
                    "redeem_at": "office",
                },
            },
        )


class ReferredFriendsView(APIView):
    """GET /referrals/friends/  -> friends who signed up with my code, newest first."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Everything is computed in the one query (no per-friend lookups).
        queryset = (
            RewardAccount.objects.filter(referred_by=user)
            .select_related("user", "user__userprofile")
            .annotate(
                has_order=Exists(
                    Order.objects.filter(user=OuterRef("user")).exclude(
                        status=Order.Status.CANCELLED
                    )
                ),
                has_delivered=Exists(
                    Order.objects.filter(user=OuterRef("user"), status=Order.Status.DELIVERED)
                ),
                reward_points=Subquery(
                    PointsTransaction.objects.filter(
                        user=user,
                        referred_user=OuterRef("user"),
                        reason=PointsTransaction.Reason.REFERRAL_REWARD,
                    ).values("points")[:1]
                ),
            )
        )

        paginator = RewardsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ReferredFriendSerializer(page, many=True)

        return APIResponse.success(
            message="Referred friends retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )


class CashbackListView(APIView):
    """GET /referrals/cashback/  -> points earned from my own delivered orders."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = PointsTransaction.objects.filter(
            user=request.user, reason=PointsTransaction.Reason.PURCHASE_CASHBACK
        ).select_related("order")

        paginator = RewardsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = CashbackSerializer(page, many=True)

        return APIResponse.success(
            message="Cashback history retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )