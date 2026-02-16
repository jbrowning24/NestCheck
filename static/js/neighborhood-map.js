/**
 * Interactive neighborhood map using Leaflet.js + CartoDB Positron tiles.
 *
 * Reads map data from a JSON script block (#nc-map-data) embedded in the
 * template.  Renders the property pin, POI markers by category, and an
 * optional transit station marker.  Provides layer-toggle controls so
 * users can show/hide categories independently.
 *
 * No additional API calls — uses data already collected during evaluation.
 */
(function () {
  "use strict";

  // ── Guards ─────────────────────────────────────────────────────────
  if (typeof L === "undefined") return;      // Leaflet CDN failed — degrade silently

  var dataEl = document.getElementById("nc-map-data");
  if (!dataEl) return;                       // No map data — nothing to render

  var data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;                                   // Malformed JSON — degrade silently
  }

  var coords = data.coordinates;
  if (!coords || coords.lat == null || coords.lng == null) return;

  // ── Map init ──────────────────────────────────────────────────────
  var container = document.getElementById("neighborhood-map-leaflet");
  if (!container) return;

  var map = L.map(container, {
    center: [coords.lat, coords.lng],
    zoom: 15,
    minZoom: 12,
    maxZoom: 18,
    scrollWheelZoom: false,                   // Prevent accidental zoom while scrolling page
    zoomControl: true,
  });

  // Enable scroll-wheel zoom only after user clicks the map (intentional interaction)
  map.once("focus", function () { map.scrollWheelZoom.enable(); });

  // CartoDB Positron — muted tile palette that lets markers stand out
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
                 '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 20,
  }).addTo(map);

  // ── Colors (match map_generator.py) ───────────────────────────────
  var CATEGORY_STYLES = {
    coffee:  { color: "#92400e", label: "Coffee" },
    grocery: { color: "#15803d", label: "Grocery" },
    fitness: { color: "#7c3aed", label: "Fitness" },
    parks:   { color: "#166534", label: "Parks" },
  };
  var TRANSIT_COLOR = "#ea580c";
  var PROPERTY_COLOR = "#2563eb";

  // Collect all marker coords for bounds fitting
  var allLatLngs = [[coords.lat, coords.lng]];

  // ── Property marker ───────────────────────────────────────────────
  L.circleMarker([coords.lat, coords.lng], {
    radius: 10,
    fillColor: PROPERTY_COLOR,
    fillOpacity: 1,
    color: "#ffffff",
    weight: 3,
  }).addTo(map).bindPopup("<strong>Property</strong>");

  // ── Helper: build popup HTML for a place ──────────────────────────
  function placePopup(place) {
    var html = "<strong>" + _esc(place.name) + "</strong>";
    if (place.rating) {
      html += "<br>" + place.rating + " ★";
      if (place.review_count) html += " <span style='color:#64748b'>(" + place.review_count + ")</span>";
    }
    if (place.walk_time_min != null) {
      html += "<br>" + place.walk_time_min + " min walk";
    }
    return html;
  }

  /** Minimal HTML escaping for user-facing place names. */
  function _esc(s) {
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }

  // ── POI markers by category ───────────────────────────────────────
  var overlays = {};
  var places = data.neighborhood_places || {};

  Object.keys(CATEGORY_STYLES).forEach(function (cat) {
    var items = places[cat];
    if (!items || !items.length) return;

    var style = CATEGORY_STYLES[cat];
    var group = L.layerGroup();

    items.forEach(function (place) {
      if (place.lat == null || place.lng == null) return;
      allLatLngs.push([place.lat, place.lng]);

      L.circleMarker([place.lat, place.lng], {
        radius: 7,
        fillColor: style.color,
        fillOpacity: 0.85,
        color: "#ffffff",
        weight: 2,
      }).bindPopup(placePopup(place))
        .addTo(group);
    });

    group.addTo(map);                        // Visible by default
    overlays[style.label] = group;
  });

  // ── Transit marker ────────────────────────────────────────────────
  var transit = data.transit;
  if (transit && transit.lat != null && transit.lng != null) {
    allLatLngs.push([transit.lat, transit.lng]);

    var transitPopup = "<strong>" + _esc(transit.name) + "</strong>";
    if (transit.walk_time_min != null) {
      transitPopup += "<br>" + transit.walk_time_min + " min walk";
    }

    var transitGroup = L.layerGroup([
      L.circleMarker([transit.lat, transit.lng], {
        radius: 8,
        fillColor: TRANSIT_COLOR,
        fillOpacity: 0.9,
        color: "#ffffff",
        weight: 2,
      }).bindPopup(transitPopup),
    ]);

    transitGroup.addTo(map);
    overlays["Transit"] = transitGroup;
  }

  // ── Layer control ─────────────────────────────────────────────────
  if (Object.keys(overlays).length > 0) {
    L.control.layers(null, overlays, { collapsed: false }).addTo(map);
  }

  // ── Fit bounds to show all markers ────────────────────────────────
  if (allLatLngs.length > 1) {
    map.fitBounds(allLatLngs, { padding: [30, 30], maxZoom: 16 });
  }
})();
