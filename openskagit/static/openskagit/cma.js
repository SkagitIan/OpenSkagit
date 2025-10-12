document.addEventListener("DOMContentLoaded", () => {
  if (window.htmx) {
    const csrfToken = document.cookie
      .split(";")
      .map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith("csrftoken="));
    if (csrfToken) {
      window.htmx.config.headers = window.htmx.config.headers || {};
      window.htmx.config.headers["X-CSRFToken"] = csrfToken.split("=")[1];
    }
  }

  const mapElement = document.getElementById("cma-map");
  if (!mapElement || typeof L === "undefined") {
    return;
  }

  const DEFAULT_CENTER = [48.5, -122.3];
  const DEFAULT_ZOOM = 11;

  const map = L.map(mapElement, { scrollWheelZoom: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  const markerLayer = L.layerGroup().addTo(map);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(map);

  const parcelNumber = mapElement.dataset.parcel;

  const parseMarkers = () => {
    const scriptEl = document.getElementById("cma-map-data");
    if (!scriptEl) {
      return [];
    }
    try {
      const payload = JSON.parse(scriptEl.textContent || "[]");
      scriptEl.remove();
      return Array.isArray(payload) ? payload : [];
    } catch (error) {
      console.warn("Unable to parse CMA marker payload", error);
      scriptEl.remove();
      return [];
    }
  };

  const updateMarkerLayer = (markers) => {
    markerLayer.clearLayers();
    if (!markers || !markers.length) {
      return;
    }
    markers.forEach((marker) => {
      if (!marker.lat || !marker.lon) {
        return;
      }
      const markerOptions =
        marker.type === "subject"
          ? { color: "#38bdf8", radius: 8, fillColor: "#38bdf8" }
          : { color: "#22c55e", radius: 6, fillColor: "#22c55e" };
      const leafletMarker = L.circleMarker([marker.lat, marker.lon], {
        radius: markerOptions.radius,
        color: markerOptions.color,
        weight: 2,
        fillOpacity: 0.7,
        fillColor: markerOptions.fillColor,
      });
      const popupLines = [];
      if (marker.address) {
        popupLines.push(`<strong>${marker.address}</strong>`);
      }
      if (marker.parcel_number) {
        popupLines.push(`Parcel ${marker.parcel_number}`);
      }
      if (marker.type !== "subject" && marker.adjusted_price) {
        popupLines.push(`Adj. Price $${Number(marker.adjusted_price).toLocaleString()}`);
      }
      leafletMarker.bindPopup(popupLines.join("<br>"));
      markerLayer.addLayer(leafletMarker);
    });
  };

  const initialMarkers = parseMarkers();
  if (initialMarkers.length) {
    updateMarkerLayer(initialMarkers);
    const subjectMarker = initialMarkers.find((item) => item.type === "subject");
    if (subjectMarker) {
      map.setView([subjectMarker.lat, subjectMarker.lon], 13);
    }
  }

  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (!event || !event.detail) {
      return;
    }
    const destination = event.target;
    if (!destination) {
      return;
    }
    const markers = parseMarkers();
    if (markers.length) {
      updateMarkerLayer(markers);
    }
  });

  let pendingViewportRequest = null;
  const requestViewportMarkers = () => {
    if (!parcelNumber || !window.htmx) {
      return;
    }
    if (pendingViewportRequest) {
      clearTimeout(pendingViewportRequest);
    }
    pendingViewportRequest = setTimeout(() => {
      const bounds = map.getBounds();
      const bbox = [
        bounds.getWest().toFixed(6),
        bounds.getSouth().toFixed(6),
        bounds.getEast().toFixed(6),
        bounds.getNorth().toFixed(6),
      ].join(",");
      const params = new URLSearchParams({ bbox });
      const filterForm = document.getElementById("cma-filter-form");
      if (filterForm) {
        const formData = new FormData(filterForm);
        for (const [key, value] of formData.entries()) {
          if (value !== null && value !== "") {
            params.append(key, value);
          }
        }
      }
      const url = `/cma/map/${parcelNumber}/?${params.toString()}`;
      window.htmx.ajax("GET", url, { target: "#cma-map-payload", swap: "innerHTML" });
    }, 250);
  };

  map.on("moveend", requestViewportMarkers);
});
