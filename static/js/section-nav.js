/**
 * Section navigation highlighting for report pages (NES-41, NES-323).
 *
 * Uses a single IntersectionObserver to track which report section is
 * currently in view and highlights the corresponding link in both the
 * desktop rail nav and the mobile sticky tab bar.
 * Also handles smooth-scroll on nav link clicks.
 */
(function () {
  "use strict";

  // ── Discover nav consumers ──────────────────────────────────────────
  var railNav = document.querySelector(".report-rail-nav");
  var tabBar = document.querySelector(".mobile-tab-bar");

  // Need at least one nav present to proceed
  if (!railNav && !tabBar) return;

  // Collect links from both consumers
  var railLinks = railNav ? railNav.querySelectorAll(".rail-nav__link") : [];
  var tabLinks = tabBar ? tabBar.querySelectorAll(".mobile-tab__link") : [];

  if (!railLinks.length && !tabLinks.length) return;

  // Build section ID → link maps for each consumer
  var railLinkMap = {};
  railLinks.forEach(function (link) {
    var id = link.getAttribute("data-section");
    if (id) railLinkMap[id] = link;
  });

  var tabLinkMap = {};
  tabLinks.forEach(function (link) {
    var id = link.getAttribute("data-section");
    if (id) tabLinkMap[id] = link;
  });

  // Union of all section IDs from both navs
  var allIds = {};
  Object.keys(railLinkMap).forEach(function (id) { allIds[id] = true; });
  Object.keys(tabLinkMap).forEach(function (id) { allIds[id] = true; });

  var sections = [];
  Object.keys(allIds).forEach(function (id) {
    var el = document.getElementById(id);
    if (el) sections.push({ id: id, el: el });
  });

  if (!sections.length) return;

  // ── IntersectionObserver ─────────────────────────────────────────────
  // rootMargin: -52px top (tab bar height 44px + 8px buffer) and -70%
  // bottom so the "active" section is the one occupying the top ~30%.
  var currentActive = null;

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        setActive(entry.target.id);
      }
    });
  }, {
    rootMargin: "-52px 0px -70% 0px",
    threshold: 0
  });

  sections.forEach(function (s) { observer.observe(s.el); });

  function setActive(sectionId) {
    if (currentActive === sectionId) return;
    currentActive = sectionId;

    // Update desktop rail nav
    railLinks.forEach(function (link) {
      link.classList.remove("rail-nav__link--active");
      link.removeAttribute("aria-current");
    });
    var activeRailLink = railLinkMap[sectionId];
    if (activeRailLink) {
      activeRailLink.classList.add("rail-nav__link--active");
      activeRailLink.setAttribute("aria-current", "true");
    }

    // Update mobile tab bar
    tabLinks.forEach(function (link) {
      link.classList.remove("mobile-tab__link--active");
      link.removeAttribute("aria-current");
    });
    var activeTabLink = tabLinkMap[sectionId];
    if (activeTabLink) {
      activeTabLink.classList.add("mobile-tab__link--active");
      activeTabLink.setAttribute("aria-current", "true");
      // Auto-scroll the tab bar to keep the active tab visible
      // Use scrollTo on the container to avoid vertical page scroll jank
      var bar = activeTabLink.closest(".mobile-tab-bar");
      if (bar) {
        var linkLeft = activeTabLink.offsetLeft;
        var linkWidth = activeTabLink.offsetWidth;
        var barWidth = bar.offsetWidth;
        bar.scrollTo({ left: linkLeft - (barWidth / 2) + (linkWidth / 2), behavior: "smooth" });
      }
    }
  }

  // ── Smooth scroll on click ──────────────────────────────────────────
  function handleNavClick(link) {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      var targetId = link.getAttribute("data-section");
      var target = document.getElementById(targetId);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        history.replaceState(null, "", "#" + targetId);
        setActive(targetId);
      }
    });
  }

  railLinks.forEach(handleNavClick);
  tabLinks.forEach(handleNavClick);
})();
