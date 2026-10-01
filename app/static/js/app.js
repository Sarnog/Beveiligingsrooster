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

  // Bevestiging vragen bij formulieren met data-bevestig="vraag"
  document.addEventListener("submit", function (e) {
    var vraag = e.target.getAttribute("data-bevestig");
    if (vraag && !window.confirm(vraag)) {
      e.preventDefault();
    }
  }, true);

  // Formulieren met data-bezig: knop uitschakelen en "Bezig…" tonen tijdens het wachten
  // (voorkomt dat een dubbele klik iets twee keer doet, bijv. twee agenda's aanmaken)
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented || !e.target.hasAttribute("data-bezig")) return;
    var knop = e.target.querySelector('button[type="submit"]');
    if (knop) {
      setTimeout(function () { knop.disabled = true; }, 0);  // na het versturen
      knop.textContent = "Bezig…";
    }
  });

  // localStorage kan ontbreken of geblokkeerd zijn (privévenster): dan gewoon niets onthouden
  function leesVoorkeur(sleutel) {
    try { return window.localStorage.getItem(sleutel); } catch (e) { return null; }
  }
  function bewaarVoorkeur(sleutel, waarde) {
    try { window.localStorage.setItem(sleutel, waarde); } catch (e) { /* niet onthouden */ }
  }

  // ---------- Weekrooster op de telefoon ----------
  // Raster (Excel-achtig) of telefoonweergave: standaard volgens de schermbreedte,
  // met de knop 'Telefoonweergave' zelf te kiezen (onthouden per gebruiker).
  // In de telefoonweergave: per dag of per medewerker, met knoppen of vegen.
  function weekMobiel() {
    var mobiel = document.querySelector("[data-week-mobiel]");
    if (!mobiel) return;
    var html = document.documentElement;
    var gebruiker = mobiel.getAttribute("data-gebruiker");
    var sleutelWeergave = "rooster.weergave." + gebruiker;
    var sleutelModus = "rooster.mobielmodus." + gebruiker;
    var smal = window.matchMedia("(max-width: 760px)");
    var wissel = document.querySelector("[data-weergave-wissel]");

    function isMobiel() {
      if (html.classList.contains("weergave-mobiel")) return true;
      if (html.classList.contains("weergave-raster")) return false;
      return smal.matches;
    }
    function zetWeergave(weergave) {
      html.classList.toggle("weergave-mobiel", weergave === "mobiel");
      html.classList.toggle("weergave-raster", weergave === "raster");
      if (wissel) {
        var mob = isMobiel();
        wissel.textContent = mob ? "Rasterweergave" : "Telefoonweergave";
        wissel.setAttribute("aria-pressed", mob ? "true" : "false");
      }
    }
    zetWeergave(leesVoorkeur(sleutelWeergave));
    if (wissel) {
      wissel.addEventListener("click", function () {
        var nieuw = isMobiel() ? "raster" : "mobiel";
        bewaarVoorkeur(sleutelWeergave, nieuw);
        zetWeergave(nieuw);
      });
    }
    smal.addEventListener("change", function () { zetWeergave(leesVoorkeur(sleutelWeergave)); });

    // Panelen 'dag' en 'medewerker', elk met eigen pagina's
    var panelen = {};
    mobiel.querySelectorAll("[data-mobiel-paneel]").forEach(function (paneel) {
      var naam = paneel.getAttribute("data-mobiel-paneel");
      var paginas = paneel.querySelectorAll(".mobiel-pagina");
      var kies = paneel.querySelector("[data-mobiel-kies]");
      var p = { paneel: paneel, paginas: paginas, kies: kies, index: 0 };
      p.toon = function (index) {
        if (!paginas.length) return;
        p.index = Math.max(0, Math.min(paginas.length - 1, index));
        paginas.forEach(function (pagina, i) { pagina.hidden = i !== p.index; });
        if (kies) kies.value = String(p.index);
      };
      p.stap = function (richting) {
        var doel = p.index + richting;
        // Voorbij maandag of zondag: naar de vorige of volgende week (dagweergave)
        if (naam === "dag" && (doel < 0 || doel >= paginas.length)) {
          var url = mobiel.getAttribute(doel < 0 ? "data-vorige-week" : "data-volgende-week");
          if (url) window.location.href = url;
          return;
        }
        p.toon(doel);
      };
      paneel.querySelector("[data-mobiel-vorige]").addEventListener("click", function () { p.stap(-1); });
      paneel.querySelector("[data-mobiel-volgende]").addEventListener("click", function () { p.stap(1); });
      if (kies) kies.addEventListener("change", function () { p.toon(parseInt(kies.value, 10)); });
      panelen[naam] = p;
    });
    panelen.dag.toon(parseInt(mobiel.getAttribute("data-start-dag") || "0", 10));
    panelen.medewerker.toon(panelen.medewerker.kies ? panelen.medewerker.kies.selectedIndex : 0);

    var modus = leesVoorkeur(sleutelModus) === "medewerker" ? "medewerker" : "dag";
    function zetModus(nieuw) {
      modus = nieuw;
      Object.keys(panelen).forEach(function (naam) { panelen[naam].paneel.hidden = naam !== modus; });
      mobiel.querySelectorAll("[data-mobiel-modus]").forEach(function (knop) {
        knop.setAttribute("aria-pressed", knop.getAttribute("data-mobiel-modus") === modus ? "true" : "false");
      });
    }
    zetModus(modus);
    mobiel.querySelectorAll("[data-mobiel-modus]").forEach(function (knop) {
      knop.addEventListener("click", function () {
        zetModus(knop.getAttribute("data-mobiel-modus"));
        bewaarVoorkeur(sleutelModus, modus);
      });
    });

    // Vegen: naar links = volgende, naar rechts = vorige (alleen een duidelijk horizontale beweging)
    var start = null;
    mobiel.addEventListener("touchstart", function (e) {
      start = e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
    }, { passive: true });
    mobiel.addEventListener("touchend", function (e) {
      if (!start || !e.changedTouches.length) return;
      var dx = e.changedTouches[0].clientX - start.x;
      var dy = e.changedTouches[0].clientY - start.y;
      start = null;
      if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) panelen[modus].stap(dx < 0 ? 1 : -1);
    }, { passive: true });
  }

  // Service worker (installeerbaar als app; werkt alleen via HTTPS of op localhost).
  // Cachet alleen statische bestanden met versienummer, nooit pagina's of de API.
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* geen app-functies */ });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Menu open/dicht op smalle schermen (hamburger). Werkt ook met het toetsenbord:
    // openen zet de focus op het eerste menu-item, Escape sluit en zet de focus terug.
    document.querySelectorAll("[data-menu]").forEach(function (knop) {
      var menu = document.getElementById(knop.getAttribute("data-menu"));
      if (!menu) return;
      function zet(open, focus) {
        menu.classList.toggle("open", open);
        knop.setAttribute("aria-expanded", open ? "true" : "false");
        if (open && focus) {
          var eerste = menu.querySelector("a, button");
          if (eerste) eerste.focus();
        } else if (!open && focus) {
          knop.focus();
        }
      }
      knop.addEventListener("click", function (e) {
        // detail === 0: geactiveerd met het toetsenbord (Enter/spatie)
        zet(!menu.classList.contains("open"), e.detail === 0);
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && menu.classList.contains("open")) zet(false, true);
      });
    });

    weekMobiel();

    // Tabellen die breder zijn dan het scherm: hint tonen boven de scrollbare tabel
    function schuifHints() {
      document.querySelectorAll(".tabel-schuif").forEach(function (houder) {
        var hint = houder.previousElementSibling;
        if (!hint || !hint.classList.contains("schuif-hint")) {
          hint = document.createElement("p");
          hint.className = "schuif-hint";
          hint.textContent = "↔ Veeg opzij om de hele tabel te zien";
          houder.parentNode.insertBefore(hint, houder);
        }
        hint.hidden = houder.scrollWidth <= houder.clientWidth + 1;
      });
    }
    schuifHints();
    window.addEventListener("resize", schuifHints);

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
