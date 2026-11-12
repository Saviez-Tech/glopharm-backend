
import hashlib
import hmac
import secrets
import logging
from datetime import timedelta
from html import escape

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import PasswordResetOTP
from brevohelp import send_email

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 10
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 10


class PasswordResetError(Exception):
    pass


def generate_otp():
    return f"{secrets.randbelow(100_000_000):08d}"


def hash_otp(otp):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        otp.encode(),
        hashlib.sha256
    ).hexdigest()


def get_attempt_key(ip_address):
    ip_hash = hashlib.sha256(
        (ip_address or "unknown").encode()
    ).hexdigest()

    return f"password_reset_attempts:{ip_hash}"


def check_attempt_limit(ip_address):
    key = get_attempt_key(ip_address)
    attempts = cache.get(key, 0)

    if attempts >= MAX_ATTEMPTS:
        raise PasswordResetError(
            "Too many incorrect attempts. Please try again in 10 minutes."
        )


def record_failed_attempt(ip_address):
    key = get_attempt_key(ip_address)

    if not cache.add(key, 1, timeout=LOCKOUT_MINUTES * 60):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=LOCKOUT_MINUTES * 60)


def clear_failed_attempts(ip_address):
    cache.delete(get_attempt_key(ip_address))


def request_password_reset(email):
    """
    Generate an OTP and send it through Brevo.
    Returns False if the email cannot be sent.
    """

    users = list(
        __import__("django.contrib.auth.models", fromlist=["User"])
        .User.objects.filter(
            email__iexact=email,
            is_active=True
        )[:2]
    )

    # Avoid ambiguity if duplicate emails exist.
    if len(users) != 1:
        return True

    user = users[0]
    otp = generate_otp()

    otp_record, _ = PasswordResetOTP.objects.update_or_create(
        user=user,
        defaults={
            "otp_hash": hash_otp(otp),
            "expires_at": timezone.now() + timedelta(
                minutes=OTP_EXPIRY_MINUTES
            ),
            "attempts": 0,
            "used_at": None,
        }
    )

    name = escape(user.get_username())

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 30px;">
        <div style="max-width: 500px; margin: auto; background: white;
                    padding: 30px; border-radius: 10px;">

            <h2>Password Reset Request</h2>

            <p>Hello {name},</p>

            <p>We received a request to reset your Glopharm account password.</p>

            <p>Your verification code is:</p>

            <h1 style="letter-spacing: 8px; color: #167d45;">
                {otp}
            </h1>

            <p>This code expires in 10 minutes.</p>

            <p>If you did not request this password reset,
               please ignore this email.</p>

            <p>Regards,<br>Glopharm Team</p>

        </div>
    </body>
    </html>
    """

    result = send_email(
        to_email=user.email,
        to_name=name,
        subject="Glopharm Password Reset OTP",
        html_content=html_content
    )

    if result["status_code"] not in (200, 201, 202):
        logger.error(
            "Password reset email delivery failed for user ID %s",
            user.id
        )

        otp_record.delete()
        return False

    return True


@transaction.atomic
def reset_user_password(otp, new_password, ip_address):
    """
    Verify OTP and reset the user's password.
    """

    check_attempt_limit(ip_address)

    otp_digest = hash_otp(otp)

    otp_record = (
        PasswordResetOTP.objects
        .select_for_update()
        .select_related("user")
        .filter(
            otp_hash=otp_digest,
            used_at__isnull=True
        )
        .first()
    )

    if otp_record is None:
        record_failed_attempt(ip_address)
        raise PasswordResetError(
            "Invalid or expired OTP."
        )

    if otp_record.expires_at <= timezone.now():
        record_failed_attempt(ip_address)
        raise PasswordResetError(
            "Invalid or expired OTP."
        )

    user = otp_record.user

    if not user.is_active:
        raise PasswordResetError(
            "This account cannot reset its password."
        )

    try:
        password_validation.validate_password(
            new_password,
            user=user
        )
    except ValidationError as exc:
        raise PasswordResetError(
            " ".join(exc.messages)
        )

    user.set_password(new_password)
    user.save(update_fields=["password"])

    otp_record.used_at = timezone.now()
    otp_record.save(update_fields=["used_at"])

    clear_failed_attempts(ip_address)

    return user
