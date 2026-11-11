
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status
from .serializers import RegisterSerializer
from .utils import APIResponse
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import LoginSerializer
from .serializers import CustomTokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError


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
