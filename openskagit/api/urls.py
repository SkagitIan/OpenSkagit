from django.urls import path

from openskagit.api import views


urlpatterns = [
    path("parcel/<str:parcel_number>/", views.ParcelDetailView.as_view(), name="parcel-detail"),
    path("sales/", views.SalesListView.as_view(), name="sales-list"),
    path("search/", views.ParcelSearchView.as_view(), name="parcel-search"),
    path("summary/", views.ParcelSummaryView.as_view(), name="parcel-summary"),
    path("semantic_search/", views.SemanticSearchView.as_view(), name="semantic-search"),
    path("nearby/", views.NearbyParcelsView.as_view(), name="parcel-nearby"),
]
