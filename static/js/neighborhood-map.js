/**
 * Interactive neighborhood map using Leaflet.js + CartoDB Positron tiles.
 *
 * Reads map data from a JSON script block (#nc-map-data) embedded in the
 * template.  Renders the property pin, POI markers by category, and an
 * optional transit station marker.  Provides layer-toggle controls so
 * users can show/hide categories independently.
 *
 * Supports dual containers: rail map (#rail-map-leaflet) on desktop and
 * inline map (#neighborhood-map-leaflet) on mobile.  Initializes whichever
 * container(s) are visible.  Handles viewport resize across the 1200px
 * breakpoint with invalidateSize().
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

  // ── Shared config ───────────────────────────────────────────────────
  var CATEGORY_STYLES = {
    coffee:  { color: "#92400e", label: "Coffee" },
    grocery: { color: "#15803d", label: "Grocery" },
    fitness: { color: "#7c3aed", label: "Fitness" },
    parks:   { color: "#166534", label: "Parks" },
  };
  var TRANSIT_COLOR = "#ea580c";
  var PROPERTY_COLOR = "#2563eb";

  /** Minimal HTML escaping for user-facing place names. */
  function _esc(s) {
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }

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

  // ── Initialize a map on a given container element ───────────────────
  function initMap(container, opts) {
    opts = opts || {};
    var compact = opts.compact || false;  // Rail map: smaller markers, collapsed controls

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
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
                   '&copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 20,
    }).addTo(map);

    var allLatLngs = [[coords.lat, coords.lng]];

    // Property marker
    L.circleMarker([coords.lat, coords.lng], {
      radius: compact ? 8 : 10,
      fillColor: PROPERTY_COLOR,
      fillOpacity: 1,
      color: "#ffffff",
      weight: compact ? 2 : 3,
    }).addTo(map).bindPopup("<strong>Property</strong>");

    // POI markers by category
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
          radius: compact ? 5 : 7,
          fillColor: style.color,
          fillOpacity: 0.85,
          color: "#ffffff",
          weight: 2,
        }).bindPopup(placePopup(place))
          .addTo(group);
      });

      group.addTo(map);
      overlays[style.label] = group;
    });

    // Transit marker
    var transit = data.transit;
    if (transit && transit.lat != null && transit.lng != null) {
      allLatLngs.push([transit.lat, transit.lng]);

      var transitPopup = "<strong>" + _esc(transit.name) + "</strong>";
      if (transit.walk_time_min != null) {
        transitPopup += "<br>" + transit.walk_time_min + " min walk";
      }

      var transitGroup = L.layerGroup([
        L.circleMarker([transit.lat, transit.lng], {
          radius: compact ? 6 : 8,
          fillColor: TRANSIT_COLOR,
          fillOpacity: 0.9,
          color: "#ffffff",
          weight: 2,
        }).bindPopup(transitPopup),
      ]);

      transitGroup.addTo(map);
      overlays["Transit"] = transitGroup;
    }

    // Layer control
    if (Object.keys(overlays).length > 0) {
      L.control.layers(null, overlays, { collapsed: compact }).addTo(map);
    }

    // Fit bounds
    if (allLatLngs.length > 1) {
      map.fitBounds(allLatLngs, { padding: compact ? [20, 20] : [30, 30], maxZoom: 16 });
    }

    return map;
  }

  // ── Container detection & init ──────────────────────────────────────
  var inlineContainer = document.getElementById("neighborhood-map-leaflet");
  var railContainer = document.getElementById("rail-map-leaflet");

  function isVisible(el) {
    return el && el.offsetParent !== null;
  }

  var maps = [];

  // Initialize visible containers
  if (railContainer && isVisible(railContainer)) {
    maps.push({ el: railContainer, map: initMap(railContainer, { compact: true }), id: "rail" });
  }
  if (inlineContainer && isVisible(inlineContainer)) {
    maps.push({ el: inlineContainer, map: initMap(inlineContainer, { compact: false }), id: "inline" });
  }

  // If neither is visible yet (e.g., page still loading), fall back to inline
  if (maps.length === 0 && inlineContainer) {
    maps.push({ el: inlineContainer, map: initMap(inlineContainer, { compact: false }), id: "inline" });
  }

  // ── Handle viewport resize across 1200px breakpoint ─────────────────
  // When the layout switches between rail/inline, the newly visible map
  // needs invalidateSize() to render tiles correctly.
  if (railContainer && inlineContainer) {
    var mql = window.matchMedia("(min-width: 1200px)");
    var railInited = maps.some(function (m) { return m.id === "rail"; });
    var inlineInited = maps.some(function (m) { return m.id === "inline"; });

    mql.addEventListener("change", function (e) {
      if (e.matches) {
        // Switched to desktop — rail visible
        if (!railInited) {
          maps.push({ el: railContainer, map: initMap(railContainer, { compact: true }), id: "rail" });
          railInited = true;
        } else {
          maps.forEach(function (m) { if (m.id === "rail") m.map.invalidateSize(); });
        }
      } else {
        // Switched to mobile — inline visible
        if (!inlineInited) {
          maps.push({ el: inlineContainer, map: initMap(inlineContainer, { compact: false }), id: "inline" });
          inlineInited = true;
        } else {
          maps.forEach(function (m) { if (m.id === "inline") m.map.invalidateSize(); });
        }
      }
    });
  }
})();
