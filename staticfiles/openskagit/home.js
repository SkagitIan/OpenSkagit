document.addEventListener("DOMContentLoaded", function () {
    const mapContainer = document.getElementById("parcel-map");
    if (!mapContainer || typeof L === "undefined") {
        return;
    }

    const map = L.map(mapContainer, {
        scrollWheelZoom: true,
        zoomControl: true,
    }).setView([48.472, -122.337], 11);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 19,
    }).addTo(map);

    const sampleParcels = [
        {
            name: "Sample Parcel P78901",
            center: [48.4755, -122.331],
            coordinates: [
                [48.4783, -122.334],
                [48.4771, -122.326],
                [48.4738, -122.327],
                [48.4746, -122.336],
            ],
        },
        {
            name: "Sample Parcel P12345",
            center: [48.4301, -122.345],
            coordinates: [
                [48.4322, -122.349],
                [48.4316, -122.339],
                [48.4284, -122.339],
                [48.4286, -122.347],
            ],
        },
    ];

    const parcelLayerGroup = L.layerGroup().addTo(map);

    function renderSampleParcels() {
        parcelLayerGroup.clearLayers();
        sampleParcels.forEach(function (parcel) {
            const polygon = L.polygon(parcel.coordinates, {
                color: "#3f8cff",
                weight: 2,
                fillColor: "#3f8cff",
                fillOpacity: 0.18,
            });

            polygon.bindPopup(
                "<strong>" +
                    parcel.name +
                    "</strong><br>Hook this to your parcel geometry service."
            );

            polygon.addTo(parcelLayerGroup);
        });
    }

    renderSampleParcels();

    const searchInput = document.getElementById("parcel-search");
    const searchButton = document.getElementById("parcel-search-btn");
    const mapHint = document.querySelector(".map-hint");

    function focusSampleParcel() {
        const term = (searchInput.value || "").trim();
        if (!term) {
            mapHint.textContent =
                "Type a parcel number or address to center the map. Results will appear here.";
            return;
        }

        const match = sampleParcels.find(function (parcel) {
            return parcel.name.toLowerCase().includes(term.toLowerCase());
        });

        if (match) {
            map.flyTo(match.center, 15, { duration: 0.8 });
            mapHint.textContent =
                "Centered on " +
                match.name +
                ". Replace this mock search with your vector powered lookup.";
        } else {
            mapHint.textContent =
                "No mock parcel found. Integrate the real dataset to surface live results.";
        }
    }

    if (searchButton) {
        searchButton.addEventListener("click", focusSampleParcel);
    }

    if (searchInput) {
        searchInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                focusSampleParcel();
            }
        });
    }
});
