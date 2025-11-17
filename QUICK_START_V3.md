# Quick Start - V3 Templates

## Files Ready to Use

All v3 templates are in: `/openskagit/templates/openskagit/`

### Template Files (5)
1. `appeal_base_v3.html` - Base with Ethereal Grays palette
2. `appeal_home_v3.html` - Step 1 (Search)
3. `appeal_parcel_search_results_v3.html` - Search results partial
4. `appeal_results_v3.html` - Step 2 (Property + Gauges)
5. `appeal_results_comparables_v3.html` - Step 3 (Comparables with map)

## What's New

### Color Palette
Ethereal Grays theme replaces purple/blue:
- Dusty Grape (#6C698D)
- Dusty Taupe (#AA968A)
- Dust Grey, Silver, Dim Grey

### Step 1 Changes
✅ Beautiful autocomplete with left border hover
✅ No assessment year badge
✅ Smooth animations

### Step 2 - 3 Flippable Gauge Cards
✅ **COD** - Measures assessment consistency (5-15% ideal)
✅ **PRD** - Tests high vs low value equity (0.98-1.03 ideal)
✅ **Sales Ratio** - Assessed vs market value (90-110% ideal)

Each card:
- Front: Animated canvas gauge with ideal range
- Back: Detailed IAAO standards explanation
- Pulsing flip indicator

### Step 3 - View Switcher
✅ **List View** - Detailed cards (default)
✅ **Grid View** - 2-column compact cards
✅ **Map View** - Leaflet map with markers

Map features:
- Red marker for subject property
- Dusty grape markers for comparables
- Clickable popups with details
- Auto-fit bounds

## Libraries Loaded
- Leaflet 1.9.4 (maps)
- Anime.js 3.2.1 (animations)
- HTMX (already in use)

## Next Step

Update your Django views to use v3 templates instead of modern/v2 templates.

Example:
```python
# Before
return render(request, 'openskagit/appeal_home_modern.html', context)

# After
return render(request, 'openskagit/appeal_home_v3.html', context)
```

That's it! All the design updates are ready to go.
