from django.apps import AppConfig


class GisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gis"
    label = "gis_registry"
    verbose_name = "GIS Source Registry"
