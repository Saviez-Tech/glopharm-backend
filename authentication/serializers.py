
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers

from .models import UserProfile
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import UserProfile
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from rest_framework_simplejwt.serializers import TokenRefreshSerializer


class RegisterSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=100)

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'password',
            'name',
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

    @transaction.atomic
    def create(self, validated_data):
        name = validated_data.pop('name')

        user = User.objects.create_user(
            **validated_data
        )

        UserProfile.objects.create(
            user=user,
            name=name
        )

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
