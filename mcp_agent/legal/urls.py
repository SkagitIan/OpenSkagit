from django.urls import path

from mcp_agent.legal import views

urlpatterns = [
    path("jurisdictions/", views.legal_jurisdictions, name="mcp_agent_legal_jurisdictions"),
    path("search/", views.legal_search, name="mcp_agent_legal_search"),
    path("get/", views.legal_get, name="mcp_agent_legal_get"),
]

