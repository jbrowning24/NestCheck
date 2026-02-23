/**
 * Section navigation highlighting for the report rail (NES-41).
 *
 * Uses IntersectionObserver to track which report section is currently
 * in view and highlights the corresponding link in the rail nav.
 * Also handles smooth-scroll on nav link clicks.
 */
(function () {
  "use strict";

  var nav = document.querySelector(".report-rail-nav");
  if (!nav) return;  // No rail nav — not on snapshot page or below breakpoint

  var links = nav.querySelectorAll(".rail-nav__link");
  if (!links.length) return;

  // Build a map of section ID → nav link
  var linkMap = {};
  links.forEach(function (link) {
    var sectionId = link.getAttribute("data-section");
    if (sectionId) linkMap[sectionId] = link;
  });

  var sectionIds = Object.keys(linkMap);
  var sections = [];
  sectionIds.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) sections.push({ id: id, el: el });
  });

  if (!sections.length) return;

  // ── IntersectionObserver ─────────────────────────────────────────────
  // rootMargin: negative top offset (below sticky nav) and negative bottom
  // so the "active" section is the one occupying the top 40% of the viewport.
  var currentActive = null;

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        setActive(entry.target.id);
      }
    });
  }, {
    rootMargin: "-80px 0px -60% 0px",
    threshold: 0
  });

  sections.forEach(function (s) { observer.observe(s.el); });

  function setActive(sectionId) {
    if (currentActive === sectionId) return;
    currentActive = sectionId;

    links.forEach(function (link) {
      link.classList.remove("rail-nav__link--active");
    });

    var activeLink = linkMap[sectionId];
    if (activeLink) {
      activeLink.classList.add("rail-nav__link--active");
    }
  }

  // ── Smooth scroll on click ──────────────────────────────────────────
  links.forEach(function (link) {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      var targetId = link.getAttribute("data-section");
      var target = document.getElementById(targetId);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        // Update active state immediately for responsiveness
        setActive(targetId);
      }
    });
  });
})();
