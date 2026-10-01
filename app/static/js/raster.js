/* ==========================================================
   Excel-achtige bediening van het weekrooster (alleen beheerder)

   Er zijn twee rasters: het code-raster (dienstcodes per dag) en het
   visuele rooster (opmerkingen, tijden, dagopmerkingen). Elke bewerkbare
   cel heeft de klasse "cel" en deze data-attributen:
     data-r / data-c / data-cs  positie in het raster (rij, kolom, breedte)
     data-mw / data-datum        medewerker en dag
     data-veld                   welk veld (code, begin, eind, opmerking, ...)

   Bediening: pijltjes, Tab, Enter, direct typen, F2/dubbelklik, Delete,
   Esc, Shift+pijltjes (selecteren), Ctrl+C / Ctrl+V (ook vanuit Excel),
   Ctrl+Z (ongedaan maken) en Ctrl+S (opslaan).

   Wijzigingen worden NIET direct opgeslagen. Ze worden gemarkeerd en de
   server rekent een voorbeeld uit (dienstnaam, tijden, uren), zonder iets
   te bewaren. Pas bij 'Opslaan' wordt alles in één keer bewaard.
   Wie de pagina wil verlaten met niet-opgeslagen wijzigingen, krijgt eerst
   een vraag: Opslaan, Terug of Doorgaan (wijzigingen vergeten).
   ========================================================== */
