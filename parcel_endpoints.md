# Parcel-ID endpoints (candidates)

Collected from all `urls.py` under /home/django/django_project. Each path takes a parcel id/number in the URL and returns JSON or could be wrapped as an MCP action.

## openskagit/api/urls.py
- path("appeals/<str:parcel_number>/comparables/", views.AppealComparablesView.as_view(), name="appeal-comparables")

## django_project/urls.py
- path("api/sales/top25/<str:parcel_number>/", openskagit_views.parcel_modal, name="parcel-modal-partial")
- path("cma/comparison/<str:parcel_number>/", openskagit_views.cma_comparison_grid, name="cma-comparison-grid")

## planning/urls.py
- path("parcel/<str:parcel_number>/", views.planning_parcel_detail, name="planning-parcel-detail")

(Other urls files had no parcel-id paths.)
