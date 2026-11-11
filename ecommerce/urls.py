from django.urls import path

from .views import PayOrderView,CheckoutView, PaystackWebhookView, ProductDetailView, ProductListView, ProductSearchView, VerifyPaymentView

urlpatterns = [
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/search/", ProductSearchView.as_view(), name="product-search"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    
    
    path("orders/checkout/", CheckoutView.as_view(), name="checkout"),
    path("orders/payment/verify/", VerifyPaymentView.as_view(), name="payment-verify"),
    path("orders/payment/webhook/", PaystackWebhookView.as_view(), name="payment-webhook"),
    path("orders/<str:order_number>/pay/", PayOrderView.as_view(), name="order-pay"),
]