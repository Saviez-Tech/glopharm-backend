from django.urls import path

from .views import CashbackListView, ReferralSummaryView, ReferredFriendsView

urlpatterns = [
    path("summary/", ReferralSummaryView.as_view(), name="referral-summary"),
    path("friends/", ReferredFriendsView.as_view(), name="referral-friends"),
    path("cashback/", CashbackListView.as_view(), name="referral-cashback"),
]