from decimal import Decimal
import random
import re

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from ecommerce.models import Order  # change to your orders app label

from . import config
from .models import PointsTransaction, RewardAccount

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class InsufficientPointsError(Exception):
    pass


# ------------------------------------------------------------ account + code


def _name_token(user):
    profile = getattr(user, "userprofile", None)
    name = (profile.name if profile else "") or user.get_username()
    first_word = (name.split() or [""])[0]
    token = re.sub(r"[^A-Za-z0-9]", "", first_word).upper()[:8]
    return token or "USER"


def _unique_code(user):
    # e.g. GLO-AMAKA-26 (name + 2-digit year); a short suffix is added on a clash.
    base = f"GLO-{_name_token(user)}-{timezone.now():%y}"
    code = base
    while RewardAccount.objects.filter(referral_code=code).exists():
        code = base + "".join(random.choices(CODE_ALPHABET, k=2))
    return code


def get_or_create_account(user, referred_by=None):
    account = RewardAccount.objects.filter(user=user).first()
    if account:
        return account

    for _ in range(3):
        try:
            with transaction.atomic():
                return RewardAccount.objects.create(
                    user=user,
                    referral_code=_unique_code(user),
                    referred_by=referred_by,
                )
        except IntegrityError:
            # Another request created it first (or the code clashed): look again.
            account = RewardAccount.objects.filter(user=user).first()
            if account:
                return account

    raise RuntimeError("Could not create a reward account.")


def attach_referrer(user, code):
    """
    Call right after a new user signs up, with the code they entered.
    Returns True if the referral was recorded. Invalid/own codes are ignored.
    """
    code = (code or "").strip().upper()
    if not code:
        return False

    referrer_account = RewardAccount.objects.filter(referral_code=code).first()
    if referrer_account is None or referrer_account.user_id == user.id:
        return False
    if RewardAccount.objects.filter(user=user).exists():
        return False  # a referrer can only be set when the account is first created

    account = get_or_create_account(user, referred_by=referrer_account.user)
    return account.referred_by_id == referrer_account.user_id


# ------------------------------------------------------------------- points


@transaction.atomic
def award_points(user, points, reason, *, order=None, referred_user=None, note=""):
    """
    Add points and write the ledger row together. Returns the transaction, or
    None if this exact reward was already given (the DB constraints make it safe
    to call more than once).
    """
    if points <= 0:
        return None

    account = get_or_create_account(user)

    try:
        with transaction.atomic():  # savepoint, so a duplicate doesn't break the outer transaction
            tx = PointsTransaction.objects.create(
                user=user,
                points=points,
                reason=reason,
                order=order,
                referred_user=referred_user,
                note=note,
            )
    except IntegrityError:
        return None

    RewardAccount.objects.filter(pk=account.pk).update(
        points_balance=F("points_balance") + points
    )
    return tx


@transaction.atomic
def award_delivery_rewards(order):
    """
    Call once an order's status becomes DELIVERED. Gives the buyer cashback and,
    if it is the buyer's first delivered order and they were referred, gives the
    referrer their reward. Guest orders earn nothing. Safe to call repeatedly.
    """
    if (
        order.user_id is None
        or order.status != Order.Status.DELIVERED
        or order.payment_status != Order.PaymentStatus.PAID
    ):
        return

    buyer = order.user
    Reason = PointsTransaction.Reason

    cashback = int(order.total * config.PURCHASE_CASHBACK_PERCENT / 100 / config.POINT_VALUE_NAIRA)
    award_points(buyer, cashback, Reason.PURCHASE_CASHBACK, order=order)

    account = get_or_create_account(buyer)
    if account.referred_by_id:
        is_first_delivery = not (
            Order.objects.filter(user_id=buyer.id, status=Order.Status.DELIVERED)
            .exclude(pk=order.pk)
            .exists()
        )
        if is_first_delivery:
            award_points(
                account.referred_by,
                config.REFERRAL_REWARD_POINTS,
                Reason.REFERRAL_REWARD,
                order=order,
                referred_user=buyer,
            )


@transaction.atomic
def redeem_points(user, points, note=""):
    """For staff (points are redeemed in the office, never used to pay online)."""
    if points <= 0:
        raise ValueError("points must be positive")

    account = RewardAccount.objects.select_for_update().filter(user=user).first()
    if account is None or account.points_balance < points:
        raise InsufficientPointsError("Not enough points.")

    tx = PointsTransaction.objects.create(
        user=user, points=-points, reason=PointsTransaction.Reason.REDEEMED, note=note
    )
    account.points_balance -= points
    account.save(update_fields=["points_balance"])
    return tx


@transaction.atomic
def set_referrer(user, code):
    """
    Link a user to the person whose code they used. Allowed only if they have no
    referrer yet and no real order yet. Returns True if it was applied.
    """
    code = (code or "").strip().upper()
    if not code:
        return False

    referrer_account = RewardAccount.objects.filter(referral_code=code).select_related("user").first()
    if referrer_account is None or referrer_account.user_id == user.id:
        return False

    account = get_or_create_account(user)
    account = RewardAccount.objects.select_for_update().get(pk=account.pk)

    if account.referred_by_id == referrer_account.user_id:
        return True  # same code sent again (a retry): already applied
    if account.referred_by_id:
        return False  # already referred by someone else
    if Order.objects.filter(user=user).exclude(status=Order.Status.CANCELLED).exists():
        return False

    account.referred_by = referrer_account.user
    account.save(update_fields=["referred_by"])
    return True


def get_first_purchase_discount(user, subtotal):
    """
    ₦ discount for a referred friend's first purchase, otherwise 0. Call it inside
    the checkout transaction: it locks the user's reward account so two
    simultaneous checkouts can't both claim the discount.
    """
    zero = Decimal("0.00")

    account = RewardAccount.objects.select_for_update().filter(user=user).first()
    if account is None or not account.referred_by_id:
        return zero
    if Order.objects.filter(user=user).exclude(status=Order.Status.CANCELLED).exists():
        return zero

    discount = config.REFERRED_FRIEND_DISCOUNT
    return discount if subtotal > discount else zero  # order must exceed the discount