/**
 * Section navigation highlighting for report pages (NES-41, NES-323, NES-328).
 *
 * Uses a single IntersectionObserver to track which report section is
 * currently in view.  Nav consumers (desktop rail, mobile tab bar, etc.)
 * register update callbacks via SectionNav.register().  The observer calls
 * every registered callback with the active section ID — it never needs to
 * know which surfaces exist.
 *
 * Also handles smooth-scroll-on-click with a 52 px top offset so the
 * target section clears any sticky header / tab bar.
 */
var SectionNav = (function () {
  "use strict";

  var SCROLL_OFFSET = 52; // tab bar 44 px + 8 px buffer

  // ── Registration bookkeeping ────────────────────────────────────────
  var consumers = [];      // [{ links, linkMap, activeClass, onActivate }]
  var sectionIds = {};     // union of all registered data-section values
  var sections = [];       // [{ id, el }]
  var currentActive = null;
  var observer = null;
  var booted = false;

  /**
   * Register a nav consumer.
   *
   * @param {object} opts
   * @param {string}   opts.containerSelector  — e.g. ".report-rail-nav"
   * @param {string}   opts.linkSelector       — e.g. ".rail-nav__link"
   * @param {string}   opts.activeClass        — e.g. "rail-nav__link--active"
   * @param {function} [opts.onActivate]       — optional extra work after
   *                                              the active class is applied
   *                                              (receives the active link element)
   */
  function register(opts) {
    var container = document.querySelector(opts.containerSelector);
    if (!container) return;

    var links = container.querySelectorAll(opts.linkSelector);
    if (!links.length) return;

    var linkMap = {};
    links.forEach(function (link) {
      var id = link.getAttribute("data-section");
      if (id) {
        linkMap[id] = link;
        sectionIds[id] = true;
      }
    });

    consumers.push({
      links: links,
      linkMap: linkMap,
      activeClass: opts.activeClass,
      onActivate: opts.onActivate || null
    });

    // Attach smooth-scroll click handler to every link
    links.forEach(function (link) {
      link.addEventListener("click", handleClick);
    });

    // If the observer is already running, re-scan for any new section IDs
    if (booted) boot();
  }

  // ── Observer + active-state management ──────────────────────────────
  function boot() {
    // (Re)build observed section list from the union of all registered IDs
    if (observer) {
      sections.forEach(function (s) { observer.unobserve(s.el); });
    }

    sections = [];
    Object.keys(sectionIds).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) sections.push({ id: id, el: el });
    });

    if (!sections.length) return;

    if (!observer) {
      observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            setActive(entry.target.id);
          }
        });
      }, {
        rootMargin: "-52px 0px -70% 0px",
        threshold: 0
      });
    }

    sections.forEach(function (s) { observer.observe(s.el); });
    booted = true;
  }

  function setActive(sectionId) {
    if (currentActive === sectionId) return;
    currentActive = sectionId;

    consumers.forEach(function (c) {
      // Clear all links
      c.links.forEach(function (link) {
        link.classList.remove(c.activeClass);
        link.removeAttribute("aria-current");
      });

      // Highlight the matching link
      var active = c.linkMap[sectionId];
      if (active) {
        active.classList.add(c.activeClass);
        active.setAttribute("aria-current", "true");
        if (c.onActivate) c.onActivate(active);
      }
    });
  }

  // ── Smooth scroll with offset ───────────────────────────────────────
  function handleClick(e) {
    e.preventDefault();
    var targetId = this.getAttribute("data-section");
    var target = document.getElementById(targetId);
    if (!target) return;

    var top = target.getBoundingClientRect().top + window.pageYOffset - SCROLL_OFFSET;
    window.scrollTo({ top: top, behavior: "smooth" });
    history.replaceState(null, "", "#" + targetId);
    setActive(targetId);
  }

  // ── Public API ──────────────────────────────────────────────────────
  return { register: register, boot: boot };
})();

// ── Register built-in consumers & start ─────────────────────────────────
(function () {
  "use strict";

  // Desktop rail nav
  SectionNav.register({
    containerSelector: ".report-rail-nav",
    linkSelector: ".rail-nav__link",
    activeClass: "rail-nav__link--active"
  });

  // Mobile tab bar
  SectionNav.register({
    containerSelector: ".mobile-tab-bar",
    linkSelector: ".mobile-tab__link",
    activeClass: "mobile-tab__link--active",
    onActivate: function (activeLink) {
      // Auto-scroll the tab bar to keep the active tab centred.
      // Use container.scrollTo to avoid vertical page scroll (Safari).
      var bar = activeLink.closest(".mobile-tab-bar");
      if (!bar) return;
      var linkLeft = activeLink.offsetLeft;
      var linkWidth = activeLink.offsetWidth;
      var barWidth = bar.offsetWidth;
      bar.scrollTo({
        left: linkLeft - (barWidth / 2) + (linkWidth / 2),
        behavior: "smooth"
      });
    }
  });

  SectionNav.boot();
})();
