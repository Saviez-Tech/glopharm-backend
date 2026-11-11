from django.urls import path

from .views import LabTestCheckoutView, LabTestDetailView, LabTestListCreateView

urlpatterns = [
    path("", LabTestListCreateView.as_view(), name="labtest-list-create"),
    path("<str:reference>/", LabTestDetailView.as_view(), name="labtest-detail"),
    path("<str:reference>/checkout/", LabTestCheckoutView.as_view(), name="labtest-checkout"),
]