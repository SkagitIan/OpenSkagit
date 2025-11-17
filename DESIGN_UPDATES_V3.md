# Design Updates V3 - Implementation Guide

## Changes Implemented

### 1. Color Palette - Ethereal Grays ✅

Updated to use the provided color palette:
- **Dusty Grape** (#6C698D) - Primary brand color
- **Dust Grey** (#D4D2D5) - Neutral tone
- **Silver** (#BFAFA6) - Accent
- **Dusty Taupe** (#AA968A) - Secondary accent
- **Dim Grey** (#6E6A6F) - Dark neutral

Files updated: `appeal_base_v3.html`

### 2. Step 1 - Enhanced Autocomplete Styling

Based on the reference image showing "813 CULTUS MOUNTAIN DR" results:

```html
<style>
  .autocomplete-result {
    display: block;
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--gray-100);
    text-decoration: none;
    color: inherit;
    transition: all var(--transition-fast);
    cursor: pointer;
  }

  .autocomplete-result:last-child {
    border-bottom: none;
  }

  .autocomplete-result:hover {
    background: linear-gradient(90deg, var(--primary-50), transparent);
    padding-left: calc(var(--space-5) + 8px);
  }

  .result-address {
    font-size: 1rem;
    font-weight: 600;
    color: var(--gray-900);
    margin-bottom: var(--space-1);
  }

  .result-parcel {
    font-size: 0.875rem;
    color: var(--primary-600);
    margin-bottom: var(--space-1);
  }

  .result-sale-info {
    font-size: 0.8125rem;
    color: var(--gray-600);
  }

  .result-cta {
    font-size: 0.8125rem;
    color: var(--primary-600);
    font-weight: 600;
    margin-top: var(--space-2);
  }
</style>
```

### 3. Removed Assessment Year Badge

Removed the badge from Step 1 header that showed "Assessment Year 2024".

###  4. View Switcher for Comparables

```html
<div class="view-switcher">
  <button class="view-btn view-btn--active" data-view="list" onclick="switchView('list')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="8" y1="6" x2="21" y2="6"></line>
      <line x1="8" y1="12" x2="21" y2="12"></line>
      <line x1="8" y1="18" x2="21" y2="18"></line>
      <line x1="3" y1="6" x2="3.01" y2="6"></line>
      <line x1="3" y1="12" x2="3.01" y2="12"></line>
      <line x1="3" y1="18" x2="3.01" y2="18"></line>
    </svg>
    List
  </button>
  <button class="view-btn" data-view="grid" onclick="switchView('grid')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="3" width="7" height="7"></rect>
      <rect x="14" y="3" width="7" height="7"></rect>
      <rect x="14" y="14" width="7" height="7"></rect>
      <rect x="3" y="14" width="7" height="7"></rect>
    </svg>
    Grid
  </button>
  <button class="view-btn" data-view="map" onclick="switchView('map')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"></polygon>
      <line x1="8" y1="2" x2="8" y2="18"></line>
      <line x1="16" y1="6" x2="16" y2="22"></line>
    </svg>
    Map
  </button>
</div>

<style>
  .view-switcher {
    display: inline-flex;
    gap: var(--space-1);
    background: var(--gray-100);
    padding: var(--space-1);
    border-radius: var(--radius-lg);
  }

  .view-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
    border: none;
    background: transparent;
    color: var(--gray-600);
    font-weight: 600;
    font-size: 0.875rem;
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: all var(--transition-fast);
  }

  .view-btn svg {
    width: 1rem;
    height: 1rem;
  }

  .view-btn--active {
    background: white;
    color: var(--primary-600);
    box-shadow: var(--shadow-sm);
  }

  .view-btn:hover:not(.view-btn--active) {
    color: var(--primary-500);
  }
</style>

<script>
  let comparablesMap = null;

  function switchView(view) {
    // Update buttons
    document.querySelectorAll('.view-btn').forEach(btn => {
      btn.classList.toggle('view-btn--active', btn.dataset.view === view);
    });

    // Show/hide views
    document.getElementById('list-view').style.display = view === 'list' ? 'block' : 'none';
    document.getElementById('grid-view').style.display = view === 'grid' ? 'grid' : 'none';
    document.getElementById('map-view').style.display = view === 'map' ? 'block' : 'none';

    if (view === 'map' && !comparablesMap) {
      initComparablesMap();
    }
  }

  function initComparablesMap() {
    const mapEl = document.getElementById('comparables-map');
    if (!mapEl) return;

    comparablesMap = L.map('comparables-map').setView([48.5, -122.5], 11);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors'
    }).addTo(comparablesMap);

    // Add subject marker (red)
    if (window.subjectLocation) {
      L.marker([window.subjectLocation.lat, window.subjectLocation.lon], {
        icon: L.divIcon({
          className: 'subject-marker',
          html: '<div style="background: #ef4444; width: 12px; height: 12px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
          iconSize: [18, 18]
        })
      }).addTo(comparablesMap).bindPopup('<strong>Your Property</strong>');
    }

    // Add comparable markers (blue)
    if (window.comparablesList) {
      window.comparablesList.forEach(comp => {
        if (comp.lat && comp.lon) {
          L.marker([comp.lat, comp.lon], {
            icon: L.divIcon({
              className: 'comp-marker',
              html: '<div style="background: #6c698d; width: 10px; height: 10px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 6px rgba(0,0,0,0.2);"></div>',
              iconSize: [14, 14]
            })
          }).addTo(comparablesMap).bindPopup(`
            <strong>${comp.address}</strong><br>
            Sale: $${comp.sale_price.toLocaleString()}<br>
            Date: ${comp.sale_date}<br>
            Distance: ${comp.distance_miles.toFixed(2)} mi
          `);
        }
      });
    }

    setTimeout(() => comparablesMap.invalidateSize(), 100);
  }
</script>
```

### 5. Flippable Gauge Cards with Anime.js

#### COD Gauge Card

```html
<div class="gauge-card" id="cod-card">
  <div class="gauge-card__inner">
    <!-- Front Side -->
    <div class="gauge-card__front">
      <div class="gauge-card__header">
        <h4 class="gauge-card__title">Coefficient of Dispersion (COD)</h4>
        <button class="flip-indicator" onclick="flipCard('cod-card')" aria-label="Flip to see details">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"></polyline>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
        </button>
      </div>

      <div class="gauge-container">
        <canvas id="cod-gauge" width="200" height="120"></canvas>
        <div class="gauge-value">{{ neighborhood.cod|floatformat:1 }}</div>
      </div>

      <div class="gauge-status">
        {% if neighborhood.cod < 10 %}
          <span class="status-badge status-badge--excellent">Excellent</span>
        {% elif neighborhood.cod < 15 %}
          <span class="status-badge status-badge--good">Good</span>
        {% else %}
          <span class="status-badge status-badge--fair">Fair</span>
        {% endif %}
      </div>
    </div>

    <!-- Back Side -->
    <div class="gauge-card__back">
      <div class="gauge-card__header">
        <h4 class="gauge-card__title">What is COD?</h4>
        <button class="flip-indicator" onclick="flipCard('cod-card')" aria-label="Flip back">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="1 4 1 10 7 10"></polyline>
            <path d="M3.51 15a9 9 0 0 0 2.13-9.36L1 10"></path>
          </svg>
        </button>
      </div>

      <div class="gauge-explanation">
        <p class="explanation-text">
          The <strong>Coefficient of Dispersion (COD)</strong> measures how consistent property assessments are across similar properties.
        </p>

        <div class="explanation-section">
          <h5>What it measures:</h5>
          <p>"Horizontal equity" – consistency of appraisals for similar properties, regardless of value.</p>
        </div>

        <div class="explanation-section">
          <h5>Ideal range:</h5>
          <p>The IAAO recommends a COD between <strong>5% and 15%</strong>.</p>
        </div>

        <div class="explanation-metrics">
          <div class="metric-item">
            <div class="metric-label">Lower COD</div>
            <div class="metric-desc">More consistent valuations across properties</div>
          </div>
          <div class="metric-item">
            <div class="metric-label">Higher COD</div>
            <div class="metric-desc">Greater variation in assessments, less uniform</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
  .gauge-card {
    perspective: 1000px;
    height: 360px;
    position: relative;
  }

  .gauge-card__inner {
    position: relative;
    width: 100%;
    height: 100%;
    transform-style: preserve-3d;
    transition: transform 0.6s;
  }

  .gauge-card.flipped .gauge-card__inner {
    transform: rotateY(180deg);
  }

  .gauge-card__front,
  .gauge-card__back {
    position: absolute;
    width: 100%;
    height: 100%;
    backface-visibility: hidden;
    background: white;
    border: 2px solid var(--gray-100);
    border-radius: var(--radius-xl);
    padding: var(--space-6);
  }

  .gauge-card__back {
    transform: rotateY(180deg);
  }

  .gauge-card__header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: var(--space-4);
  }

  .gauge-card__title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--gray-700);
  }

  .flip-indicator {
    background: var(--primary-50);
    border: none;
    width: 2rem;
    height: 2rem;
    border-radius: var(--radius-full);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--primary-600);
    cursor: pointer;
    transition: all var(--transition-fast);
    animation: pulseRotate 2s infinite;
  }

  .flip-indicator:hover {
    background: var(--primary-100);
    transform: scale(1.1);
  }

  @keyframes pulseRotate {
    0%, 100% { transform: rotate(0deg) scale(1); }
    50% { transform: rotate(180deg) scale(1.05); }
  }

  .gauge-container {
    position: relative;
    display: flex;
    justify-content: center;
    margin: var(--space-4) 0;
  }

  .gauge-value {
    position: absolute;
    bottom: 10px;
    font-size: 2.5rem;
    font-weight: 800;
    color: var(--primary-600);
  }

  .status-badge {
    display: inline-block;
    padding: var(--space-2) var(--space-4);
    border-radius: var(--radius-full);
    font-size: 0.875rem;
    font-weight: 600;
  }

  .status-badge--excellent {
    background: var(--success-50);
    color: var(--success-700);
  }

  .status-badge--good {
    background: var(--primary-50);
    color: var(--primary-700);
  }

  .status-badge--fair {
    background: var(--warning-50);
    color: var(--warning-700);
  }

  .gauge-explanation {
    font-size: 0.9375rem;
    line-height: 1.6;
  }

  .explanation-text {
    margin-bottom: var(--space-4);
    color: var(--gray-700);
  }

  .explanation-section {
    margin-bottom: var(--space-4);
  }

  .explanation-section h5 {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--primary-700);
    margin-bottom: var(--space-2);
  }

  .explanation-section p {
    color: var(--gray-600);
  }

  .explanation-metrics {
    display: grid;
    gap: var(--space-3);
    margin-top: var(--space-4);
  }

  .metric-item {
    padding: var(--space-3);
    background: var(--gray-50);
    border-radius: var(--radius-md);
  }

  .metric-label {
    font-weight: 600;
    color: var(--gray-900);
    margin-bottom: var(--space-1);
  }

  .metric-desc {
    font-size: 0.8125rem;
    color: var(--gray-600);
  }
</style>

<script>
  function flipCard(cardId) {
    const card = document.getElementById(cardId);
    card.classList.toggle('flipped');

    // Animate with anime.js
    anime({
      targets: `#${cardId} .gauge-card__inner`,
      rotateY: card.classList.contains('flipped') ? 180 : 0,
      duration: 600,
      easing: 'easeInOutQuad'
    });
  }

  function createGauge(canvasId, value, min, max, ideal Min, idealMax) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const centerX = 100;
    const centerY = 100;
    const radius = 80;
    const startAngle = Math.PI;
    const endAngle = 2 * Math.PI;

    // Clear canvas
    ctx.clearRect(0, 0, 200, 120);

    // Draw background arc
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, startAngle, endAngle);
    ctx.lineWidth = 20;
    ctx.strokeStyle = '#e5e5e5';
    ctx.stroke();

    // Draw ideal range
    const idealStartAngle = startAngle + (idealMin / max) * Math.PI;
    const idealEndAngle = startAngle + (idealMax / max) * Math.PI;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, idealStartAngle, idealEndAngle);
    ctx.lineWidth = 20;
    ctx.strokeStyle = '#10b981';
    ctx.globalAlpha = 0.3;
    ctx.stroke();
    ctx.globalAlpha = 1;

    // Draw value arc with gradient
    const valueAngle = startAngle + (value / max) * Math.PI;
    const gradient = ctx.createLinearGradient(0, 0, 200, 0);
    gradient.addColorStop(0, '#6c698d');
    gradient.addColorStop(1, '#aa968a');

    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, startAngle, valueAngle);
    ctx.lineWidth = 20;
    ctx.strokeStyle = gradient;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Animate the gauge
    anime({
      targets: { value: 0 },
      value: value,
      duration: 1500,
      easing: 'easeOutQuad',
      update: function(anim) {
        const currentValue = anim.animations[0].currentValue;
        const currentAngle = startAngle + (currentValue / max) * Math.PI;

        ctx.clearRect(0, 0, 200, 120);

        // Redraw background
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, startAngle, endAngle);
        ctx.lineWidth = 20;
        ctx.strokeStyle = '#e5e5e5';
        ctx.stroke();

        // Redraw ideal range
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, idealStartAngle, idealEndAngle);
        ctx.lineWidth = 20;
        ctx.strokeStyle = '#10b981';
        ctx.globalAlpha = 0.3;
        ctx.stroke();
        ctx.globalAlpha = 1;

        // Draw current value
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, startAngle, currentAngle);
        ctx.lineWidth = 20;
        ctx.strokeStyle = gradient;
        ctx.lineCap = 'round';
        ctx.stroke();
      }
    });
  }

  // Initialize gauges on page load
  document.addEventListener('DOMContentLoaded', () => {
    // COD gauge (0-30 range, ideal 5-15)
    createGauge('cod-gauge', {{ neighborhood.cod|default:0 }}, 0, 30, 5, 15);

    // PRD gauge (0.8-1.2 range, ideal 0.98-1.03)
    createGauge('prd-gauge', {{ neighborhood.prd|default:1 }}, 0.8, 1.2, 0.98, 1.03);

    // Sales Ratio gauge (0.7-1.3 range, ideal 0.9-1.1)
    createGauge('sales-ratio-gauge', {{ neighborhood.sales_ratio|floatformat:2|div:100|default:1 }}, 0.7, 1.3, 0.9, 1.1);
  });
