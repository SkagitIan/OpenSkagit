from django.urls import path

from planning import views

urlpatterns = [
    path("parcel-search/", views.planning_parcel_search, name="planning-parcel-search"),
    path("intent/", views.planning_intent_graph, name="planning-intent-graph"),
    path("active-code-sets/", views.planning_active_code_sets, name="planning-active-code-sets"),
    path("chunks/", views.planning_chunks, name="planning-chunks"),
    path("answer/", views.planning_answer, name="planning-answer"),
    path("parcel-detail-json/", views.planning_parcel_detail_json, name="planning-parcel-detail-json"),
    path("intent-classify/", views.planning_intent_classify, name="planning-intent-classify"),
    path("scope/resolve/product/", views.planning_scope_resolve_product, name="planning-scope-resolve-product"),
    path("scope/resolve/debug/", views.planning_scope_resolve_debug, name="planning-scope-resolve-debug"),
    path("parcel/<str:parcel_number>/", views.planning_parcel_detail, name="planning-parcel-detail"),
    path("debug/", views.planning_scope_debug, name="planning-home-debug"),
    path("", views.planning_home, name="planning-home"),
]
