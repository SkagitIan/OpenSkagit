from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health_check, name="mcp_agent_health"),
    path("lookup/", views.lookup_parcel, name="mcp_agent_lookup"),
    path("parcel/<str:parcel_id>/bundle/", views.parcel_bundle, name="mcp_agent_parcel_bundle"),
    path("parcel/<str:parcel_id>/intersect/", views.parcel_intersect, name="mcp_agent_parcel_intersect"),
    path("nlq/", views.nlq),
]