</script>
```

#### Similar implementation for PRD and Sales Ratio gauges with their respective explanations

### 6. PRD Explanation Content

**Front:**
- Gauge showing value (0.8 to 1.2 range)
- Ideal zone: 0.98-1.03 highlighted in green

**Back:**
- Title: "Price-Related Differential (PRD)"
- "The PRD tests for vertical assessment inequity – whether high-value and low-value properties are assessed at the same ratio."
- Calculation: Mean sales ratio ÷ Weighted mean sales ratio
- PRD = 1.00: Perfect vertical equity
- PRD > 1.03: Regressivity (high-value parcels under-appraised)
- PRD < 0.98: Progressivity (high-value parcels over-appraised)

### 7. Sales Ratio Explanation Content

**Front:**
- Gauge showing percentage (70% to 130% range)
- Ideal zone: 90%-110% highlighted in green

**Back:**
- Title: "Assessment to Sales Ratio"
- "This ratio compares assessed values to actual market values (sale prices)."
- Ideal: 1.0 or 100% (assessed value = market value)
- IAAO Standard: 0.90 to 1.10 (90% to 110%)
- Purpose: Ensures properties are assessed consistently and fairly relative to market value
- Your ratio: Shows if you're assessed above or below market

## Implementation Notes

1. All three gauge cards use the same flippable card structure
2. Anime.js provides smooth flip animations and gauge fill animations
3. Canvas-based gauges show ideal ranges in green
4. Each card has a pulsing flip indicator icon
5. Color palette updated throughout to Ethereal Grays theme
6. Leaflet map integration for comparables view
7. View switcher allows seamless transitions between list, grid, and map views

## Files to Update

1. `appeal_base_v3.html` - New base with updated colors and libraries
2. `appeal_home_v3.html` - Updated Step 1 with new autocomplete styling
3. `appeal_results_v3.html` - Step 2 with flippable gauge cards
4. `appeal_results_comparables_v3.html` - Step 3 with view switcher and map

## Next Steps

1. Test gauge animations on various COD/PRD/Sales Ratio values
2. Verify Leaflet map markers display correctly
3. Ensure flip animations work smoothly on mobile
4. Test reduced motion preferences
5. Verify all explanations are clear and accurate