(function () {
  "use strict";

  // Versie van dit script. Moet gelijk zijn aan VERSIE in app/__init__.py
  // (een test in tests/test_rooster.py controleert dat).
  var SCRIPT_VERSIE = "1.3.0";

  var houder = document.querySelector("[data-api-cellen]");
  if (!houder) return;

  // Hoort dit script bij deze pagina? Zo niet (een oude versie uit een cache), dan
  // niets laten bewerken en melden dat de pagina opnieuw geladen moet worden.
  if (houder.getAttribute("data-versie") !== SCRIPT_VERSIE) {
    var melding = document.querySelector("[data-status]");
    if (melding) {
      melding.textContent = "Verouderde versie geladen. Ververs de pagina (Ctrl+F5) voordat je iets wijzigt.";
      melding.className = "raster-status fout";
    }
    document.querySelectorAll("[data-opslaan]").forEach(function (k) { k.disabled = true; });
    return;
  }
  var API_CELLEN = houder.getAttribute("data-api-cellen");
  var statusVak = document.querySelector("[data-status]");

  // ---------- Raster: posities van cellen ----------

  function Raster(tabel) {
    this.tabel = tabel;
    this.matrix = {};   // matrix[r][c] = cel
    this.rijen = [];    // gesorteerde rijnummers
    var zelf = this;
    tabel.querySelectorAll(".cel").forEach(function (cel) {
      cel.setAttribute("tabindex", "-1");
      cel._raster = zelf;
      var r = parseInt(cel.getAttribute("data-r"), 10);
      zelf.maxC = Math.max(zelf.maxC || 0, parseInt(cel.getAttribute("data-c"), 10) + parseInt(cel.getAttribute("data-cs") || "1", 10) - 1);
      var c = parseInt(cel.getAttribute("data-c"), 10);
      var cs = parseInt(cel.getAttribute("data-cs") || "1", 10);
      cel._r = r; cel._c = c; cel._cs = cs;
      if (!zelf.matrix[r]) { zelf.matrix[r] = {}; zelf.rijen.push(r); }
      for (var k = 0; k < cs; k++) zelf.matrix[r][c + k] = cel;
    });
    this.rijen.sort(function (a, b) { return a - b; });
  }

  Raster.prototype.op = function (r, c) {
    return this.matrix[r] ? this.matrix[r][c] : undefined;
  };

  // Eén stap in een richting; blijft staan aan de rand van het raster
  Raster.prototype.stap = function (cel, dr, dc) {
    if (dc !== 0) {
      for (var c = dc > 0 ? cel._c + cel._cs : cel._c - 1; c >= 0 && c <= this.maxC; c += dc) {
        var kandidaat = this.op(cel._r, c);
        if (kandidaat && kandidaat !== cel) return kandidaat;
      }
      return cel;
    }
    var index = this.rijen.indexOf(cel._r) + dr;
    if (index < 0 || index >= this.rijen.length) return cel;
    var rij = this.rijen[index];
    // Zoek in de nieuwe rij de cel op dezelfde kolom (of de dichtstbijzijnde links)
    for (var k = cel._c; k >= 0; k--) {
      var doel = this.op(rij, k);
      if (doel) return doel;
    }
    return cel;
  };

  // Alle cellen in de rechthoek tussen twee cellen, per rij gegroepeerd
  Raster.prototype.rechthoek = function (a, b) {
    var r1 = Math.min(a._r, b._r), r2 = Math.max(a._r, b._r);
    var c1 = Math.min(a._c, b._c), c2 = Math.max(a._c + a._cs - 1, b._c + b._cs - 1);
    var resultaat = [];
    var zelf = this;
    this.rijen.forEach(function (r) {
      if (r < r1 || r > r2) return;
      var rij = [];
      for (var c = c1; c <= c2; c++) {
        var cel = zelf.op(r, c);
        if (cel && rij.indexOf(cel) === -1) rij.push(cel);
      }
      if (rij.length) resultaat.push(rij);
    });
    return resultaat;
  };

  var rasters = [];
  document.querySelectorAll("[data-raster]").forEach(function (tabel) {
    rasters.push(new Raster(tabel));
  });

  // ---------- Toestand ----------

  var actief = null;        // de actieve cel
  var anker = null;         // begin van een selectie (Shift)
  var invoer = null;        // <input> tijdens het bewerken
  var invoerModus = "";     // "typen" (pijltjes = verplaatsen) of "f2" (pijltjes in de tekst)
  var ongedaan = [];        // stapel voor Ctrl+Z
  var MAX_ONGEDAAN = 50;

  function selectie() {
    if (!actief) return [];
    return actief._raster.rechthoek(anker || actief, actief);
  }

  function toonSelectie() {
    document.querySelectorAll(".cel.geselecteerd, .cel.actief").forEach(function (c) {
      c.classList.remove("geselecteerd", "actief");
    });
    if (!actief) return;
    selectie().forEach(function (rij) {
      rij.forEach(function (c) { c.classList.add("geselecteerd"); });
    });
    actief.classList.add("actief");
  }

  function kies(cel, uitbreiden) {
    if (!cel) return;
    if (uitbreiden && actief && actief._raster === cel._raster) {
      if (!anker) anker = actief;
    } else {
      anker = null;
    }
    actief = cel;
    cel.focus({ preventScroll: true });
    cel.scrollIntoView({ block: "nearest", inline: "nearest" });
    toonSelectie();
  }

  // ---------- Status ----------

  var statusTimer = null;
  function status(tekst, soort) {
    if (!statusVak) return;
    statusVak.textContent = tekst;
    statusVak.className = "raster-status " + (soort || "");
    clearTimeout(statusTimer);
    if (soort === "ok") {
      statusTimer = setTimeout(function () { statusVak.className = "raster-status"; }, 2500);
    }
  }

  // ---------- Bewerken ----------

  function startBewerken(cel, beginTekst, modus) {
    if (invoer) stopBewerken(true);
    kies(cel, false);
    invoer = document.createElement("input");
    invoer.type = "text";
    invoer.className = "cel-invoer";
    invoer.value = beginTekst !== null ? beginTekst : cel.textContent.trim();
    invoer.setAttribute("aria-label", "Cel bewerken");
    invoerModus = modus;
    cel.classList.add("bewerken");
    cel.appendChild(invoer);
    invoer.focus();
    var lengte = invoer.value.length;
    invoer.setSelectionRange(lengte, lengte);
    invoer.addEventListener("keydown", invoerToets);
    invoer.addEventListener("blur", function () { if (invoer) stopBewerken(true); });
  }

  function stopBewerken(opslaan) {
    if (!invoer) return;
    var veld = invoer;
    invoer = null;  // eerst loskoppelen: remove() veroorzaakt een blur-event
    var cel = veld.parentNode;
    var waarde = veld.value.trim();
    veld.remove();
    cel.classList.remove("bewerken");
    if (opslaan && waarde !== cel.textContent.trim()) {
      bewaar([{ cel: cel, waarde: waarde }]);
    }
    cel.focus({ preventScroll: true });
  }

  function invoerToets(e) {
    var cel = invoer.parentNode;
    var raster = cel._raster;
    // Deze toets is voor het invoerveld; niet ook nog door het raster laten verwerken
    e.stopPropagation();
    if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
      e.preventDefault();
      stopBewerken(true);
      opslaan();
    } else if (e.key === "Enter") {
      e.preventDefault();
      stopBewerken(true);
      kies(raster.stap(cel, e.shiftKey ? -1 : 1, 0));
    } else if (e.key === "Tab") {
      e.preventDefault();
      stopBewerken(true);
      kies(raster.stap(cel, 0, e.shiftKey ? -1 : 1));
    } else if (e.key === "Escape") {
      e.preventDefault();
      stopBewerken(false);
    } else if (invoerModus === "typen" && e.key.indexOf("Arrow") === 0) {
      e.preventDefault();
      stopBewerken(true);
      beweeg(cel, e.key, false);
    }
  }

  function beweeg(cel, toets, uitbreiden) {
    var richting = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[toets];
    kies(cel._raster.stap(cel, richting[0], richting[1]), uitbreiden);
  }

  // ---------- Wijzigingen bijhouden (pas bewaren bij 'Opslaan') ----------

  var wachtend = [];        // niet-opgeslagen wijzigingen: [{sleutel, dag, mw, datum, veld, waarde}]
  var getoond = {};         // "mw|datum" die ooit gewijzigd zijn (om na Ctrl+Z te kunnen herstellen)
  var getoondeDagen = {};   // idem voor dagopmerkingen
  var vrijgegeven = false;  // true = de pagina mag zonder vraag verlaten worden
  var opslaanKnoppen = document.querySelectorAll("[data-opslaan]");

  function heeftWijzigingen() {
    return wachtend.length > 0;
  }

  function post(gegevens) {
    return fetch(API_CELLEN, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": window.csrfToken() },
      body: JSON.stringify(gegevens)
    });
  }

  function versieVan(mw, datum) {
    var naam = document.querySelector('[data-toon="dienstnaam"][data-mw="' + mw + '"][data-datum="' + datum + '"]');
    return naam ? parseInt(naam.getAttribute("data-versie") || "0", 10) : 0;
  }

  // Registreer wijzigingen (typen, plakken, wissen). items: [{cel, waarde}]
  function bewaar(items) {
    if (!items.length) return;
    ongedaan.push(wachtend.slice());  // stand van vóór deze actie, voor Ctrl+Z
    if (ongedaan.length > MAX_ONGEDAAN) ongedaan.shift();
    items.forEach(function (i) {
      var veld = i.cel.getAttribute("data-veld");
      var mw = i.cel.getAttribute("data-mw");
      var datum = i.cel.getAttribute("data-datum");
      var dag = veld === "dagopmerking";
      var sleutel = dag ? "dag|" + datum : mw + "|" + datum + "|" + veld;
      // Zelfde cel opnieuw gewijzigd: alleen de laatste waarde telt
      wachtend = wachtend.filter(function (w) { return w.sleutel !== sleutel; });
      wachtend.push({ sleutel: sleutel, dag: dag, mw: mw, datum: datum, veld: veld, waarde: i.waarde });
      if (dag) { getoondeDagen[datum] = true; } else { getoond[mw + "|" + datum] = true; }
      i.cel.textContent = i.waarde;  // direct tonen wat er getypt is
      i.cel.classList.remove("fout");
    });
    if (statusVak) statusVak.className = "raster-status";  // oude foutmelding weghalen
    voorbeeld();
  }

  // Het verzoek aan de server: alle wachtende wijzigingen, met de versies van de laatste opslag
  function verzoek(opslaan) {
    var gezien = {};
    var cellen = [];
    var dagen = [];
    wachtend.forEach(function (w) {
      if (w.dag) {
        dagen.push({ datum: w.datum, tekst: w.waarde });
        return;
      }
      var k = w.mw + "|" + w.datum;
      cellen.push({ mw: w.mw, datum: w.datum, veld: w.veld, waarde: w.waarde,
                    versie: gezien[k] ? null : versieVan(w.mw, w.datum) });
      gezien[k] = true;
    });
    return { opslaan: opslaan, wijzigingen: cellen, dagopmerkingen: dagen,
             ook_tonen: Object.keys(getoond), ook_dagen: Object.keys(getoondeDagen) };
  }

  // Alle verzoeken aan de server gaan strikt na elkaar (voorbeeld, opslaan, voorbeeld, ...).
  // Zo kunnen een voorbeeld en het opslaan elkaar nooit kruisen.
  var wachtrij = Promise.resolve();
  function inWachtrij(taak) {
    wachtrij = wachtrij.then(taak, taak);
    return wachtrij;
  }

  function leesAntwoord(r) {
    if (r.status === 409) throw new Error("conflict");
    if (r.status === 401) throw new Error("uitgelogd");
    if (!r.ok) throw new Error("fout");
    return r.json();
  }

  // Voorbeeld opvragen (niets wordt bewaard). Staat er al een voorbeeld klaar in de
  // wachtrij, dan niet nog een: dat voorbeeld gebruikt straks vanzelf de nieuwste stand.
  var voorbeeldGepland = false;
  var ronde = 0;  // verhoogd bij elke opslag: een ouder voorbeeld wordt dan genegeerd
  function voorbeeld() {
    toonTeller();
    if (voorbeeldGepland) return;
    voorbeeldGepland = true;
    inWachtrij(function () {
      voorbeeldGepland = false;
      var mijnRonde = ronde;
      return post(verzoek(false))
        .then(leesAntwoord)
        .then(function (antwoord) {
          // Intussen opgeslagen of opnieuw gewijzigd? Dan is dit voorbeeld verouderd.
          if (!voorbeeldGepland && mijnRonde === ronde) verwerkAntwoord(antwoord, false);
        })
        .catch(function (fout) {
          if (mijnRonde !== ronde) return;  // verouderd: niet melden
          var meldingen = {
            uitgelogd: "Je bent uitgelogd. Log opnieuw in (je wijzigingen zijn niet opgeslagen).",
            conflict: "Iemand anders wijzigde tegelijk dezelfde dienst. Ververs de pagina."
          };
          status(meldingen[fout.message] || "Geen verbinding met de server.", "fout");
        });
    });
  }

  // Definitief opslaan. 'daarna' wordt uitgevoerd als alles goed is opgeslagen.
  var opslaanBezig = false;
  function opslaan(daarna) {
    if (invoer) stopBewerken(true);
    if (!heeftWijzigingen()) { if (daarna) daarna(); return; }
    if (opslaanBezig) return;
    opslaanBezig = true;
    ronde++;
    status("Opslaan…", "bezig");
    opslaanKnoppen.forEach(function (k) { k.disabled = true; });
    inWachtrij(function () {
      // Pas nu (na een eventueel lopend voorbeeld) bepalen wat er verstuurd wordt
      var verstuurd = wachtend.slice();
      return post(verzoek(true))
        .then(leesAntwoord)
        .then(function (antwoord) {
          // Alleen wat verstuurd is, is opgeslagen; nieuwere wijzigingen blijven wachten
          wachtend = wachtend.filter(function (w) { return verstuurd.indexOf(w) === -1; });
          ongedaan = [];
          verwerkAntwoord(antwoord, true);
          if (!wachtend.length) { getoond = {}; getoondeDagen = {}; } else { voorbeeld(); }
          if (antwoord.fouten.length) {
            status(antwoord.fouten[0].melding, "fout");
          } else {
            status("Opgeslagen ✓", "ok");
            if (daarna) daarna();
          }
        })
        .catch(function (fout) {
          var meldingen = {
            conflict: "Iemand anders wijzigde tegelijk dezelfde dienst. Niets opgeslagen; ververs de pagina.",
            uitgelogd: "Je bent uitgelogd. Log opnieuw in; je wijzigingen zijn niet opgeslagen."
          };
          status(meldingen[fout.message] || "Opslaan mislukt. Controleer de verbinding en probeer opnieuw.", "fout");
        })
        .then(function () {
          opslaanBezig = false;
          toonTeller();
        });
    });
  }

  // Antwoord van de server tonen (voorbeeld of opgeslagen)
  function verwerkAntwoord(antwoord, opgeslagen) {
    Object.keys(antwoord.bijgewerkt).forEach(function (k) {
      var delen = k.split("|");
      werkBij(delen[0], delen[1], antwoord.bijgewerkt[k], opgeslagen);
    });
    Object.keys(antwoord.dagopmerkingen || {}).forEach(function (datum) {
      var g = antwoord.dagopmerkingen[datum];
      var cel = document.querySelector('.dagopm[data-datum="' + datum + '"]');
      if (!cel) return;
      cel.textContent = g.tekst;
      cel.classList.toggle("gevuld", !!g.tekst);
      cel.title = g.handmatig ? "Handmatig aangepast" : "";
    });
    // Ongeldige invoer: rood tonen en niet meenemen bij het opslaan
    antwoord.fouten.forEach(function (f) {
      var cel = document.querySelector('.cel[data-mw="' + f.mw + '"][data-datum="' + f.datum + '"][data-veld="' + f.veld + '"]');
      var sleutel = f.mw + "|" + f.datum + "|" + f.veld;
      var poging = wachtend.filter(function (w) { return w.sleutel === sleutel; })[0];
      if (!f.conflict) wachtend = wachtend.filter(function (w) { return w.sleutel !== sleutel; });
      if (!cel) return;
      cel.classList.add("fout");
      cel.title = f.melding;
      if (poging && !f.conflict) cel.textContent = poging.waarde;
    });
    if (antwoord.fouten.length && !opgeslagen) status(antwoord.fouten[0].melding, "fout");
    markeerGewijzigd();
    toonTeller();
  }

  function markeerGewijzigd() {
    document.querySelectorAll(".cel.gewijzigd").forEach(function (c) { c.classList.remove("gewijzigd"); });
    wachtend.forEach(function (w) {
      var selector = w.dag ? '.dagopm[data-datum="' + w.datum + '"]'
        : '.cel[data-mw="' + w.mw + '"][data-datum="' + w.datum + '"][data-veld="' + w.veld + '"]';
      var cel = document.querySelector(selector);
      if (cel) cel.classList.add("gewijzigd");
    });
  }

  function toonTeller() {
    var aantal = wachtend.length;
    opslaanKnoppen.forEach(function (k) {
      k.disabled = aantal === 0 || opslaanBezig;
      k.textContent = aantal ? "Opslaan (" + aantal + ")" : "Opslaan";
    });
    if (aantal && !opslaanBezig && statusVak && statusVak.className.indexOf("fout") === -1) {
      status(aantal === 1 ? "1 wijziging nog niet opgeslagen" : aantal + " wijzigingen nog niet opgeslagen", "wacht");
    }
  }

  function ongedaanMaken() {
    if (!ongedaan.length) return;
    wachtend = ongedaan.pop();
    status("Ongedaan gemaakt", "ok");
    voorbeeld();
  }

  // Alle cellen van één medewerker/dag bijwerken met de gegevens van de server
  function werkBij(mw, datum, g, opgeslagen) {
    var selector = '[data-mw="' + mw + '"][data-datum="' + datum + '"]';
    document.querySelectorAll(selector).forEach(function (el) {
      var veld = el.getAttribute("data-veld");
      var toon = el.getAttribute("data-toon");
      if (veld === "code") {
        el.textContent = g.code;
        el.setAttribute("style", g.dienst_stijl);
      } else if (veld === "begin" || veld === "eind") {
        el.textContent = g[veld];
        el.classList.toggle("handmatig", g.handmatig);
      } else if (veld === "opmerking") {
        el.textContent = g.opmerking;
        el.setAttribute("style", g.opmerking_stijl);
      } else if (veld === "opm_begin" || veld === "opm_eind") {
        el.textContent = g[veld];
      } else if (toon === "dienstnaam") {
        el.textContent = g.dienstnaam;
        el.setAttribute("style", g.dienst_stijl);
        // De versie alleen overnemen na echt opslaan (een voorbeeld is niet bewaard)
        if (opgeslagen) el.setAttribute("data-versie", g.versie);
      } else if (toon === "uren") {
        el.textContent = g.uren;
        el.classList.toggle("handmatig", !!g.uren_handmatig);
      }
      if (veld) { el.classList.remove("fout"); el.removeAttribute("title"); }
      if (veld === "begin" || veld === "eind") el.title = g.handmatig ? "Handmatig aangepast" : "";
      if (veld === "uren" && g.uren_handmatig) el.title = "Zelf ingevulde uren";
    });
    var totaal = document.querySelector('[data-totaal="' + mw + '"]');
    if (totaal) totaal.textContent = g.weektotaal;
  }

  // ---------- Opslaan-knoppen en waarschuwing bij verlaten ----------

  opslaanKnoppen.forEach(function (knop) {
    knop.addEventListener("click", function () { opslaan(); });
  });

  var dialoog = document.getElementById("niet-opgeslagen");
  var vervolg = null;

  // Vraag eerst wat er moet gebeuren als er niet-opgeslagen wijzigingen zijn
  function vraagEerst(actie) {
    if (invoer) stopBewerken(true);
    if (!heeftWijzigingen() || vrijgegeven || !dialoog) { actie(); return; }
    vervolg = actie;
    dialoog.showModal();
  }

  if (dialoog) {
    dialoog.addEventListener("click", function (e) {
      var keuze = e.target.getAttribute && e.target.getAttribute("data-keuze");
      if (!keuze) return;
      dialoog.close();
      if (keuze === "doorgaan") {
        vrijgegeven = true;  // wijzigingen vergeten
        if (vervolg) vervolg();
      } else if (keuze === "opslaan") {
        opslaan(function () { vrijgegeven = true; if (vervolg) vervolg(); });
      }
      // 'terug': niets doen, verder wijzigen
    });
  }

  // Links (menu, weeknavigatie, kalender, ...)
  document.addEventListener("click", function (e) {
    if (!heeftWijzigingen() || vrijgegeven || e.defaultPrevented) return;
    var link = e.target.closest ? e.target.closest("a[href]") : null;
    if (!link || link.target === "_blank" || link.getAttribute("href").charAt(0) === "#") return;
    e.preventDefault();
    e.stopPropagation();
    vraagEerst(function () { window.location.href = link.href; });
  }, true);

  // Formulieren (uitloggen, week kopiëren, ...)
  document.addEventListener("submit", function (e) {
    if (!heeftWijzigingen() || vrijgegeven || e.defaultPrevented) return;
    var formulier = e.target;
    if (dialoog && dialoog.contains(formulier)) return;
    e.preventDefault();
    e.stopPropagation();
    vraagEerst(function () { HTMLFormElement.prototype.submit.call(formulier); });
  }, true);

  // Keuzelijsten die naar een andere pagina gaan (weekkiezer)
  document.addEventListener("change", function (e) {
    var lijst = e.target;
    if (!lijst.hasAttribute || !lijst.hasAttribute("data-navigeer")) return;
    if (!heeftWijzigingen() || vrijgegeven) return;
    e.stopImmediatePropagation();
    var doel = lijst.value;
    // Keuze terugzetten tot er een besluit is
    Array.prototype.forEach.call(lijst.options, function (o) { o.selected = o.defaultSelected; });
    vraagEerst(function () { if (doel) window.location.href = doel; });
  }, true);

  // Browser of tabblad sluiten, verversen, terug-knop: de browser toont zijn eigen vraag
  window.addEventListener("beforeunload", function (e) {
    if (heeftWijzigingen() && !vrijgegeven) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // ---------- Muis ----------

  document.addEventListener("mousedown", function (e) {
    var cel = e.target.closest ? e.target.closest(".cel") : null;
    if (e.target === invoer) return;
    if (!cel) {
      if (invoer) stopBewerken(true);
      if (!e.target.closest("[data-raster]")) { actief = null; anker = null; toonSelectie(); }
      return;
    }
    if (invoer) stopBewerken(true);
    e.preventDefault();
    kies(cel, e.shiftKey);
  });

  document.addEventListener("dblclick", function (e) {
    var cel = e.target.closest ? e.target.closest(".cel") : null;
    if (cel && !invoer) startBewerken(cel, null, "f2");
  });

  // ---------- Toetsenbord ----------

  document.addEventListener("keydown", function (e) {
    // Ctrl+S: opslaan (ook als er geen cel geselecteerd is)
    if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
      e.preventDefault();
      opslaan();
      return;
    }
    if (!actief || invoer) return;
    var focus = document.activeElement;
    if (focus && focus !== actief && focus !== document.body && !focus.classList.contains("cel")) return;

    var ctrl = e.ctrlKey || e.metaKey;
    if (e.key.indexOf("Arrow") === 0) {
      e.preventDefault();
      beweeg(actief, e.key, e.shiftKey);
    } else if (e.key === "Tab") {
      e.preventDefault();
      kies(actief._raster.stap(actief, 0, e.shiftKey ? -1 : 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      kies(actief._raster.stap(actief, e.shiftKey ? -1 : 1, 0));
    } else if (e.key === "F2") {
      e.preventDefault();
      startBewerken(actief, null, "f2");
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      var items = [];
      selectie().forEach(function (rij) {
        rij.forEach(function (c) { if (c.textContent.trim() !== "") items.push({ cel: c, waarde: "" }); });
      });
      bewaar(items);
    } else if (ctrl && (e.key === "z" || e.key === "Z")) {
      e.preventDefault();
      ongedaanMaken();
    } else if (e.key === "Escape") {
      anker = null;
      toonSelectie();
    } else if (!ctrl && !e.altKey && e.key.length === 1) {
      // Direct typen: cel overschrijven
      e.preventDefault();
      startBewerken(actief, e.key, "typen");
    }
  });

  // ---------- Kopiëren en plakken ----------

  document.addEventListener("copy", function (e) {
    if (!actief || invoer) return;
    var tekst = selectie().map(function (rij) {
      return rij.map(function (c) { return c.textContent.trim(); }).join("\t");
    }).join("\n");
    e.clipboardData.setData("text/plain", tekst);
    e.preventDefault();
    status("Gekopieerd", "ok");
  });

  document.addEventListener("paste", function (e) {
    if (!actief || invoer) return;
    var tekst = (e.clipboardData || window.clipboardData).getData("text/plain");
    if (!tekst) return;
    e.preventDefault();
    var regels = tekst.replace(/\r/g, "").split("\n");
    if (regels.length > 1 && regels[regels.length - 1] === "") regels.pop();
    var items = [];

    // Eén waarde en meerdere cellen geselecteerd: alle geselecteerde cellen vullen (zoals Excel)
    if (regels.length === 1 && regels[0].indexOf("\t") === -1 && anker) {
      selectie().forEach(function (rij) { rij.forEach(function (c) { items.push({ cel: c, waarde: regels[0].trim() }); }); });
    } else {
      var rijStart = actief;
      for (var i = 0; i < regels.length; i++) {
        if (i > 0) {
          var volgende = rijStart._raster.stap(rijStart, 1, 0);
          if (volgende === rijStart) break;  // onderkant van het raster bereikt
          rijStart = volgende;
        }
        var cel = rijStart;
        var waarden = regels[i].split("\t");
        for (var j = 0; j < waarden.length; j++) {
          if (j > 0) {
            var rechts = cel._raster.stap(cel, 0, 1);
            if (rechts === cel) break;  // rechterkant bereikt
            cel = rechts;
          }
          items.push({ cel: cel, waarde: waarden[j].trim() });
        }
      }
    }
    bewaar(items.filter(function (i) { return i.waarde !== i.cel.textContent.trim(); }));
  });
})();
