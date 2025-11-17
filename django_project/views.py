from django.http import HttpResponse, HttpRequest

hero = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1.0" />
  <title>Property Tax Appeal Helper</title>
  <style>
    :root {
      color-scheme: light;
      font-family: "Inter", "Segoe UI", system-ui, sans-serif;
      background-color: #f5f7fb;
      color: #0f172a;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      background: linear-gradient(180deg,#eef1fb 0%,#f7f8ff 70%,#ffffff 100%);
      min-height: 100vh;
    }
    .page {
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }
    .brand {
      text-align: center;
      margin-bottom: 40px;
    }
    .brand h1 {
      margin: 0;
      font-size: 2rem;
      letter-spacing: 0.04em;
    }
    .brand p {
      margin: 12px auto 0;
      max-width: 540px;
      color: #42516b;
    }
    .progress {
      display: grid;
      grid-template-columns: repeat(3,1fr);
      gap: 12px;
      margin-bottom: 32px;
    }
    .progress button {
      background: #dfe4ff;
      border: none;
      border-radius: 999px;
      padding: 10px 16px;
      font-weight: 600;
      color: #4b56c2;
      letter-spacing: 0.05em;
      cursor: pointer;
    }
    .progress button.active {
      background: linear-gradient(135deg,#5c61e5,#6e8dff);
      color: #fff;
      box-shadow: 0 10px 25px rgba(92,97,229,.25);
    }
    .card {
      background: #fff;
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 25px 80px rgba(15,23,42,.08);
      margin-bottom: 32px;
      border: 1px solid rgba(99,102,241,.1);
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 1.4rem;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .card small {
      display: block;
      color: #6b7280;
    }
    .step-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 16px;
      font-size: 0.95rem;
      color: #4b5563;
      font-weight: 600;
    }
    .icon {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: rgba(59,130,246,.15);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: #2563eb;
      font-size: 1.2rem;
    }
    .address-input {
      width: 100%;
      margin-top: 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .address-input input {
      border-radius: 12px;
      border: 1px solid #d1d5db;
      padding: 14px 16px;
      font-size: 1rem;
      transition: border .2s ease,box-shadow .2s ease;
    }
    .address-input input:focus {
      outline: none;
      border-color: #6366f1;
      box-shadow: 0 0 0 3px rgba(99,102,241,.2);
    }
    .address-input small {
      background: #f1f5ff;
      border-radius: 10px;
      padding: 12px 14px;
      color: #475569;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.9rem;
    }
    .address-input button {
      border-radius: 14px;
      border: none;
      font-weight: 600;
      font-size: 1rem;
      padding: 14px;
      background: #5c61e5;
      color: #fff;
      cursor: pointer;
      margin-top: 6px;
    }
    .snapshot-grid {
      display: grid;
      gap: 16px;
    }
    .detail-card {
      border-radius: 18px;
      border: 1px solid rgba(99,102,241,.25);
      background: linear-gradient(180deg,#eef2ff,#fff);
      padding: 20px;
    }
    .detail-card strong {
      font-size: 1.6rem;
      display: block;
      color: #111827;
    }
    .detail-card span {
      color: #475569;
      display: block;
      margin-top: 4px;
    }
    .property-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit,minmax(140px,1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .property-grid div {
      background: #fff;
      border-radius: 12px;
      padding: 12px 14px;
      border: 1px solid #e2e8f0;
      font-size: 0.9rem;
    }
    .property-grid div strong {
      display: block;
      font-size: 1.2rem;
      color: #111827;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px;
      border-radius: 12px;
      background: #f8fafc;
      border: 1px solid #e5e7eb;
      margin-bottom: 10px;
    }
    .metric-row strong {
      font-size: 1rem;
      color: #374151;
    }
    .metric-caption {
      color: #6b7280;
      font-size: 0.85rem;
    }
    .metric-value {
      font-size: 1.3rem;
      font-weight: 600;
    }
    .metric-positive .metric-value {
      color: #047857;
    }
    .metric-warning .metric-value {
      color: #c2410c;
    }
    .section-cta {
      display: flex;
      justify-content: flex-end;
      margin-top: 16px;
    }
    .section-cta button {
      background: #16a34a;
      color: #fff;
      border: none;
      border-radius: 16px;
      padding: 14px 20px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 18px 35px rgba(22,163,74,.25);
    }
    .comparables-list {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .comparable {
      border-radius: 14px;
      border: 1px solid #e2e8f0;
      padding: 12px 14px;
      background: #fff;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
    }
    .comparable h3 {
      margin: 0;
      font-size: 1rem;
      color: #111827;
    }
    .comparable small {
      color: #6b7280;
    }
    .comparable-price {
      font-size: 1.3rem;
      font-weight: 700;
      color: #1d4ed8;
    }
    .comparable .tags {
      display: flex;
      gap: 8px;
      margin-top: 6px;
    }
    .tag {
      font-size: 0.75rem;
      padding: 4px 8px;
      border-radius: 999px;
      background: #e0e7ff;
      color: #3730a3;
    }
    .summary-banner {
      border-radius: 18px;
      padding: 16px 20px;
      background: #fef3c7;
      color: #92400e;
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
      border: 1px solid #fde68a;
    }
    .summary-banner span {
      font-weight: 600;
    }
    .bottom-cta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 24px;
      flex-wrap: wrap;
      gap: 14px;
    }
    .bottom-cta button {
      background: #4f46e5;
      border: none;
      border-radius: 16px;
      padding: 14px 28px;
      color: #fff;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 20px 35px rgba(79,70,229,.35);
    }
    @media (max-width: 768px) {
      .progress {
        grid-template-columns: 1fr;
      }
      .comparable {
        grid-template-columns: 1fr;
      }
      .bottom-cta {
        flex-direction: column;
        align-items: stretch;
      }
      .section-cta {
        justify-content: stretch;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="brand">
      <h1>Property Tax Appeal Helper</h1>
      <p>Simple steps help you see if an appeal is worth your time—no jargon, just guidance.</p>
    </div>
    <div class="progress">
      <button class="active">1. Your Address</button>
      <button>2. Neighborhood Snapshot</button>
      <button>3. Comparable Sales</button>
    </div>

    <div class="card">
      <div class="step-header">
        <span class="icon">📍</span>
        Step 1 — Address Entry
      </div>
      <h2>Enter your home or parcel</h2>
      <p>This is actually pretty good! Keep it simple, then tap continue when ready.</p>
      <div class="address-input">
        <input type="text" placeholder="e.g., 101 Main St or P12345" />
        <small>Tip: an increasing assessment alone doesn’t mean higher taxes. We look at nearby homes too.</small>
        <button>Continue to Assessment Review →</button>
      </div>
    </div>

    <div class="card">
      <div class="step-header">
        <span class="icon">📊</span>
        Step 2 — Neighborhood Snapshot
      </div>
      <div class="summary-banner">
        <span>Looking good! ✓</span>
        Your assessed value is higher than most comparable homes, so an appeal could be worth exploring.
      </div>
      <h2>Your Property Details</h2>
      <div class="snapshot-grid">
        <div class="detail-card">
          <strong>$453,500</strong>
          <span>2025 Assessed Value · 813 Cultus Mountain Dr · Sedro Woolley, WA 98284</span>
          <div class="property-grid">
            <div><strong>3</strong><span>Bedrooms</span></div>
            <div><strong>1,166</strong><span>Living Area (sq ft)</span></div>
            <div><strong>1992</strong><span>Year Built</span></div>
            <div><strong>0.21</strong><span>Lot Size (acres)</span></div>
          </div>
        </div>
      </div>

      <h2>How you compare to neighbors</h2>
      <div class="metric-row metric-positive">
        <div>
          <strong>Assessment vs. Market</strong>
          <p class="metric-caption">Your assessment is around 94% of nearby sales—higher than 5 of 6 comparables.</p>
        </div>
        <span class="metric-value">94.19%</span>
      </div>
      <div class="metric-row">
        <div>
          <strong>Neighborhood Uniformity (COD)</strong>
          <p class="metric-caption">Lower numbers mean assessments are steady across the area.</p>
        </div>
        <span class="metric-value">6.50</span>
      </div>
      <div class="metric-row metric-warning">
        <div>
          <strong>Price Range Dispersion (PRD)</strong>
          <p class="metric-caption">Above 1.00 shows values vary more than the ideal range.</p>
        </div>
        <span class="metric-value">1.04</span>
      </div>
      <div class="section-cta">
        <button>View Comparable Sales →</button>
      </div>
    </div>

    <div class="card">
      <div class="step-header">
        <span class="icon">🏡</span>
        Step 3 — Comparable Sales
      </div>
      <h2>Key finding</h2>
      <p>We found 6 comparable sales. Your assessed value is higher than five of them—this is the gap to highlight.</p>
      <div class="comparables-list">
        <article class="comparable">
          <div>
            <h3>805 Cultus Mountain Dr</h3>
            <small>Sold Jul 14, 2025 · 3 beds · 1,325 sq ft</small>
            <div class="tags">
              <span class="tag">Assessed $475,200</span>
              <span class="tag">Recent sale</span>
            </div>
          </div>
          <div class="comparable-price">$545,000</div>
        </article>
        <article class="comparable">
          <div>
            <h3>824 Orth Way</h3>
            <small>Sold Jul 16, 2025 · 3 beds · 1,776 sq ft</small>
            <div class="tags">
              <span class="tag">Assessed $593,500</span>
              <span class="tag">Close size</span>
            </div>
          </div>
          <div class="comparable-price">$700,000</div>
        </article>
        <article class="comparable">
          <div>
            <h3>812 Dana Dr</h3>
            <small>Sold Oct 22, 2025 · 4 beds · 1,421 sq ft</small>
            <div class="tags">
              <span class="tag">Assessed $474,500</span>
              <span class="tag">Higher story count</span>
            </div>
          </div>
          <div class="comparable-price">$570,000</div>
        </article>
        <article class="comparable">
          <div>
            <h3>729 Sauk Mountain Dr</h3>
            <small>Sold Jun 23, 2025 · 3 beds · 1,439 sq ft</small>
            <div class="tags">
              <span class="tag">Assessed $484,600</span>
              <span class="tag">Matching vibe</span>
            </div>
          </div>
          <div class="comparable-price">$535,000</div>
        </article>
      </div>
      <div class="section-cta">
        <button>Show more comparables</button>
      </div>
      <div class="bottom-cta">
        <span>Ready to appeal? Download a summary that outlines the gap and reference sales.</span>
        <button>Download Appeal Report</button>
      </div>
    </div>
  </div>
</body>
</html>
"""

def index(request: HttpRequest) -> HttpResponse:
    return HttpResponse(hero)
