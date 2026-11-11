from rest_framework import serializers

from .models import Product, ProductSpecification


class ProductSpecificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSpecification
        fields = ("id", "name", "value")


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight: no description, no specifications."""

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "image",
            "category",
            "subcategory",
            "original_price",
            "price",
            "stock",
        )


class ProductDetailSerializer(serializers.ModelSerializer):
    # Served from the prefetch cache, so no extra query per product.
    specifications = ProductSpecificationSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "image",
            "image2",
            "image3",
            "image4",
            "category",
            "subcategory",
            "description",
            "original_price",
            "price",
            "stock",
            "created_at",
            "updated_at",
            "specifications",
        )