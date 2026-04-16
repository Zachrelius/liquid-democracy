/* ==========================================================================
   Liquid Democracy — Main JavaScript
   Minimal: mobile nav, scroll animations, smooth scroll for anchor links
   ========================================================================== */

(function () {
  "use strict";

  /* -----------------------------------------------------------------------
     1. Mobile Navigation Toggle
     ----------------------------------------------------------------------- */

  var navToggle = document.getElementById("nav-toggle");
  var mainNav = document.getElementById("main-nav");

  if (navToggle && mainNav) {
    navToggle.addEventListener("click", function () {
      var expanded = navToggle.getAttribute("aria-expanded") === "true";
      navToggle.setAttribute("aria-expanded", String(!expanded));
      navToggle.setAttribute("aria-label", expanded ? "Open menu" : "Close menu");
      mainNav.classList.toggle("is-open");
      document.body.style.overflow = expanded ? "" : "hidden";
    });

    // Close nav when a link is clicked
    var navLinks = mainNav.querySelectorAll(".nav-link");
    for (var i = 0; i < navLinks.length; i++) {
      navLinks[i].addEventListener("click", function () {
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.setAttribute("aria-label", "Open menu");
        mainNav.classList.remove("is-open");
        document.body.style.overflow = "";
      });
    }

    // Close on Escape key
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && mainNav.classList.contains("is-open")) {
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.setAttribute("aria-label", "Open menu");
        mainNav.classList.remove("is-open");
        document.body.style.overflow = "";
        navToggle.focus();
      }
    });
  }

  /* -----------------------------------------------------------------------
     2. Scroll Animations (Intersection Observer)
     ----------------------------------------------------------------------- */

  // Only animate if user has no motion preference
  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  function initScrollAnimations() {
    var fadeEls = document.querySelectorAll(".fade-up");

    if (!fadeEls.length) return;

    // If reduced motion is preferred, show everything immediately
    if (prefersReducedMotion.matches) {
      for (var j = 0; j < fadeEls.length; j++) {
        fadeEls[j].classList.add("is-visible");
      }
      return;
    }

    if (!("IntersectionObserver" in window)) {
      // Fallback: show everything
      for (var k = 0; k < fadeEls.length; k++) {
        fadeEls[k].classList.add("is-visible");
      }
      return;
    }

    var observer = new IntersectionObserver(
      function (entries) {
        for (var m = 0; m < entries.length; m++) {
          if (entries[m].isIntersecting) {
            entries[m].target.classList.add("is-visible");
            observer.unobserve(entries[m].target);
          }
        }
      },
      {
        threshold: 0.2,
        rootMargin: "0px 0px -40px 0px",
      }
    );

    for (var n = 0; n < fadeEls.length; n++) {
      observer.observe(fadeEls[n]);
    }
  }

  initScrollAnimations();

  // Re-check if user changes motion preference
  prefersReducedMotion.addEventListener("change", function () {
    if (prefersReducedMotion.matches) {
      var els = document.querySelectorAll(".fade-up");
      for (var p = 0; p < els.length; p++) {
        els[p].classList.add("is-visible");
      }
    }
  });

  /* -----------------------------------------------------------------------
     3. Smooth Scroll for Anchor Links
        (Enhances native scroll-behavior: smooth with offset for fixed header)
     ----------------------------------------------------------------------- */

  var HEADER_HEIGHT = 64;

  document.addEventListener("click", function (e) {
    var link = e.target.closest("a[href^='#']");
    if (!link) return;

    var targetId = link.getAttribute("href");
    if (targetId === "#") return;

    var target = document.querySelector(targetId);
    if (!target) return;

    e.preventDefault();

    var top = target.getBoundingClientRect().top + window.pageYOffset - HEADER_HEIGHT;

    window.scrollTo({
      top: top,
      behavior: prefersReducedMotion.matches ? "auto" : "smooth",
    });

    // Set focus on target for accessibility
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  });

  /* -----------------------------------------------------------------------
     4. Stat Counter Animation (Problem Section)
        Quick count-up when stats scroll into view
     ----------------------------------------------------------------------- */

  function animateCounters() {
    if (prefersReducedMotion.matches) return;
    if (!("IntersectionObserver" in window)) return;

    var statNumbers = document.querySelectorAll(".stat-number[data-count]");
    if (!statNumbers.length) return;

    var counterObserver = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (entries[i].isIntersecting) {
            countUp(entries[i].target);
            counterObserver.unobserve(entries[i].target);
          }
        }
      },
      { threshold: 0.5 }
    );

    for (var i = 0; i < statNumbers.length; i++) {
      counterObserver.observe(statNumbers[i]);
    }
  }

  function countUp(el) {
    var endVal = parseFloat(el.getAttribute("data-count"));
    var prefix = el.getAttribute("data-prefix") || "";
    var suffix = el.getAttribute("data-suffix") || "";
    var useComma = el.getAttribute("data-format") === "comma";
    var duration = 1200; // ms
    var startTime = null;

    function formatNumber(val) {
      if (useComma) {
        return Math.round(val).toLocaleString("en-US");
      }
      // If endVal has decimals, keep one decimal
      if (endVal % 1 !== 0) {
        return val.toFixed(1);
      }
      return Math.round(val).toString();
    }

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      // Ease out quad
      var eased = 1 - (1 - progress) * (1 - progress);
      var current = eased * endVal;
      el.textContent = prefix + formatNumber(current) + suffix;
      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = prefix + formatNumber(endVal) + suffix;
      }
    }

    requestAnimationFrame(step);
  }

  animateCounters();
})();
