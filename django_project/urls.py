"""django_project URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from openskagit import views as openskagit_views
from openskagit.neighborhood import neighborhood_snapshot_view

urlpatterns = [
    path('', openskagit_views.home, name='home'),
    path('history/', openskagit_views.history, name='chat-history'),
    path('chat/', openskagit_views.chat, name='chat'),
    path('chat/new', openskagit_views.chat_new, name='chat-new'),
    path('documents/upload/', openskagit_views.documents_upload, name='documents-upload'),
    path('admin/', admin.site.urls),
    path("api/chat/", openskagit_views.chat_completion, name="api-chat"),
    path("api/dashboard/", openskagit_views.api_dashboard, name="api-dashboard"),
    path("api/docs/", openskagit_views.api_docs, name="api-docs"),
    path("api/sales/top25/", openskagit_views.top_sales_widget, name="top-sales-partial"),
    path("api/sales/top25/<str:parcel_number>/", openskagit_views.parcel_modal, name="parcel-modal-partial"),
    path("cma/", openskagit_views.cma_dashboard_view, name="cma-dashboard"),
    path("cma/parcel-search/", openskagit_views.cma_parcel_search, name="cma-parcel-search"),
    path("cma/comparison/<str:parcel_number>/", openskagit_views.cma_comparison_grid, name="cma-comparison-grid"),
    path(
        "cma/improvements/<str:parcel_number>/<str:comp_parcel>/",
        openskagit_views.cma_comparable_improvements,
        name="cma-comparable-improvements",
    ),
    path(
        "cma/toggle/<str:parcel_number>/<str:comp_parcel>/",
        openskagit_views.cma_toggle_comparable,
        name="cma-toggle-comp",
    ),
    path("cma/map/<str:parcel_number>/", openskagit_views.cma_map_data, name="cma-map-data"),
    path("cma/save/<str:parcel_number>/", openskagit_views.cma_save_analysis, name="cma-save"),
    path("cma/share/<uuid:share_uuid>/", openskagit_views.cma_share, name="cma-share"),
    path("cma/<str:parcel_number>/", openskagit_views.cma_dashboard_view, name="cma-detail"),
    path("api/", include("openskagit.api.urls")),
    path("neighborhoods/<str:code>/", neighborhood_snapshot_view, name="neighborhood-snapshot"),
    # Citizen Appeal Helper
    path("appeal/new/", openskagit_views.appeal_new, name="appeal-new"),
    path("appeal/", openskagit_views.appeal_home, name="appeal-home"),
    path("appeal/parcel-search/", openskagit_views.appeal_parcel_search, name="appeal-parcel-search"),
    path("appeal/result/<str:parcel_number>/", openskagit_views.appeal_result, name="appeal-result"),
    path(
        "appeal/result/<str:parcel_number>/comparables/",
        openskagit_views.appeal_result_comparables,
        name="appeal-result-comparables",
    ),
]
