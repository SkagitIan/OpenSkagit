from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Assessor, Improvements, Land, Sales

from leaflet.admin import LeafletGeoAdmin
from .models import Assessor

@admin.register(Assessor)
class AssessorAdmin(LeafletGeoAdmin):
    list_display = ("parcel_number", "assessed_value")
    search_fields = ("parcel_number", "address", "city_district")

@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "sale_price", "sale_date", "sale_type")
    search_fields = ("parcel_number", "buyer_name", "seller_name")

admin.site.register(Improvements)
admin.site.register(Land)

