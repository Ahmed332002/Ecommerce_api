
from rest_framework import viewsets, permissions, generics, status, mixins
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User, Group
from .models import MenuItem, Category, Cart, CartItem, Order, OrderItem
from rest_framework.pagination import PageNumberPagination
from .serializers import *
from .serializers import UserCreateSerializer


# صلاحيات مخصصة
class IsManager(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and (request.user.is_superuser or request.user.groups.filter(name='Manager').exists())

class IsDeliveryCrew(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and (request.user.is_superuser or request.user.groups.filter(name='Delivery_crew').exists())

# ViewSet للمنتجات والفئات (عامة)
class MenuItemViewSet(viewsets.ModelViewSet):
    serializer_class = MenuItemSerializer
    queryset = MenuItem.objects.select_related('category').all()
    filterset_fields = ['category__id']
    ordering_fields = ['price']
    search_fields = ['title']
    pagination_class=PageNumberPagination
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [IsManager()]
    
    def get_queryset(self):
        category_id = self.kwargs.get("category_pk")  # لاحظ الاسم: category_pk
        if category_id:
            return MenuItem.objects.filter(category_id=category_id)
        return MenuItem.objects.select_related('category').all()
    
    def get_serializer_context(self):
        context = super().get_serializer_context()  # ياخد أي context افتراضي
        context['category_id'] = self.kwargs.get('category_pk')
        context['request'] = self.request  # ده اللي ناقص
        return context

    

class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    queryset = Category.objects.all()
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.AllowAny()]
        return [IsManager()]
    
    
class CartViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet,mixins.CreateModelMixin,
                  mixins.DestroyModelMixin,
                  mixins.ListModelMixin,mixins.UpdateModelMixin):
    serializer_class = CartSerializer
    permission_classes = [permissions.IsAuthenticated]
   
    def get_permissions(self):
        """
        نتحكم مين يدخل أي أكشن
        """
        if self.action == "list":  
            # لو عاوز يعمل List → لازم يكون Manager أو Admin
            return [IsManager()]
        # باقي الأكشنات → أي يوزر عامل لوج إن
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        نتحكم الداتا اللي اليوزر يشوفها
        """
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="Manager").exists():
            # الأدمن أو المانجر يشوفوا كل الكروت
            return Cart.objects.all()
        else:
            # يوزر عادي يشوف بس الكارت بتاعه
            return Cart.objects.filter(user=user)

    def perform_create(self, serializer):
        """
        أوفررايد عشان أربط الكارت باليوزر اللي عامل لوج إن تلقائيًا
        """
        serializer.save(user=self.request.user)

class CartItemViewSet(viewsets.ModelViewSet):
    serializer_class = CartItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="Manager").exists():
            return CartItem.objects.all()
        return CartItem.objects.filter(cart__user=user)
    
    def perform_create(self, serializer):
        # جلب الكارت الخاص باليوزر
        cart = Cart.objects.get(user=self.request.user)
        serializer.save(cart=cart)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = CartItemGroupedSerializer(queryset, many=False)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        # في حالة المانجر:
        #   /api/cart-items/<user_id>/
        #   بيعرض كل CartItems الخاصة باليوزر اللي الـ id بتاعه = pk
        user_id = kwargs.get('pk')
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=404)

        cart_items = CartItem.objects.filter(cart__user=user)
        serializer = CartItemSerializer(cart_items, many=True)
        return Response(serializer.data)

    
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="Manager").exists():
            return Order.objects.all()
        elif user.groups.filter(name="Delivery_crew").exists():
            return Order.objects.filter(delivery_crew=user)
        return Order.objects.filter(user=user)

    def get_serializer_context(self):
        """
        DRF بتستدعيه تلقائيًا لما تعمل self.get_serializer()
        هنا نضيف request للـ serializer
        """
        context = super().get_serializer_context()
        # أي context إضافي ممكن تحطه هنا
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        # أي يوزر ينشئ أوردر → الحالة تكون Out for delivery
        serializer.save(user=self.request.user, status='pending')


class ManagerGroupViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsManager]
    queryset = User.objects.filter(groups__name="Manager")
    serializer_class = ManagerUserSerializer

    http_method_names = ['get', 'post', 'delete']


    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        group = Group.objects.filter(name="Manager").first()
        if group and user in group.user_set.all():
            group.user_set.remove(user)
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_404_NOT_FOUND)
    
class DeliveryCrewGroupViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsDeliveryCrew]
    queryset = User.objects.filter(groups__name="Delivery_crew")
    serializer_class = ManagerUserSerializer

    http_method_names = ['get', 'post', 'delete']


    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        group = Group.objects.filter(name="Delivery_crew").first()
        if group and user in group.user_set.all():
            group.user_set.remove(user)
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_404_NOT_FOUND)




    

