web: gunicorn django_project.wsgi --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-3} --timeout 120
worker: celery -A config worker --loglevel info
