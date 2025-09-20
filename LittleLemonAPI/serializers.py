from rest_framework import serializers
from django.contrib.auth.models import User, Group
from .models import MenuItem, Category, Cart, CartItem, Order, OrderItem, MenuItemReview
from djoser.serializers import UserCreateSerializer as DjoserUserCreateSerializer
from collections import defaultdict
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from django.db import IntegrityError

# Serializer مخصص لـDjoser
class UserCreateSerializer(DjoserUserCreateSerializer):
    class Meta(DjoserUserCreateSerializer.Meta):
        fields = [ 'username','first_name','last_name', 'email', 'password']

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class UserserializerSimple(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class BaseGroupUserSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), write_only=True, required=True
    )

    group_name = None  # كل subclass يحدد الاسم

    class Meta:
        model = User
        fields = ["id", "username", "email", "user_id"]
        read_only_fields = ["id", "username", "email"]

    def validate_user_id(self, value):
        group, _ = Group.objects.get_or_create(name=self.group_name)
        if group.user_set.filter(id=value.id).exists():
            raise serializers.ValidationError(f"This user is already in {self.group_name} group.")
        return value

    def create(self, validated_data):
        user = validated_data["user_id"]
        group, _ = Group.objects.get_or_create(name=self.group_name)
        group.user_set.add(user)
        return user


class ManagerUserSerializer(BaseGroupUserSerializer):
    group_name = "Manager"


class DeliveryUserSerializer(BaseGroupUserSerializer):
    group_name = "Delivery_crew"



class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']


        
class MenuItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), source='category', write_only=True)

    class Meta:
        model = MenuItem
        fields = ['id', 'title', 'price', 'inventory', 'category', 'category_id', 'featured']

    def create(self, validated_data):
        category_id = self.context.get('category_id')
        if category_id:
            # override category من الـ body أو لو مش موجود ضعها
            validated_data['category'] = Category.objects.get(pk=category_id)
        return MenuItem.objects.create(**validated_data)

    
    def update(self, instance, validated_data):
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        featured_in_payload = 'featured' in validated_data
        # نأخذ قيمة featured ونحذفها من validated_data حتى لا نعيد معالجتها في حلقة الحقول
        featured_value = validated_data.pop('featured', None)

        # فحص الصلاحية مبكراً
        if featured_in_payload and not (user and (user.is_superuser or user.groups.filter(name="Manager").exists())):
            raise PermissionDenied("Only managers/superusers can change the 'featured' status.")

        try:
            # transaction لضمان التزامن
            with transaction.atomic():
                if featured_in_payload and featured_value:
                    # قفل العنصر الحالي وأي عنصر كان مميزًا لتفادي race conditions
                    locked_qs = MenuItem.objects.select_for_update().filter(Q(featured=True) | Q(pk=instance.pk))
                    # نُعطّل أي عناصر مميزة أخرى (ما عدا العنصر الحالي)
                    locked_qs.exclude(pk=instance.pk).filter(featured=True).update(featured=False)
                    instance.featured = True
                elif featured_in_payload:
                    # لو القيمة False: فقط نحدّث قيمة العنصر الحالي بدون تغيير عناصر أخرى
                    instance.featured = False

                # تحديث الحقول الباقية (مع ملاحظة التعامل الخاص بالـ M2M لاحقًا)
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)

                instance.save()

        except IntegrityError:
            # لو استخدمت قيد فريد على DB هذا ممكن يحدث عند تعارضات متزامنة
            raise serializers.ValidationError("Could not set featured due to concurrency. Please retry.")

        return instance
    

class MenuItemShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ['id', 'title', 'price']

class CartItemSerializer(serializers.ModelSerializer):
    menuitem_title = serializers.CharField(source='menuitem.title', read_only=True)
    menuitem_price = serializers.DecimalField(
        source='menuitem.price', max_digits=10, decimal_places=2, read_only=True
    )
    menuitem_id = serializers.PrimaryKeyRelatedField(
        queryset=MenuItem.objects.all(), source='menuitem', write_only=True
    )

    subtotal = serializers.SerializerMethodField(method_name='calculate_price', read_only=True)
    cart_name = serializers.CharField(source='cart.user.username', read_only=True)
    

    class Meta:
        model = CartItem
        fields = ['cart_name','id', 'menuitem_title','menuitem_price', 'quantity', 'subtotal', 'menuitem_id']

    def calculate_price(self,cart_item: CartItem):
        return cart_item.quantity * cart_item.menuitem.price
    
    def create(self, validated_data):
        user = self.context['request'].user
        menuitem = validated_data['menuitem']
        quantity = validated_data.get('quantity', 1)

        # حاول نجيب item موجود مسبقًا لنفس ال user ونفس ال menuitem
        cart_item, created = CartItem.objects.get_or_create(
            cart__user=user,
            menuitem=menuitem,
            defaults={'quantity': quantity}
        )

        if not created:
            # لو موجود بالفعل، نزود الكمية
            cart_item.quantity += quantity
            cart_item.save()

        return cart_item
    
