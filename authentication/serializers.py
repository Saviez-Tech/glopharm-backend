
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers

from referrals.models import RewardAccount
from referrals.referalservice import set_referrer

from .models import UserProfile
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import UserProfile
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
import re
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


class RegisterSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=100)
    referral_code = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'password',
            'name',
            'referral_code',
        ]
        extra_kwargs = {
            'password': {
                'write_only': True,
                'min_length': 8,
            },
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )

        return value
    def validate_referral_code(self, value):
        value = value.strip().upper()
        if value and not RewardAccount.objects.filter(referral_code=value).exists():
            raise serializers.ValidationError("Invalid referral code.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        name = validated_data.pop('name')
        referral_code = validated_data.pop('referral_code', '')   

        user = User.objects.create_user(**validated_data)

        UserProfile.objects.create(user=user, name=name)

        if referral_code:                                          
            set_referrer(user, referral_code)

        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False
    )

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        users = User.objects.filter(email__iexact=email)

        # Require exactly one matching email.
        if users.count() != 1:
            raise AuthenticationFailed(
                "Invalid email or password."
            )

        user_record = users.first()

        user = authenticate(
            request=self.context.get('request'),
            username=user_record.username,
            password=password
        )

        if user is None:
            raise AuthenticationFailed(
                "Invalid email or password."
            )

        refresh = RefreshToken.for_user(user)

        name = UserProfile.objects.filter(
            user=user
        ).values_list('name', flat=True).first()

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "name": name,
            }
        }



class CustomTokenRefreshSerializer(TokenRefreshSerializer):

    def validate(self, attrs):
        data = super().validate(attrs)

        return {
            "access": data["access"],
            "refresh": data.get("refresh", attrs["refresh"])
        }




class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ("name", "phone_number", "address", "city", "state")

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_phone_number(self, value):
        if value is None:
            return value
        value = value.strip()
        if value and not re.fullmatch(r"\+?[0-9\s\-]{7,20}", value):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value


 
class ProfileDetailSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
 
    class Meta:
        model = UserProfile
        fields = ("username", "email", "name", "phone_number", "address", "city", "state")
 
 

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, attrs):
        user = self.context["request"].user

        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": ["New password must be different from the old password."]}
            )

        # Runs the validators configured in AUTH_PASSWORD_VALIDATORS.
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})

        return attrs
    


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class ResetPasswordSerializer(serializers.Serializer):
    otp = serializers.RegexField(
        regex=r"^\d{8}$",
        error_messages={
            "invalid": "OTP must be exactly 8 digits."
        }
    )

    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        min_length=8
    )
