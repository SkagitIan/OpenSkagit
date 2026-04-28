def primary_nav_links(request):
    links = [
        {"href": "/votevector/", "label": "VoteVector"},
        {"href": "/#tools", "label": "Tools"},
        {"href": "/#enrichments", "label": "Enrichments"},
        {"href": "/#model", "label": "Model"},
        {"href": "/#ai", "label": "AI"},
        {"href": "/#cta-briefing", "label": "Briefing"},
        {"href": "/partner/", "label": "Partner"},
        {"href": "/about/", "label": "About"},
        {"href": "/contact/", "label": "Contact"},
    ]

    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False) and getattr(user, "is_staff", False):
        links.append({"href": "/staff/image-generator/", "label": "Image Generator"})
        links.append({"href": "/staff/gis/", "label": "GIS Sources"})

    return {"nav_links": links}
