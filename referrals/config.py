"""
Referral & rewards settings. Override any of these in settings.py.
"""
from decimal import Decimal

from django.conf import settings

# 1 point = ₦5  (2,450 pts = ₦12,250, 500 pts = ₦2,500)
POINT_VALUE_NAIRA = Decimal(str(getattr(settings, "POINT_VALUE_NAIRA", 5)))

# Points the referrer earns when their friend's FIRST order is delivered.
REFERRAL_REWARD_POINTS = int(getattr(settings, "REFERRAL_REWARD_POINTS", 500))

# Discount (₦) a referred friend gets on their first purchase (used at checkout later).
REFERRED_FRIEND_DISCOUNT = Decimal(str(getattr(settings, "REFERRED_FRIEND_DISCOUNT", 1000)))

# % of the goods total given back as points when an order is delivered.
# PLACEHOLDER: set the real rate you want.
PURCHASE_CASHBACK_PERCENT = Decimal(str(getattr(settings, "PURCHASE_CASHBACK_PERCENT", 5)))

REFERRAL_LINK_BASE = getattr(settings, "REFERRAL_LINK_BASE", "https://glopharm.ng/ref/")