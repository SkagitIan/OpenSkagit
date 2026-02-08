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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from openskagit import survey as survey_views
from openskagit import views as openskagit_views
from openskagit.neighborhood import neighborhood_snapshot_view

urlpatterns = [
    path('', openskagit_views.home, name='home'),
    path('kids/', include('openskagit.kidslab.urls')),
    path('flavor/', openskagit_views.flavor_index, name='flavor-index'),
    path('flavor/build/', openskagit_views.build_skagit_dish, name='flavor-build-skagit-dish'),
    path('documents/upload/', openskagit_views.documents_upload, name='documents-upload'),
    path('survey/', survey_views.citizen_survey, name='citizen-survey'),
    path('survey/respond/', survey_views.survey_response, name='citizen-survey-response'),
    path('about/', openskagit_views.about_view, name='about'),
    path('consult/', openskagit_views.consult_view, name='consult'),
    path('contact/', openskagit_views.contact_view, name='contact'),
    path('votevector/', openskagit_views.votevector_view, name='votevector'),
    path('partner/', openskagit_views.partner_view, name='partner'),
    path('dashboard/', openskagit_views.newsletter_dashboard, name='newsletter-dashboard'),
    path('newsletter/unsubscribe/<str:token>/', openskagit_views.newsletter_unsubscribe, name='newsletter-unsubscribe'),
    path('briefing/subscribe/', openskagit_views.subscribe_briefing, name='briefing-subscribe'),
    path('sitemap.xml', openskagit_views.sitemap_xml, name='sitemap-xml'),
    path('admin/', admin.site.urls),
    path("api/dashboard/", openskagit_views.api_dashboard, name="api-dashboard"),
    path("api/live-activity/", openskagit_views.live_activity_feed, name="live-activity-feed"),
    path("api/docs/", openskagit_views.api_docs, name="api-docs"),
    path("api/sales/top25/", openskagit_views.top_sales_widget, name="top-sales-partial"),
    path("api/sales/top25/<str:parcel_number>/", openskagit_views.parcel_modal, name="parcel-modal-partial"),
    path("sales/", openskagit_views.sales_search, name="sales-search"),
    path("sales/search/suggest/", openskagit_views.sales_compare_search, name="sales-compare-search"),
    path("sales/export/", openskagit_views.sales_search_export, name="sales-search-export"),
    path("sales/row/<int:sale_id>/", openskagit_views.sales_search_row, name="sales-search-row"),
    path("cma/", openskagit_views.cma_dashboard_view, name="cma-dashboard"),
    path("cma/parcel-search/", openskagit_views.cma_parcel_search, name="cma-parcel-search"),
    path("cma/comparison/<str:parcel_number>/", openskagit_views.cma_comparison_grid, name="cma-comparison-grid"),
    #path("methodology/load-more/", openskagit_views.load_more_adjustment_runs, name="load-more-adjustment-runs"),

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
    path("api/gastronet/", include("gastronet.urls")),
    path("agent/", include("mcp_agent.urls")),
    path("agent/", include("agent.urls")),
    path("gastronet/", include("gastronet.urls")),
    path("planning/", include("planning.urls")),
    path("neighborhoods/<str:code>/", neighborhood_snapshot_view, name="neighborhood-snapshot"),
    path("methodology/", openskagit_views.methodology_view, name="methodology"),
    path("faq/", openskagit_views.faq_view, name="faq"),
    path("hood-trends/", openskagit_views.hood_trend_list, name="hood_trend_list"),
    path("hood-trends/<str:hood_id>/", openskagit_views.hood_trend_detail, name="hood_trend_detail"),
    path(
        "neighborhood-trends/",
        openskagit_views.neighborhood_trends_page,
        name="neighborhood-trends-page",
    ),
    path(
        "neighborhood-trends/<str:hood_id>/data/",
        openskagit_views.neighborhood_trend_data,
        name="neighborhood-trend-data",
    ),
    path(
        "neighborhood-trends/<str:hood_id>/geom/",
        openskagit_views.neighborhood_trend_geom,
        name="neighborhood-trend-geom",
    ),
    path(
        "neighborhood-trends/search/",
        openskagit_views.neighborhood_trend_address_search,
        name="neighborhood-trend-search",
    ),
    # Citizen Appeal Helper

    #path("appeal/new/", openskagit_views.appeal_new, name="appeal-new"),
    path("parcel/", openskagit_views.appeal_home, name="appeal-home"),
    #path('appeal/modern/', openskagit_views.appeal_home, name='appeal-home-modern'),
    path("parcel/parcel-search/", openskagit_views.appeal_parcel_search, name="appeal-parcel-search"),
    path("tax/", openskagit_views.tax_levy_home, name="tax-levy-home"),
    path("tax/parcel-search/", openskagit_views.tax_parcel_search, name="tax-parcel-search"),
    path("parcel/result/<str:parcel_number>/", openskagit_views.appeal_result, name="appeal-result"),
    path(
        "parcel/result/<str:parcel_number>/comparables/",
        openskagit_views.appeal_result_comparables,
        name="appeal-result-comparables",
    ),
    path(
        "parcel/result/<str:parcel_number>/fairness/",
        openskagit_views.appeal_fairness_analysis,
        name="appeal-result-fairness",
    ),
    # Legacy appeal URLs (permanent redirect to new parcel routes)
    path(
        "appeal/",
        RedirectView.as_view(pattern_name="appeal-home", permanent=True, query_string=True),
    ),
    path(
        "appeal/parcel-search/",
        RedirectView.as_view(pattern_name="appeal-parcel-search", permanent=True, query_string=True),
    ),
    path(
        "appeal/result/<str:parcel_number>/",
        RedirectView.as_view(pattern_name="appeal-result", permanent=True, query_string=True),
    ),
    path("tax/levies/", RedirectView.as_view(pattern_name="tax-levy-home", permanent=True, query_string=True)),
    path(
        "appeal/result/<str:parcel_number>/comparables/",
        RedirectView.as_view(pattern_name="appeal-result-comparables", permanent=True, query_string=True),
    ),
    path(
        "appeal/result/<str:parcel_number>/fairness/",
        RedirectView.as_view(pattern_name="appeal-result-fairness", permanent=True, query_string=True),
    ),
    # Experiments
    path("experiments/", openskagit_views.experiment_list, name="experiment_list"),
    path("experiments/new/", openskagit_views.experiment_create, name="experiment_create"),
    path("experiments/<uuid:experiment_id>/", openskagit_views.experiment_detail, name="experiment_detail"),
    path("experiments/<uuid:experiment_id>/status/", openskagit_views.experiment_status_json, name="experiment_status"),
    path("experiments/compare/", openskagit_views.experiment_compare, name="experiment_compare"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
