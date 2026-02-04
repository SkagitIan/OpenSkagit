# agent/urls.py
from django.urls import path
from . import views_api

# URL patterns for the Agent Tools API
# All paths are prefixed with /agent/api/ at the project level.
urlpatterns = [
    path("api/health/", views_api.health_check, name="agent_api_health"),
    path("api/lookup/", views_api.lookup_parcel, name="agent_api_lookup"),
    path("api/parcel/<str:parcel_id>/bundle/", views_api.get_parcel_bundle, name="agent_api_parcel_bundle"),
    path("api/parcel/<str:parcel_id>/intersect/", views_api.intersect_parcel, name="agent_api_parcel_intersect"),
    path("api/docs/search/", views_api.search_docs, name="agent_api_docs_search"),
]
