
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status

from authentication.passwordreset import PasswordResetError, request_password_reset, reset_user_password
from .serializers import ForgotPasswordSerializer, ProfileDetailSerializer, RegisterSerializer,ChangePasswordSerializer, ResetPasswordSerializer, UserProfileSerializer
from .utils import APIResponse
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import LoginSerializer
from .serializers import CustomTokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth import update_session_auth_hash
from rest_framework.permissions import IsAuthenticated
from .models import UserProfile

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        return APIResponse.success(
            message="Account created successfully.",
            data={
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "name": user.userprofile.name,
            },
            status_code=status.HTTP_201_CREATED
        )


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return APIResponse.success(
            message="Login successful.",
            data=serializer.validated_data,
            status_code=200
        )





class RefreshTokenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CustomTokenRefreshSerializer(
            data=request.data
        )

        try:
            serializer.is_valid(raise_exception=True)

            return APIResponse.success(
                message="Token refreshed successfully.",
                data=serializer.validated_data,
                status_code=200
            )

        except TokenError:
            return APIResponse.error(
                message="Invalid or expired refresh token.",
                status_code=401
            )


def get_or_create_profile(user):
    # Safety net for users created without a profile (e.g. createsuperuser).
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"name": user.get_full_name() or user.get_username()},
    )
    # Reuse the already-loaded user so reading username/email costs no extra query.
    profile.user = user
    return profile
 
 
class GetProfileView(APIView):
    """GET /profile/  -> the logged-in user's profile"""
 
    permission_classes = [IsAuthenticated]
 
    def get(self, request):
        profile = get_or_create_profile(request.user)
        return APIResponse.success(
            message="Profile retrieved successfully.",
            data=ProfileDetailSerializer(profile).data,
        )
 
 
class UpdateProfileView(APIView):
    """
    PUT   /profile/  -> full update (name is required)
    PATCH /profile/  -> partial update (send only the fields to change)
    """
 
    permission_classes = [IsAuthenticated]
 
    def _update(self, request, partial):
        profile = get_or_create_profile(request.user)
 
        serializer = UserProfileSerializer(profile, data=request.data, partial=partial)
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)
 
        serializer.save()
        return APIResponse.success(
            message="Profile updated successfully.",
            data=serializer.data,
        )
 
    def put(self, request):
        return self._update(request, partial=False)
 
    def patch(self, request):
        return self._update(request, partial=True)
 

class ChangePasswordView(APIView):
    """POST /change-password/  body: {"old_password": "...", "new_password": "..."}"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Keeps the current session logged in if you use session auth (no-op otherwise).
        update_session_auth_hash(request, user)

        return APIResponse.success(message="Password changed successfully.")
    



class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)

        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)

        email = serializer.validated_data["email"]

        request_password_reset(email)

        return APIResponse.success(
            message=(
                "If an account exists with this email, "
                "a password reset OTP will be sent."
            ),
            data=None,
            status_code=200
        )


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)

        if not serializer.is_valid():
            return APIResponse.validation_error(serializer.errors)

        otp = serializer.validated_data["otp"]
        new_password = serializer.validated_data["new_password"]

        ip_address = request.META.get("REMOTE_ADDR", "")

        try:
            user = reset_user_password(
                otp=otp,
                new_password=new_password,
                ip_address=ip_address
            )

        except PasswordResetError as exc:
            return APIResponse.error(
                message=str(exc),
                status_code=400
            )

        return APIResponse.success(
            message="Password reset successfully. You can now log in.",
            data={
                "user_id": user.id,
                "email": user.email,
            },
            status_code=200
        )
