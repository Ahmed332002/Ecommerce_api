from django.contrib import admin
from .models import MenuItem, Category, Cart, CartItem, Order, OrderItem, MenuItemReview

# Register your models here.
admin.site.register(MenuItem)
admin.site.register(Category)   
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(MenuItemReview)

class CartItemInline(admin.TabularInline):  # أو StackedInline
    model = CartItem
    extra = 0

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user',)
    inlines = [CartItemInline]

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'menuitem', 'quantity')