from django.contrib import admin
from .models import Order, Product, ProductSpecification


admin.site.register(Order)
class ProductSpecificationInline(admin.TabularInline):
    model = ProductSpecification
    extra = 3
    fields = ("name", "value")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "subcategory",
        "price",
        "stock",
        "created_at",
    )

    search_fields = ("name", "category", "subcategory")
    list_filter = ("category", "subcategory")
    inlines = [ProductSpecificationInline]