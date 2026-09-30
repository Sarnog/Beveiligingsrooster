/* ==========================================================
   Excel-achtige bediening van het weekrooster (alleen beheerder)

   Er zijn twee rasters: het code-raster (dienstcodes per dag) en het
   visuele rooster (opmerkingen, tijden, dagopmerkingen). Elke bewerkbare
   cel heeft de klasse "cel" en deze data-attributen:
     data-r / data-c / data-cs  positie in het raster (rij, kolom, breedte)
     data-mw / data-datum        medewerker en dag
     data-veld                   welk veld (code, begin, eind, opmerking, ...)

   Bediening: pijltjes, Tab, Enter, direct typen, F2/dubbelklik, Delete,
   Esc, Shift+pijltjes (selecteren), Ctrl+C / Ctrl+V (ook vanuit Excel)
   en Ctrl+Z (ongedaan maken). Elke wijziging wordt direct opgeslagen.
   ========================================================== */
(function () {
  "use strict";

  var houder = document.querySelector("[data-api-cellen]");
  if (!houder) return;
  var API_CELLEN = houder.getAttribute("data-api-cellen");
  var API_DAG = houder.getAttribute("data-api-dag");
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
    if (e.key === "Enter") {
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

  // ---------- Opslaan ----------

  function sleutel(cel) {
    return cel.getAttribute("data-mw") + "|" + cel.getAttribute("data-datum");
  }

  function versieVan(mw, datum) {
    var naam = document.querySelector('[data-toon="dienstnaam"][data-mw="' + mw + '"][data-datum="' + datum + '"]');
    return naam ? parseInt(naam.getAttribute("data-versie") || "0", 10) : 0;
  }

  // Alle verzoeken gaan na elkaar (in volgorde), zodat snelle wijzigingen
  // aan dezelfde dag elkaar niet inhalen en de versies kloppen.
  var wachtrij = Promise.resolve();
  function inWachtrij(taak) {
    wachtrij = wachtrij.then(taak, taak);
    return wachtrij;
  }

  function post(url, gegevens) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": window.csrfToken() },
      body: JSON.stringify(gegevens)
    });
  }

  // items: [{cel, waarde}]; zonderOngedaan = true bij Ctrl+Z zelf
  function bewaar(items, zonderOngedaan) {
    if (!items.length) return;
    if (!zonderOngedaan) {
      ongedaan.push(items.map(function (i) { return { cel: i.cel, waarde: i.cel.textContent.trim() }; }));
      if (ongedaan.length > MAX_ONGEDAAN) ongedaan.shift();
    }
    var dagItems = items.filter(function (i) { return i.cel.getAttribute("data-veld") === "dagopmerking"; });
    var celItems = items.filter(function (i) { return i.cel.getAttribute("data-veld") !== "dagopmerking"; });

    // Direct tonen wat er getypt is (wordt daarna vervangen door het antwoord van de server)
    items.forEach(function (i) { i.cel.textContent = i.waarde; i.cel.classList.add("bezig"); i.cel.classList.remove("fout"); });
    status("Opslaan…", "bezig");

    dagItems.forEach(function (i) {
      inWachtrij(function () { return post(API_DAG, { datum: i.cel.getAttribute("data-datum"), tekst: i.waarde })
        .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
        .then(function (g) {
          i.cel.textContent = g.tekst;
          i.cel.classList.toggle("gevuld", !!g.tekst);
          i.cel.title = g.handmatig ? "Handmatig aangepast" : "";
          i.cel.classList.remove("bezig");
          status("Opgeslagen ✓", "ok");
        })
        .catch(function () { i.cel.classList.remove("bezig"); status("Opslaan mislukt. Probeer het opnieuw.", "fout"); }); });
    });

    if (!celItems.length) return;
    inWachtrij(function () { return verstuurCellen(celItems); });
  }

  function verstuurCellen(celItems) {
    // De versies worden pas NU gelezen, na het vorige antwoord uit de wachtrij
    var gezien = {};
    var wijzigingen = celItems.map(function (i) {
      var mw = i.cel.getAttribute("data-mw"), datum = i.cel.getAttribute("data-datum");
      var k = mw + "|" + datum;
      // Versie alleen meesturen bij de eerste cel van een dag (de server telt verder)
      var versie = gezien[k] ? null : versieVan(mw, datum);
      gezien[k] = true;
      return { mw: mw, datum: datum, veld: i.cel.getAttribute("data-veld"), waarde: i.waarde, versie: versie };
    });

    return post(API_CELLEN, { wijzigingen: wijzigingen })
      .then(function (r) {
        if (r.status === 409) {
          status("Iemand anders wijzigde dit tegelijk. De pagina wordt ververst…", "fout");
          setTimeout(function () { location.reload(); }, 1500);
          throw new Error("conflict");
        }
        if (r.status === 401) {
          status("Je bent uitgelogd. Log opnieuw in.", "fout");
          throw new Error("uitgelogd");
        }
        if (!r.ok) throw new Error("fout");
        return r.json();
      })
      .then(function (antwoord) {
        Object.keys(antwoord.bijgewerkt).forEach(function (k) {
          var delen = k.split("|");
          werkBij(delen[0], delen[1], antwoord.bijgewerkt[k]);
        });
        celItems.forEach(function (i) { i.cel.classList.remove("bezig"); });
        if (antwoord.fouten.length) {
          antwoord.fouten.forEach(function (f) {
            var cel = document.querySelector('.cel[data-mw="' + f.mw + '"][data-datum="' + f.datum + '"][data-veld="' + f.veld + '"]');
            if (!cel) return;
            cel.classList.add("fout");
            cel.title = f.melding;
            // Ongeldige invoer zichtbaar laten (niet opgeslagen), zodat je ziet wat er mis was
            var poging = celItems.filter(function (i) { return i.cel === cel; })[0];
            if (poging && !f.conflict) cel.textContent = poging.waarde;
          });
          status(antwoord.fouten[0].melding, "fout");
        } else {
          status("Opgeslagen ✓", "ok");
        }
      })
      .catch(function (fout) {
        celItems.forEach(function (i) { i.cel.classList.remove("bezig"); });
        if (fout.message === "fout") status("Opslaan mislukt. Controleer de verbinding.", "fout");
      });
  }

  // Alle cellen van één medewerker/dag bijwerken met de gegevens van de server
  function werkBij(mw, datum, g) {
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
        el.title = g.handmatig ? "Handmatig aangepast" : "";
      } else if (veld === "opmerking") {
        el.textContent = g.opmerking;
        el.setAttribute("style", g.opmerking_stijl);
      } else if (veld === "opm_begin" || veld === "opm_eind") {
        el.textContent = g[veld];
      } else if (toon === "dienstnaam") {
        el.textContent = g.dienstnaam;
        el.setAttribute("style", g.dienst_stijl);
        el.setAttribute("data-versie", g.versie);
      } else if (toon === "uren") {
        el.textContent = g.uren;
      }
      if (veld) { el.classList.remove("fout"); el.removeAttribute("title"); }
      if (veld === "begin" || veld === "eind") el.title = g.handmatig ? "Handmatig aangepast" : "";
    });
    var totaal = document.querySelector('[data-totaal="' + mw + '"]');
    if (totaal) totaal.textContent = g.weektotaal;
  }

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
      var laatste = ongedaan.pop();
      if (laatste) { bewaar(laatste, true); status("Ongedaan gemaakt", "ok"); }
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
