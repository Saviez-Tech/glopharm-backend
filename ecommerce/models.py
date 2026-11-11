from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255)
    image = models.URLField(blank=True, null=True)
    image2 = models.URLField(blank=True, null=True)
    image3 = models.URLField(blank=True, null=True)
    image4 = models.URLField(blank=True, null=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    subcategory = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField()
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["-created_at", "-id"], name="product_created_idx"),
            models.Index(fields=["category", "subcategory"], name="product_category_idx"),
        ]

    def __str__(self):
        return self.name


class ProductSpecification(models.Model):
    # ForeignKey columns are indexed automatically by Django.
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="specifications",
    )
    name = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name}: {self.value}"