from django.urls import path

from openskagit.api import views


urlpatterns = [
    path("parcel/<str:parcel_number>/", views.ParcelDetailView.as_view(), name="parcel-detail"),
    path("sales/", views.SalesListView.as_view(), name="sales-list"),
    path("search/", views.ParcelSearchView.as_view(), name="parcel-search"),
    path("summary/", views.ParcelSummaryView.as_view(), name="parcel-summary"),
    path("semantic_search/", views.SemanticSearchView.as_view(), name="semantic-search"),
    path("nearby/", views.NearbyParcelsView.as_view(), name="parcel-nearby"),
    path("neighborhood_stats/<str:neighborhood_code>/", views.NeighborhoodStatsView.as_view(), name="neighborhood-stats"),
    path("appeal_analysis/<str:parcel_number>/", views.AppealAnalysisView.as_view(), name="appeal-analysis"),
    path("appeals/search/", views.AppealParcelSearchView.as_view(), name="appeal-search"),
    path("appeals/<str:parcel_number>/subject/", views.AppealSubjectView.as_view(), name="appeal-subject"),
    path("appeals/<str:parcel_number>/comparables/", views.AppealComparablesView.as_view(), name="appeal-comparables"),
    path(
        "appeals/<str:parcel_number>/comparables/<str:comp_parcel>/improvements/",
        views.AppealComparableImprovementsView.as_view(),
        name="appeal-comparable-improvements",
    ),
    path("neighborhoods/<str:neighborhood_code>/", views.NeighborhoodStatsView.as_view(), name="neighborhood-detail"),
    path(
        "co_appraiser/adjustments/",
        views.CoAppraiserAdjustmentView.as_view(),
        name="co-appraiser-adjustments",
    ),
]
