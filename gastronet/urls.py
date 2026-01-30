from django.urls import path

from . import views
from .menu_scraping import (
    extract_menu_items,
    get_next_restaurant,
    save_menu_items,
)

app_name = "gastronet"

urlpatterns = [
    path("menu-items/", views.ingest_menu_items, name="menu-items"),
    path(
        "menu-items/generate/",
        views.generate_menu_json,
        name="menu-items-generate",
    ),
    path(
        "human-in-loop/next-restaurant/",
        get_next_restaurant,
        name="get-next-restaurant",
    ),
    path(
        "human-in-loop/extract-menu-items/",
        extract_menu_items,
        name="extract-menu-items",
    ),
    path(
        "human-in-loop/save-menu-items/",
        save_menu_items,
        name="save-menu-items",
    ),
]
