from django.urls import path, include
# from rest_framework import routers
from rest_framework_nested import routers
from . import views

router = routers.DefaultRouter()
router.register('menu-items', views.MenuItemViewSet)
router.register('categories', views.CategoryViewSet)
router.register('carts', views.CartViewSet, basename='cart')
router.register('cart-items', views.CartItemViewSet, basename='cart-items')
router.register('orders', views.OrderViewSet, basename='orders')
router.register('groups/manager/users', views.ManagerGroupViewSet, basename='managers')
router.register('groups/delivery-crew/users', views.DeliveryCrewGroupViewSet, basename='delivery-crews')
router.register('reviews', views.MenuItemReviewViewSet, basename='reviews')

router_menuitems = routers.NestedDefaultRouter(router, 'menu-items', lookup='menuitem')
router_menuitems.register('reviews', views.MenuItemReviewViewSet, basename='menuitem-reviews')


router_category = routers.NestedDefaultRouter(router, 'categories', lookup='category')
router_category.register('menu-items', views.MenuItemViewSet, basename='category-menu-items')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(router_menuitems.urls)),
    path('', include(router_category.urls)),
   
]
