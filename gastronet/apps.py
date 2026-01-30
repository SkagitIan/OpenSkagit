from django.apps import AppConfig


class GastronetConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gastronet'

    def ready(self):
        # Ensure batch job plugins register with the framework at startup.
        pass
