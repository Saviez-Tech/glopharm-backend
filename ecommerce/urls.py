from django.urls import path

from .views import ProductDetailView, ProductListView, ProductSearchView

urlpatterns = [
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/search/", ProductSearchView.as_view(), name="product-search"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
]