/**
 * Compare page map initialization.
 * Finds all map data blocks (nc-map-data-*) and initializes a Leaflet map
 * for each comparison column.
 */
(function () {
  "use strict";
  if (typeof L === "undefined") return;

  var CATEGORY_STYLES = {
    coffee:  { color: "#92400e" },
    grocery: { color: "#15803d" },
    fitness: { color: "#7c3aed" },
    parks:   { color: "#166534" },
  };

  function _esc(s) {
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(s || ""));
    return d.innerHTML;
  }

  // Find all map data script blocks (suffixed by compare_index)
  var dataEls = document.querySelectorAll('script[id^="nc-map-data"]');
  if (!dataEls.length) return;

  dataEls.forEach(function (dataEl) {
    var data;
    try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }

    var coords = data.coordinates;
    if (!coords || coords.lat == null || coords.lng == null) return;

    // Derive the container ID from the data element's ID
    // nc-map-data-1 -> neighborhood-map-leaflet-1
    var suffix = dataEl.id.replace("nc-map-data", "");
    var containerId = "neighborhood-map-leaflet" + suffix;
    var container = document.getElementById(containerId);
    if (!container) return;

    var map = L.map(container, {
      center: [coords.lat, coords.lng],
      zoom: 15,
      minZoom: 12,
      maxZoom: 18,
      scrollWheelZoom: false,
      zoomControl: true,
    });

    map.once("focus", function () { map.scrollWheelZoom.enable(); });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 20,
    }).addTo(map);

    var allLatLngs = [[coords.lat, coords.lng]];

    // Property marker
    L.circleMarker([coords.lat, coords.lng], {
      radius: 8,
      fillColor: "#2563eb",
      fillOpacity: 1,
      color: "#ffffff",
      weight: 2,
    }).addTo(map).bindPopup("<strong>Property</strong>");

    // Category markers
    var places = data.neighborhood_places || {};
    Object.keys(CATEGORY_STYLES).forEach(function (cat) {
      var items = places[cat];
      if (!items || !items.length) return;
      var style = CATEGORY_STYLES[cat];
      items.forEach(function (place) {
        if (place.lat == null || place.lng == null) return;
        allLatLngs.push([place.lat, place.lng]);
        var popup = "<strong>" + _esc(place.name) + "</strong>" +
          (place.walk_time_min != null ? "<br>" + place.walk_time_min + " min walk" : "");
        L.circleMarker([place.lat, place.lng], {
          radius: 5,
          fillColor: style.color,
          fillOpacity: 0.85,
          color: "#ffffff",
          weight: 2,
        }).addTo(map).bindPopup(popup);
      });
    });

    // Transit marker
    if (data.transit && data.transit.lat != null && data.transit.lng != null) {
      allLatLngs.push([data.transit.lat, data.transit.lng]);
      L.circleMarker([data.transit.lat, data.transit.lng], {
        radius: 6,
        fillColor: "#0369a1",
        fillOpacity: 0.9,
        color: "#ffffff",
        weight: 2,
      }).addTo(map).bindPopup("<strong>" + _esc(data.transit.name) + "</strong>" +
        (data.transit.walk_time_min != null ? "<br>" + data.transit.walk_time_min + " min walk" : ""));
    }

    if (allLatLngs.length > 1) {
      map.fitBounds(allLatLngs, { padding: [20, 20], maxZoom: 15 });
    }
  });
})();