class CartItemGroupedSerializer(serializers.Serializer):
    def to_representation(self, queryset):
        grouped = defaultdict(list)
        for item in queryset:
            grouped[item.cart.user.username].append({
                'id': item.id,
                'menuitem_title': item.menuitem.title,
                'menuitem_price': str(item.menuitem.price),
                'quantity': item.quantity,
                'subtotal': item.quantity * item.menuitem.price,
            })
        return grouped

    
    
class CartSerializer(serializers.ModelSerializer):
        items = CartItemSerializer(many=True, read_only=True)
        user = UserserializerSimple(read_only=True)
        total = serializers.SerializerMethodField(method_name='calculate_total', read_only=True)
       
       
        class Meta:
            model = Cart
            fields = ['id', 'user', 'items', 'total']
            read_only_fields = ['user']
            
        def create(self, validated_data):
            user = self.context['request'].user
            if Cart.objects.filter(user=user).exists():
               raise serializers.ValidationError("This user already has a cart.")
            cart = Cart.objects.create(user=user)
            return cart
        
        def calculate_total (self, cart: Cart):
            items=cart.items.all()
            return sum([item.quantity * item.menuitem.price for item in items])
        
class OrderItemSerializer(serializers.ModelSerializer):
    menuitem_title = serializers.CharField(source='menuitem.title', read_only=True)
    menuitem_price = serializers.DecimalField(
        source='menuitem.price', max_digits=10, decimal_places=2, read_only=True
    )
    menuitem_id = serializers.PrimaryKeyRelatedField(
        queryset=MenuItem.objects.all(), source='menuitem', write_only=True
    )

    class Meta:
        model = OrderItem
        fields = ['id', 'menuitem_title','menuitem_price', 'menuitem_id', 'quantity', 'unit_price', 'price']
        read_only_fields = ['unit_price', 'price']

    def create(self, validated_data):
        menuitem = validated_data['menuitem']
        quantity = validated_data['quantity']
        unit_price = menuitem.price
        price = unit_price * quantity
        return OrderItem.objects.create(
            menuitem=menuitem,
            quantity=quantity,
            unit_price=unit_price,
            price=price
        )
    
class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)  # read only علشان يتولد تلقائي
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    delivery_crew = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(groups__name="Delivery_crew"),
        required=False, write_only=True
    )
    delivery_crew_name = serializers.CharField(source='delivery_crew.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    

    class Meta:
        model = Order
        fields = ['id', 'user', 'created_at', 'total', 'items','delivery_crew', 'status', 'status_display', 'delivery_crew_name']
        read_only_fields = ['user', 'created_at', 'total']
      

    def create(self, validated_data):
        user = self.context['request'].user
        cart_items = CartItem.objects.filter(cart__user=user)

        if not cart_items.exists():
            raise serializers.ValidationError("Cart is empty!")

        # إنشاء Order جديد
        order = Order.objects.create(user=user)

        total_price = 0
        for cart_item in cart_items:
            unit_price = cart_item.menuitem.price
            price = unit_price * cart_item.quantity

            OrderItem.objects.create(
                order=order,
                menuitem=cart_item.menuitem,
                quantity=cart_item.quantity,
                unit_price=unit_price,
                price=price
            )

            total_price += price

        # تحديث إجمالي الأوردر
        order.total = total_price
        order.save()

        # تفريغ الكارت بعد عمل الأوردر (اختياري)
        cart_items.delete()

        return order
    
    def update(self, instance, validated_data):
        user = self.context['request'].user  # request متاح من get_serializer_context

        # المانجر فقط يقدر يعيّن delivery_crew
        if user.is_superuser or user.groups.filter(name="Manager").exists():
            if 'delivery_crew' in validated_data:
                instance.delivery_crew = validated_data['delivery_crew']

        # فريق التوصيل فقط يقدر يحدّث الحالة لـ Delivered
        if user.groups.filter(name="Delivery_crew").exists():
            new_status = validated_data.get('status')
            if new_status == 1:  # Delivered
                if instance.delivery_crew != user:
                    raise serializers.ValidationError("You are not assigned to this order.")
                instance.status = 1

        instance.save()
        return instance
    
class MenuItemReviewSerializer(serializers.ModelSerializer):
        user = serializers.StringRelatedField(read_only=True)
        menuitem_id = serializers.PrimaryKeyRelatedField(
        queryset=MenuItem.objects.all(), source='menuitem', write_only=True
         )

        class Meta:
            model = MenuItemReview
            fields = ['id', 'menuitem', 'user', 'rating', 'comment', 'created_at', 'menuitem_id']
            read_only_fields = ['user', 'created_at', 'menuitem']
