
from django.urls import path
from .views import ChangePasswordView, GetProfileView, LoginView, RefreshTokenView, RegisterView, UpdateProfileView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('refresh/', RefreshTokenView.as_view(), name='refresh'),
    path("profile/", GetProfileView.as_view(), name="get-profile"),
    path("profile/update/", UpdateProfileView.as_view(), name="update-profile"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
]
