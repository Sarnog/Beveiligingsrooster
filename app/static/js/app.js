/* ==========================================================
   Algemene JavaScript (geen inline scripts vanwege de CSP).
   - CSRF-token meesturen met HTMX- en fetch-verzoeken
   - bevestigingsvragen bij formulieren (data-bevestig)
   - menu openklappen op de telefoon
   - live voorbeeld van dienstcode-kleuren
   - initialen-voorstel bij medewerkers
   ========================================================== */
(function () {
  "use strict";

  // CSRF-token uit de <meta>-tag
  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }
  window.csrfToken = csrfToken;

  // HTMX: stuur bij elk verzoek het CSRF-token mee als header
  document.addEventListener("htmx:configRequest", function (e) {
    e.detail.headers["X-CSRFToken"] = csrfToken();
  });

  // Bevestiging vragen bij formulieren met data-bevestig="vraag"
  document.addEventListener("submit", function (e) {
    var vraag = e.target.getAttribute("data-bevestig");
    if (vraag && !window.confirm(vraag)) {
      e.preventDefault();
    }
  }, true);

  document.addEventListener("DOMContentLoaded", function () {
    // Menu open/dicht op smalle schermen
    document.querySelectorAll("[data-wissel]").forEach(function (knop) {
      knop.addEventListener("click", function () {
        var doel = document.getElementById(knop.getAttribute("data-wissel"));
        if (doel) doel.classList.toggle("open");
      });
    });

    // Keuzelijst die naar een andere pagina gaat (bijv. weekkiezer)
    document.querySelectorAll("[data-navigeer]").forEach(function (lijst) {
      lijst.addEventListener("change", function () {
        if (lijst.value) window.location.href = lijst.value;
      });
    });

    // Kopieerknop (bijv. e-mailadres van het service-account)
    document.querySelectorAll("[data-kopieer-knop]").forEach(function (knop) {
      knop.addEventListener("click", function () {
        navigator.clipboard.writeText(knop.getAttribute("data-kopieer-knop")).then(function () {
          knop.textContent = "Gekopieerd ✓";
        });
      });
    });

    // ICS-link: in één klik alles selecteren
    document.querySelectorAll(".ics-link").forEach(function (veld) {
      veld.addEventListener("focus", function () { veld.select(); });
    });

    // Printknop
    document.querySelectorAll("[data-print]").forEach(function (knop) {
      knop.addEventListener("click", function () { window.print(); });
    });

    // Live kleurvoorbeeld in het dienstcode-formulier
    var formulier = document.querySelector("[data-kleur-voorbeeld]");
    if (formulier) {
      var voorbeeld = formulier.querySelector("[data-voorbeeld]");
      var achtergrond = formulier.querySelector("[data-voorbeeld-achtergrond]");
      var kleur = formulier.querySelector("[data-voorbeeld-kleur]");
      var tekst = formulier.querySelector("[data-voorbeeld-tekst]");
      var vet = formulier.querySelector('input[name="vet"]');
      var cursief = formulier.querySelector('input[name="cursief"]');
      var bijwerken = function () {
        voorbeeld.style.background = achtergrond.value;
        voorbeeld.style.color = kleur.value;
        voorbeeld.style.fontWeight = vet && vet.checked ? "bold" : "normal";
        voorbeeld.style.fontStyle = cursief && cursief.checked ? "italic" : "normal";
        voorbeeld.textContent = tekst.value || "Voorbeeld";
      };
      [achtergrond, kleur, tekst, vet, cursief].forEach(function (el) {
        if (el) el.addEventListener("input", bijwerken);
        if (el) el.addEventListener("change", bijwerken);
      });
      bijwerken();
    }

    // Initialen voorstellen zolang de beheerder ze niet zelf heeft aangepast
    var mwFormulier = document.querySelector("[data-initialen-url]");
    if (mwFormulier) {
      var naamVeld = mwFormulier.querySelector("[data-naam-veld]");
      var initVeld = mwFormulier.querySelector("[data-initialen-veld]");
      var zelfAangepast = initVeld.value !== "";
      initVeld.addEventListener("input", function () { zelfAangepast = initVeld.value !== ""; });
      naamVeld.addEventListener("input", function () {
        if (zelfAangepast) return;
        var url = mwFormulier.getAttribute("data-initialen-url") +
          "?naam=" + encodeURIComponent(naamVeld.value) +
          "&id=" + encodeURIComponent(mwFormulier.getAttribute("data-medewerker-id"));
        fetch(url, { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (data) { if (!zelfAangepast) initVeld.value = data.initialen; });
      });
    }
  });
})();
