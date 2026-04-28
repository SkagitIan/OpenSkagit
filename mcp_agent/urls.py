from django.urls import include, path
from . import views
from . import overlay

urlpatterns = [
    path("health/", views.health_check, name="mcp_agent_health"),
    path("lookup/", views.lookup_parcel, name="mcp_agent_lookup"),
    path("parcel/<str:parcel_id>/bundle/", views.parcel_bundle, name="mcp_agent_parcel_bundle"),
    path("parcel/<str:parcel_id>/history/", views.parcel_history_rows, name="mcp_agent_parcel_history_rows"),
    path("parcel/<str:parcel_id>/flood/", views.parcel_flood_metrics, name="mcp_agent_parcel_flood"),
    path("parcel/<str:parcel_id>/listing/", views.parcel_listing, name="mcp_agent_parcel_listing"),
    path(
        "parcel/<str:parcel_id>/imagery-change/",
        views.parcel_imagery_change_compare,
        name="mcp_agent_parcel_imagery_change_compare",
    ),
    path("parcel/<str:parcel_id>/intersect/", views.parcel_intersect, name="mcp_agent_parcel_intersect"),
    path("parcel/<str:parcel_id>/neighborhood-metrics/", views.parcel_neighborhood_metrics, name="mcp_agent_parcel_neighborhood_metrics"),
    path(
        "parcel/<str:parcel_id>/neighborhood-analysis/",
        views.parcel_neighborhood_metrics,
        name="mcp_agent_parcel_neighborhood_analysis",
    ),
    path("parcel/<str:parcel_id>/sales-comps/", views.parcel_sales_comps, name="mcp_agent_parcel_sales_comps"),
    path("parcel/<str:parcel_id>/sales-comps/v2/", views.parcel_sales_comps, name="mcp_agent_parcel_sales_comps_v2"),
    path("overlay/list/", overlay.overlay_list, name="mcp_agent_overlay_list"),
    path("overlay/get/", overlay.overlay_get, name="mcp_agent_overlay_get"),
    path("legal/", include("mcp_agent.legal.urls")),
    path("nlq/", views.nlq),
]
