from django.apps import AppConfig


class LegalCodeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'legal_code'

    def ready(self):
        # Ensure admin registrations are loaded for this app.
        from . import admin  # noqa: F401
