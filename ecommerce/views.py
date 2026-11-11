from django.db.models import Prefetch, Q
from rest_framework.views import APIView

from .models import Product, ProductSpecification
from .pagination import StandardPagination
from .serializers import ProductDetailSerializer, ProductListSerializer
from .utils import APIResponse  
from rest_framework.permissions import AllowAny


class ProductListView(APIView):
    permission_classes = [AllowAny]  # Allow any user (authenticated or not) to access this view.
    """
    GET /products/
    Optional query params: category, subcategory, page, page_size
    """

    def get(self, request):
        # .only() fetches just the columns the list serializer needs
        # (skips the heavy description and extra image columns).
        queryset = Product.objects.only(*ProductListSerializer.Meta.fields)

        category = request.query_params.get("category")
        subcategory = request.query_params.get("subcategory")
        if category:
            queryset = queryset.filter(category=category)
        if subcategory:
            queryset = queryset.filter(subcategory=subcategory)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ProductListSerializer(page, many=True)

        return APIResponse.success(
            message="Products retrieved successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )


class ProductSearchView(APIView):
    
    permission_classes = [AllowAny] 
    """
    GET /products/search/?q=<text>
    Optional query params: category, subcategory, page, page_size

    Each word in q must match the name, category or subcategory
    (case-insensitive), so "red shoe" finds "Red Running Shoes".
    """

    MIN_QUERY_LENGTH = 2
    MAX_TERMS = 5

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()

        if len(query) < self.MIN_QUERY_LENGTH:
            return APIResponse.error(
                f"Search query must be at least {self.MIN_QUERY_LENGTH} characters.",
                status_code=400,
            )

        queryset = Product.objects.only(*ProductListSerializer.Meta.fields)

        for term in query.split()[: self.MAX_TERMS]:
            queryset = queryset.filter(
                Q(name__icontains=term)
                | Q(category__icontains=term)
                | Q(subcategory__icontains=term)
            )

        category = request.query_params.get("category")
        subcategory = request.query_params.get("subcategory")
        if category:
            queryset = queryset.filter(category=category)
        if subcategory:
            queryset = queryset.filter(subcategory=subcategory)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ProductListSerializer(page, many=True)

        return APIResponse.success(
            message="Search completed successfully.",
            data=paginator.get_paginated_data(serializer.data),
        )


class ProductDetailView(APIView):
    """GET /products/<id>/  (includes specifications)"""
    
    permission_classes = [AllowAny] 

    def get(self, request, pk):
        # 2 queries total: one for the product, one for all its specifications.
        product = (
            Product.objects.prefetch_related(
                Prefetch(
                    "specifications",
                    queryset=ProductSpecification.objects.only(
                        "id", "product_id", "name", "value"
                    ),
                )
            )
            .filter(pk=pk)
            .first()
        )

        if product is None:
            return APIResponse.error("Product not found.", status_code=404)

        return APIResponse.success(
            message="Product retrieved successfully.",
            data=ProductDetailSerializer(product).data,
        )