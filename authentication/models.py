from django.db import models
from django.contrib.auth.models import User


# Create your models here.

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.user.username
    

class PasswordResetOTP(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="password_reset_otp"
    )

    otp_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Password reset OTP for {self.user.email}"

    class Meta:
        verbose_name = "Password Reset OTP"
        verbose_name_plural = "Password Reset OTPs"
