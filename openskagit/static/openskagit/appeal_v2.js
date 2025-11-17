/* eslint-disable no-console */
(function () {
  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));

  const els = {
    stepDots: $$('.step-dot'),
    input: $('#parcel-search-input'),
    resultsPanel: $('#search-results-panel'),
    results: $('#search-results'),
    empty: $('#search-empty'),
    step1: $('#step-1'),
    step2: $('#step-2'),
    step3: $('#step-3'),
    subjectAddress: $('#subject-address'),
    assessedValue: $('#assessed-value'),
    assessedChange: $('#assessed-change'),
    neighChange: $('#neigh-change'),
    rating: $('#appeal-rating'),
    reasons: $('#appeal-reasons'),
    compsList: $('#comparables-list'),
    compsEmpty: $('#comps-empty'),
    loadMore: $('#load-more-comps'),
    chartCanvas: $('#neighborhood-chart'),
  };

  const state = {
    selectedParcel: null,
    subject: null,
    parcel: null,
    comparables: [],
    compsCurrentLimit: null,
    compsMaxLimit: null,
    map: null,
    markersByParcel: new Map(),
    subjectMarker: null,
    _compsController: null,
  };

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  async function fetchJSON(url, signal) {
    const res = await fetch(url, { headers: { 'Accept': 'application/json' }, signal });
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
  }

  function fmtMoney(v) {
    if (v == null || isNaN(v)) return '—';
    try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v); } catch (e) { return `$${Math.round(v).toLocaleString()}`; }
  }
  function fmtPct(v) {
    if (v == null || isNaN(v)) return '—';
    return `${(Math.round(v * 10) / 10).toFixed(1)}%`;
  }
  function fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString();
  }

  function setStep(activeIdx) {
    els.stepDots.forEach((dot, idx) => {
      if (idx === activeIdx) {
        dot.classList.remove('bg-zinc-200', 'text-zinc-600');
        dot.classList.add('bg-dusty-grape', 'text-white');
      } else {
        dot.classList.add('bg-zinc-200', 'text-zinc-600');
        dot.classList.remove('bg-dusty-grape', 'text-white');
      }
    });
  }

  function show(el) { el.classList.remove('hidden'); }
  function hide(el) { el.classList.add('hidden'); }
  function clear(el) { el.innerHTML = ''; }

  function renderSearchResults(items) {
    clear(els.results);
    if (!items || !items.length) {
      hide(els.results);
      show(els.empty);
      return;
    }
    hide(els.empty);
    show(els.results);
    for (const it of items) {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'w-full text-left px-3 py-2 hover:bg-dust-grey/40 focus:bg-dust-grey/50';
      btn.innerHTML = `<div class="font-medium text-dim-grey">${(it.address || '').replace(/</g,'&lt;')}</div>
        <div class="text-xs text-zinc-500">${it.parcel_number}</div>`;
      btn.addEventListener('click', () => {
        selectParcel(it.parcel_number);
      });
      li.appendChild(btn);
      els.results.appendChild(li);
    }
  }

  let searchController = null;
  const doSearch = debounce(async (q) => {
    if (!q || q.length < 3) {
      hide(els.results); show(els.empty);
      return;
    }
    try {
      if (searchController) searchController.abort();
      searchController = new AbortController();
      const data = await fetchJSON(window.APPEAL_API.search(q), searchController.signal);
      renderSearchResults(data.results || []);
    } catch (e) {
      if (e.name === 'AbortError') return; // cancelled due to new keystroke
      console.error(e);
      clear(els.results);
      hide(els.results);
      els.empty.textContent = 'Search unavailable. Try again.';
      show(els.empty);
    }
  }, 300);

  function ensureMap() {
    if (state.map) return state.map;
    const map = L.map('appeal-map');
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    state.map = map;
    return map;
  }

  function setSubjectMarker(lat, lon, label) {
    const map = ensureMap();
    if (state.subjectMarker) {
      state.subjectMarker.setLatLng([lat, lon]);
    } else {
      state.subjectMarker = L.marker([lat, lon], { title: label || 'Subject' }).addTo(map);
    }
    state.subjectMarker.bindPopup(`<strong>${label || 'Subject'}</strong>`);
  }

  async function fetchCompCoords(comp) {
    if (!comp || !comp.parcel_number) return null;
    if (state.markersByParcel.has(comp.parcel_number)) return null; // already placed
    try {
      const d = await fetchJSON(window.APPEAL_API.parcel(comp.parcel_number));
      const lat = d?.location?.latitude;
      const lon = d?.location?.longitude;
      if (lat != null && lon != null) {
        const m = L.marker([lat, lon], { title: comp.address || comp.parcel_number });
        m.bindPopup(`<div class="text-sm"><div class="font-medium">${(comp.address || comp.parcel_number).replace(/</g,'&lt;')}</div>
          <div>Sale: <strong>${fmtMoney(comp.sale_price)}</strong> on ${fmtDate(comp.sale_date)}</div>
          <div>Assessed: ${fmtMoney(comp.assessed_value)} • ${comp.distance_miles ? comp.distance_miles.toFixed(2) + ' mi' : ''}</div></div>`);
        m.addTo(state.map);
        state.markersByParcel.set(comp.parcel_number, m);
      }
    } catch (e) {
      // ignore fetch failures for individual comps
    }
  }

  function fitMap() {
    const markers = [state.subjectMarker, ...state.markersByParcel.values()].filter(Boolean);
    if (!markers.length) return;
    const group = L.featureGroup(markers);
    state.map.fitBounds(group.getBounds().pad(0.2));
  }

  function renderSubjectAndNeighborhood() {
    const subj = state.subject?.subject || {};
    const assess = state.subject?.assessment || {};
    const neighborhood = state.subject?.neighborhood || {};
    const addr = subj.address || state.parcel?.address || '';
    els.subjectAddress.textContent = `${addr} • ${state.selectedParcel}`;
    els.assessedValue.textContent = fmtMoney(assess.assessed_value);
    els.assessedChange.textContent = assess.change_pct == null ? '—' : fmtPct(assess.change_pct);
    const avgChange = neighborhood?.avg_increase_pct;
    els.neighChange.textContent = avgChange == null ? '—' : fmtPct(avgChange);
    // Hide analysis until comparables are requested
    els.rating.classList.add('hidden');
    els.reasons.textContent = '';

    // Bar chart: your change vs neighborhood
    try {
      if (els.chartCanvas) {
        const ctx = els.chartCanvas.getContext('2d');
        if (state._chart) state._chart.destroy();
        state._chart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels: ['You', 'Neighborhood'],
            datasets: [{
              label: 'Assessment change %',
              data: [assess.change_pct ?? 0, avgChange ?? 0],
              backgroundColor: ['#6C698D', '#BFAFA6'],
              borderRadius: 6,
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
              y: { ticks: { callback: (v) => `${v}%` } }
            }
          }
        });
      }
    } catch (e) {
      // chart failures are non-blocking
    }
  }

  function renderComparables() {
    const items = state.comparables || [];
    clear(els.compsList);
    if (!items.length) { show(els.compsEmpty); return; }
    hide(els.compsEmpty);
    for (const c of items) {
      const li = document.createElement('li');
      li.className = 'py-3';
      li.innerHTML = `
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="font-medium text-dim-grey">${(c.address || c.parcel_number).replace(/</g,'&lt;')}</div>
            <div class="text-xs text-zinc-500">${c.parcel_number} • ${c.distance_miles ? c.distance_miles.toFixed(2) + ' mi' : ''}</div>
          </div>
          <div class="text-right">
            <div class="text-sm">Sale: <span class="font-semibold">${fmtMoney(c.sale_price)}</span></div>
            <div class="text-xs text-zinc-500">${fmtDate(c.sale_date)}</div>
          </div>
        </div>
        <div class="mt-1 text-xs text-zinc-600">Assessed ${fmtMoney(c.assessed_value)} • ${c.bedrooms ?? '—'} bd • ${c.bathrooms ?? '—'} ba • ${c.living_area_sqft ?? '—'} sf • ${c.year_built ?? '—'}</div>`;
      els.compsList.appendChild(li);
    }

    if (state.compsCurrentLimit && state.compsMaxLimit && state.compsCurrentLimit < state.compsMaxLimit) {
      els.loadMore.classList.remove('hidden');
    } else {
      els.loadMore.classList.add('hidden');
    }
  }

  function advanceToSteps() {
    hide(els.step1); show(els.step2); hide(els.step3); setStep(1);
  }

  async function selectParcel(parcelNumber) {
    state.selectedParcel = parcelNumber;
    hide(els.results);
    // Parallel fetch core datasets
    try {
      const [subject, parcel] = await Promise.all([
        fetchJSON(window.APPEAL_API.subject(parcelNumber)),
        fetchJSON(window.APPEAL_API.parcel(parcelNumber))
      ]);
      state.subject = subject; state.parcel = parcel;
      state.comparables = []; state.compsCurrentLimit = null; state.compsMaxLimit = null;

      // Render
      advanceToSteps();
      renderSubjectAndNeighborhood();

      // Defer map until Step 3
      setStep(1);
    } catch (e) {
      console.error(e);
      alert('Unable to load parcel. Please try again.');
    }
  }

  async function loadComparables() {
    if (!state.selectedParcel) return;
    try {
      if (state._compsController) state._compsController.abort();
      state._compsController = new AbortController();

      // Show Step 3 and reveal map
      show(els.step3);
      const mapPanel = document.getElementById('map-panel');
      if (mapPanel) mapPanel.classList.remove('hidden');
      setStep(2);
      els.loadMore?.classList.add('hidden');
      clear(els.compsList); hide(els.compsEmpty);

      const compsRes = await fetchJSON(window.APPEAL_API.comparables(state.selectedParcel), state._compsController.signal);
      state.comparables = compsRes.comparables || [];
      state.compsCurrentLimit = compsRes.current_limit || state.comparables.length;
      state.compsMaxLimit = compsRes.max_limit || state.comparables.length;

      // Use rating/reasons from comparables payload to update Step 2
      const rating = (compsRes.rating || '').toString();
      if (rating) {
        els.rating.textContent = rating.replace('-', ' ').replace(/\b\w/g, c => c.toUpperCase());
        els.rating.classList.remove('hidden');
        if (rating.includes('strong')) {
          els.rating.classList.add('bg-dusty-grape','text-white');
          els.rating.classList.remove('bg-zinc-100','text-zinc-700');
        } else {
          els.rating.classList.remove('bg-dusty-grape','text-white');
          els.rating.classList.add('bg-zinc-100','text-zinc-700');
        }
      }
      const reasons = Array.isArray(compsRes.reasons) ? compsRes.reasons : [];
      if (reasons.length) {
        els.reasons.innerHTML = `<ul class="list-disc ml-5 space-y-1">${reasons.map(r => `<li>${String(r).replace(/</g,'&lt;')}</li>`).join('')}</ul>`;
      }

      renderComparables();

      // Ensure map and add the subject marker
      ensureMap();
      const lat = state.parcel?.location?.latitude, lon = state.parcel?.location?.longitude;
      if (lat != null && lon != null) {
        setSubjectMarker(lat, lon, state.parcel.address || state.selectedParcel);
      }

      // Add comp markers (best-effort) and fit bounds
      const maxParallel = 4;
      let i = 0;
      async function next() {
        if (i >= state.comparables.length) return;
        const c = state.comparables[i++];
        await fetchCompCoords(c);
        await next();
      }
      await Promise.all(new Array(maxParallel).fill(0).map(next));
      fitMap();
    } catch (e) {
      if (e.name === 'AbortError') return;
      console.error(e);
    }
  }

  async function loadMoreComps() {
    if (!state.selectedParcel) return;
    const targetCount = state.compsMaxLimit || 30;
    try {
      const compsRes = await fetchJSON(window.APPEAL_API.comparables(state.selectedParcel, targetCount));
      state.comparables = compsRes.comparables || [];
      state.compsCurrentLimit = compsRes.current_limit || state.comparables.length;
      state.compsMaxLimit = compsRes.max_limit || state.comparables.length;
      renderComparables();
      // add markers for any new comps
      const toFetch = state.comparables.filter(c => !state.markersByParcel.has(c.parcel_number));
      for (const c of toFetch) { await fetchCompCoords(c); }
      fitMap();
    } catch (e) {
      console.error(e);
    }
  }

  function initFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const pn = params.get('parcel');
    if (pn) {
      selectParcel(pn);
    }
  }

  function initEvents() {
    if (!els.input) return;
    els.input.addEventListener('input', (e) => doSearch(e.target.value.trim()))
    els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const first = els.results.querySelector('button');
        if (first) first.click();
      }
    })
    els.loadMore.addEventListener('click', loadMoreComps);
    const cont = document.getElementById('step2-continue');
    if (cont) cont.addEventListener('click', loadComparables);
  }

  document.addEventListener('DOMContentLoaded', () => {
    initEvents();
    initFromQuery();
    // Default UI state
    setStep(0);
    hide(els.results);
    show(els.empty);
  });
})();
