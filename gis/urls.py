from django.urls import path

from . import views

app_name = "gis"

urlpatterns = [
    path("", views.submission_list, name="submission-list"),
    path("submissions/new/", views.submission_new, name="submission-new"),
    path("submissions/<int:submission_id>/", views.submission_detail, name="submission-detail"),
    path("submissions/<int:submission_id>/layers-panel/", views.submission_layers_panel, name="submission-layers-panel"),
    path("submissions/<int:submission_id>/inspect/", views.submission_run_inspection, name="submission-inspect"),
    path("submissions/<int:submission_id>/add-all/", views.submission_approve_all, name="submission-add-all"),
    path("submissions/<int:submission_id>/layers/<int:layer_id>/add/", views.submission_add_layer, name="submission-add-layer"),
    path("layers/<int:layer_id>/", views.discovered_layer_review, name="layer-review"),
    path("manifest/", views.manifest_list, name="manifest-list"),
    path("manifest/<int:manifest_id>/map-modal/", views.manifest_map_modal, name="manifest-map-modal"),
    path("manifest/map-modal/clear/", views.manifest_map_modal_clear, name="manifest-map-modal-clear"),
    path("manifest/<int:manifest_id>/test/", views.manifest_test, name="manifest-test"),
    path("manifest/<int:manifest_id>/delete/", views.manifest_delete, name="manifest-delete"),
    path("manifest/<int:manifest_id>/", views.manifest_detail, name="manifest-detail"),
]
