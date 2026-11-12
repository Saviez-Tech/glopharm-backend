from django.urls import path

from .views import AdminDashboardStatsView, AdminLabTestDetailView, AdminLabTestListView, AdminLabTestStatsView, AdminOrderListView, AdminOrderStatsView, AdminOrderStatusView, AdminPopularProductsView, AdminPrescribeView, AdminProductCreateView, AdminProductDetailView, AdminProductStatsView, AdminRevenueChartView
urlpatterns = [
    path("manage/products/stats/", AdminProductStatsView.as_view(), name="admin-product-stats"),
    path("manage/products/", AdminProductCreateView.as_view(), name="admin-product-create"),
    path("manage/products/<int:pk>/", AdminProductDetailView.as_view(), name="admin-product-detail"),
    
    path("manage/orders/stats/", AdminOrderStatsView.as_view(), name="admin-order-stats"),
    path("manage/orders/", AdminOrderListView.as_view(), name="admin-order-list"),
    path("manage/orders/<str:order_number>/status/", AdminOrderStatusView.as_view(), name="admin-order-status"),
    
    path("lab-tests/stats/", AdminLabTestStatsView.as_view()),
    path("lab-tests/", AdminLabTestListView.as_view()),
    path("lab-tests/<str:reference>/", AdminLabTestDetailView.as_view()),
    path("lab-tests/<str:reference>/prescription/", AdminPrescribeView.as_view()),
    
    path("dashboard/stats/", AdminDashboardStatsView.as_view()),
    path("dashboard/popular-products/", AdminPopularProductsView.as_view()),
    path("dashboard/revenue-chart/", AdminRevenueChartView.as_view()),
]