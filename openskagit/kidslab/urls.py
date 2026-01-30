from django.urls import path

from . import views

app_name = "kidslab"

urlpatterns = [
    path("", views.index, name="index"),
    path("add/", views.add_card, name="add"),
]
