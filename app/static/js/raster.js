/* ==========================================================
   Excel-achtige bediening van het weekrooster (alleen beheerder)

   Er zijn twee rasters: het code-raster (dienstcodes per dag) en het
   visuele rooster (opmerkingen, tijden, dagopmerkingen). Elke bewerkbare
   cel heeft de klasse "cel" en deze data-attributen:
     data-r / data-c / data-cs  positie in het raster (rij, kolom, breedte)
     data-mw / data-datum        medewerker en dag
     data-veld                   welk veld (code, begin, eind, opmerking, ...)
     data-vn                     "2" bij de tweede dienst van die dag (anders dienst 1)

   Twee diensten op één dag: typ in het code-raster bijvoorbeeld 4/7 (ook 4+7 of
   4 7). Elk blok in het visuele rooster heeft per dag vier regels (data-plek a,
   b1-b3, c, d1-d3). Bij één dienst: opmerking, opmerkingtijden, dienstnaam,
   tijden. Bij twee diensten: dienst 1 bovenaan (de opmerking achter de
   dienstnaam), dienst 2 onderaan. vulDag() wisselt die indeling per dag.

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
  var SCRIPT_VERSIE = "1.8.0";

  var houder = document.querySelector("[data-api-cellen]");
  if (!houder) return;

  // Hoort dit script bij deze pagina? Zo niet (een oude versie uit een cache), dan
  // niets laten bewerken en melden dat de pagina opnieuw geladen moet worden.
  if (houder.getAttribute("data-versie") !== SCRIPT_VERSIE) {
    document.querySelectorAll("[data-status]").forEach(function (melding) {
      melding.textContent = "Verouderde versie geladen. Ververs de pagina (Ctrl+F5) voordat je iets wijzigt.";
      melding.className = "raster-status fout";
    });
    document.querySelectorAll("[data-opslaan], [data-paneel-opslaan]").forEach(function (k) { k.disabled = true; });
    return;
  }
  var API_CELLEN = houder.getAttribute("data-api-cellen");
  // Statusregels: bij het raster, in de telefoonweergave en in het bewerkpaneel
  var statusVakken = document.querySelectorAll("[data-status]");
  var statusVak = statusVakken[0];

  // ---------- Raster: posities van cellen ----------

  function Raster(tabel) {
    this.tabel = tabel;
    this.matrix = {};   // matrix[r][c] = cel
    this.rijen = [];    // gesorteerde rijnummers
    this.maxC = 0;
    this.voegToe(tabel.querySelectorAll(".cel"));
  }

  // Cellen in het raster opnemen (bij het laden, en nieuwe rijen voor een tweede dienst)
  Raster.prototype.voegToe = function (cellen) {
    var zelf = this;
    cellen.forEach(function (cel) {
      cel.setAttribute("tabindex", "-1");
      cel._raster = zelf;
      var r = parseInt(cel.getAttribute("data-r"), 10);
      var c = parseInt(cel.getAttribute("data-c"), 10);
      var cs = parseInt(cel.getAttribute("data-cs") || "1", 10);
      zelf.maxC = Math.max(zelf.maxC, c + cs - 1);
      cel._r = r; cel._c = c; cel._cs = cs;
      if (!zelf.matrix[r]) { zelf.matrix[r] = {}; zelf.rijen.push(r); }
      for (var k = 0; k < cs; k++) zelf.matrix[r][c + k] = cel;
    });
    this.rijen.sort(function (a, b) { return a - b; });
  };

  // Cel uit het raster halen (een plek die geen bewerkbare cel meer is)
  Raster.prototype.verwijder = function (cel) {
    for (var k = 0; k < (cel._cs || 1); k++) {
      if (this.matrix[cel._r] && this.matrix[cel._r][cel._c + k] === cel) delete this.matrix[cel._r][cel._c + k];
    }
    cel._raster = null;
  };

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
  function zetStatusKlasse(klasse) {
    statusVakken.forEach(function (vak) { vak.className = klasse; });
  }
  function status(tekst, soort) {
    if (!statusVak) return;
    statusVakken.forEach(function (vak) { vak.textContent = tekst; });
    zetStatusKlasse("raster-status " + (soort || ""));
    clearTimeout(statusTimer);
    if (soort === "ok") {
      statusTimer = setTimeout(function () { zetStatusKlasse("raster-status"); }, 2500);
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

  // Volgnummer van de dienst bij een cel: "2" = tweede dienst van de dag, anders "1"
  function vnVan(el) {
    return el.getAttribute("data-vn") === "2" ? "2" : "1";
  }

  // Selector voor de cel van één veld van dienst 1 of 2 van een medewerker op een dag
  function celSelector(mw, datum, veld, vn) {
    return '.cel[data-mw="' + mw + '"][data-datum="' + datum + '"][data-veld="' + veld + '"]' +
      (String(vn) === "2" ? '[data-vn="2"]' : ':not([data-vn="2"])');
  }

  function versieVan(mw, datum, vn) {
    var naam = document.querySelector('[data-toon="dienstnaam"][data-mw="' + mw + '"][data-datum="' + datum + '"]' +
      (String(vn) === "2" ? '[data-vn="2"]' : ':not([data-vn="2"])'));
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
      var vn = vnVan(i.cel);
      var dag = veld === "dagopmerking";
      var sleutel = dag ? "dag|" + datum : mw + "|" + datum + "|" + veld + "|" + vn;
      // Zelfde cel opnieuw gewijzigd: alleen de laatste waarde telt
      wachtend = wachtend.filter(function (w) { return w.sleutel !== sleutel; });
      wachtend.push({ sleutel: sleutel, dag: dag, mw: mw, datum: datum, veld: veld, vn: vn, waarde: i.waarde });
      if (dag) { getoondeDagen[datum] = true; } else { getoond[mw + "|" + datum] = true; }
      i.cel.textContent = i.waarde;  // direct tonen wat er getypt is
      i.cel.classList.remove("fout");
    });
    zetStatusKlasse("raster-status");  // oude foutmelding weghalen
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
      // Versies per dienst meesturen, alleen bij de eerste wijziging van die dienst.
      // Een code uit het code-raster ('4/7') raakt beide diensten van de dag.
      var k = w.mw + "|" + w.datum + "|" + w.vn;
      var k2 = w.mw + "|" + w.datum + "|2";
      var cel = { mw: w.mw, datum: w.datum, veld: w.veld, waarde: w.waarde, volgnummer: parseInt(w.vn, 10),
                  versie: gezien[k] ? null : versieVan(w.mw, w.datum, w.vn) };
      gezien[k] = true;
      if (w.veld === "code" && w.vn === "1") {
        cel.versie2 = gezien[k2] ? null : versieVan(w.mw, w.datum, "2");
        gezien[k2] = true;
      }
      cellen.push(cel);
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
          } else if ((antwoord.waarschuwingen || []).length) {
            status("Opgeslagen ✓ – " + antwoord.waarschuwingen[0].melding, "waarschuwing");
            if (daarna) daarna();
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
      document.querySelectorAll('[data-mdagopm][data-datum="' + datum + '"]').forEach(function (p) {
        p.textContent = g.tekst;
        p.classList.toggle("gevuld", !!g.tekst);
      });
    });
    // Ongeldige invoer: rood tonen en niet meenemen bij het opslaan
    antwoord.fouten.forEach(function (f) {
      var vn = String(f.vn || 1);
      var cel = document.querySelector(celSelector(f.mw, f.datum, f.veld, vn));
      var sleutel = f.mw + "|" + f.datum + "|" + f.veld + "|" + vn;
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
    // Overlappende tijden van twee diensten: niet tegenhouden, wel waarschuwen
    var waarschuwingen = antwoord.waarschuwingen || [];
    if (waarschuwingen.length && !antwoord.fouten.length && !opgeslagen) status(waarschuwingen[0].melding, "waarschuwing");
    if (window.bouwPrintRooster) window.bouwPrintRooster();  // printversie bijwerken (print.js)
  }

  function markeerGewijzigd() {
    document.querySelectorAll(".cel.gewijzigd").forEach(function (c) { c.classList.remove("gewijzigd"); });
    wachtend.forEach(function (w) {
      var selector = w.dag ? '.dagopm[data-datum="' + w.datum + '"]' : celSelector(w.mw, w.datum, w.veld, w.vn);
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

  // Lege dienst (er is geen tweede dienst op die dag)
  var LEEG = { code: "", dienstnaam: "", begin: "", eind: "", uren: "", handmatig: false, uren_handmatig: false,
               opmerking: "", opm_begin: "", opm_eind: "", versie: 0, dienst_stijl: "", opmerking_stijl: "" };

  // Rol van elke plek in het blok van één dag (zie week.html)
  var ROLLEN_EEN = {
    a: { veld: "opmerking", klasse: "opm" },
    b1: { veld: "opm_begin", klasse: "tijd opmtijd" },
    b2: { veld: "opm_eind", klasse: "tijd opmtijd" },
    b3: null,  // lege cel
    c: { veld: "dienstnaam", toon: "dienstnaam", vn: "1", klasse: "dienstnaam" },
    d1: { veld: "begin", vn: "1", klasse: "tijd" },
    d2: { veld: "eind", vn: "1", klasse: "tijd" },
    d3: { veld: "uren", toon: "uren", vn: "1", klasse: "uren" }
  };
  var ROLLEN_TWEE = {
    a: { veld: "dienstnaam", toon: "dienstnaam", vn: "1", klasse: "dienstnaam" },
    b1: { veld: "begin", vn: "1", klasse: "tijd" },
    b2: { veld: "eind", vn: "1", klasse: "tijd" },
    b3: { veld: "uren", toon: "uren", vn: "1", klasse: "uren" },
    c: { veld: "dienstnaam", toon: "dienstnaam", vn: "2", klasse: "dienstnaam" },
    d1: { veld: "begin", vn: "2", klasse: "tijd" },
    d2: { veld: "eind", vn: "2", klasse: "tijd" },
    d3: { veld: "uren", toon: "uren", vn: "2", klasse: "uren" }
  };
  var TOESTAND = ["actief", "geselecteerd", "bewerken"];  // blijven staan bij het wisselen

  function opmerkingTekst(g) {
    return g.opmerking + (g.opm_begin || g.opm_eind ? " (" + g.opm_begin + "–" + g.opm_eind + ")" : "");
  }

  // Eén dag van één medewerker in het visuele rooster vullen; wisselt zo nodig de indeling.
  // g = dienst 1 (met opmerking en code(s)), g.tweede = dienst 2 (of null).
  function vulDag(mw, datum, g, opgeslagen) {
    var twee = !!g.tweede;
    var rollen = twee ? ROLLEN_TWEE : ROLLEN_EEN;
    // Versies van vóór dit antwoord: een voorbeeld is niet bewaard, dan blijft de oude versie
    var versies = { "1": versieVan(mw, datum, "1"), "2": versieVan(mw, datum, "2") };
    var raster = null;
    document.querySelectorAll('[data-plek][data-mw="' + mw + '"][data-datum="' + datum + '"]').forEach(function (el) {
      var rol = rollen[el.getAttribute("data-plek")];
      var d = rol && rol.vn === "2" ? g.tweede : g;
      var wasCel = el.classList.contains("cel");
      var staat = TOESTAND.filter(function (k) { return el.classList.contains(k); });
      raster = raster || el._raster || rasters.filter(function (r) { return r.tabel.contains(el); })[0];
      ["data-veld", "data-toon", "data-vn", "data-versie", "data-opm", "title", "style"].forEach(function (a) {
        el.removeAttribute(a);
      });
      if (!rol) {
        el.className = "leeg";
        el.textContent = "";
        el.removeAttribute("tabindex");
        if (wasCel && raster) raster.verwijder(el);
        return;
      }
      el.className = "cel " + rol.klasse + (staat.length ? " " + staat.join(" ") : "");
      el.setAttribute("data-veld", rol.veld);
      if (rol.toon) el.setAttribute("data-toon", rol.toon);
      if (rol.vn === "2") el.setAttribute("data-vn", "2");
      var tekst = "";
      if (rol.veld === "dienstnaam") {
        tekst = d.dienstnaam;
        el.setAttribute("style", d.dienst_stijl);
        el.setAttribute("data-versie", opgeslagen ? d.versie : versies[rol.vn]);
        // Twee diensten: de opmerking van de dag staat achter de dienstnaam van dienst 1 (CSS)
        if (twee && rol.vn === "1" && opmerkingTekst(g)) {
          el.setAttribute("data-opm", opmerkingTekst(g));
          el.title = "Opmerking: " + opmerkingTekst(g);
        }
      } else if (rol.veld === "opmerking") {
        tekst = g.opmerking;
        el.setAttribute("style", g.opmerking_stijl);
      } else if (rol.veld === "opm_begin" || rol.veld === "opm_eind") {
        tekst = g[rol.veld];
      } else if (rol.veld === "uren") {
        tekst = d.uren;
        el.classList.toggle("handmatig", !!d.uren_handmatig);
        if (d.uren_handmatig) el.title = "Zelf ingevulde uren";
      } else {  // begin, eind
        tekst = d[rol.veld];
        el.classList.toggle("handmatig", !!d.handmatig);
        if (d.handmatig) el.title = "Handmatig aangepast";
      }
      if (!(invoer && el.contains(invoer))) el.textContent = tekst;  // niet midden in het typen
      if (!wasCel && raster) raster.voegToe([el]);
    });
  }

  // Alle cellen van één medewerker/dag bijwerken met de gegevens van de server
  function werkBij(mw, datum, g, opgeslagen) {
    var code = document.querySelector('[data-veld="code"][data-mw="' + mw + '"][data-datum="' + datum + '"]');
    if (code) {
      code.textContent = g.code;
      code.setAttribute("style", g.code_stijl || g.dienst_stijl);
      code.classList.remove("fout");
      code.removeAttribute("title");
    }
    vulDag(mw, datum, g, opgeslagen);
    var totaal = document.querySelector('[data-totaal="' + mw + '"]');
    if (totaal) totaal.textContent = g.weektotaal;
    werkKaartenBij(mw, datum, g);
  }

  // Kaarten in de telefoonweergave bijwerken (zelfde gegevens als het raster)
  function werkKaartenBij(mw, datum, g) {
    var t = g.tweede || LEEG;
    document.querySelectorAll('[data-mkaart][data-mw="' + mw + '"][data-datum="' + datum + '"]').forEach(function (kaart) {
      var naam = kaart.querySelector('[data-m="dienstnaam"]');
      naam.textContent = g.dienstnaam;
      naam.setAttribute("style", g.dienst_stijl);
      kaart.querySelector('[data-m="tijden"]').textContent = g.begin ? g.begin + " – " + g.eind : "";
      kaart.querySelector('[data-m="uren"]').textContent = g.uren;
      var opm = kaart.querySelector('[data-m="opmerking"]');
      opm.textContent = opmerkingTekst(g);  // zelfde regel als het rooster: begin óf eind
      opm.setAttribute("style", g.opmerking_stijl);
      var blok = kaart.querySelector('[data-m="tweede"]');
      if (!blok && g.tweede) {
        // Eerste tweede dienst op deze dag: het blok aanmaken (zelfde opbouw als in de template)
        blok = document.createElement("span");
        blok.className = "dk-tweede";
        blok.setAttribute("data-m", "tweede");
        ["dk-dienst|dienstnaam2", "dk-tijden|tijden2", "dk-uren|uren2"].forEach(function (d) {
          var deel = document.createElement("span");
          deel.className = d.split("|")[0];
          deel.setAttribute("data-m", d.split("|")[1]);
          blok.appendChild(deel);
        });
        kaart.insertBefore(blok, opm);
      }
      if (blok) {
        blok.hidden = !g.tweede;
        var naam2 = blok.querySelector('[data-m="dienstnaam2"]');
        naam2.textContent = t.dienstnaam;
        naam2.setAttribute("style", t.dienst_stijl);
        blok.querySelector('[data-m="tijden2"]').textContent = t.begin ? t.begin + " – " + t.eind : "";
        blok.querySelector('[data-m="uren2"]').textContent = t.uren;
      }
    });
    var totaal = document.querySelector('[data-mtotaal="' + mw + '"]');
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

  // ---------- Bewerkpaneel voor de telefoon (bottom sheet) ----------
  // Tik op een dag in de telefoonweergave: alle velden van die dag in één paneel.
  // Opslaan gaat via dezelfde weg als het raster: de wijzigingen komen in 'wachtend'
  // (op de cellen van het verborgen raster) en daarna volgt opslaan(), met versies,
  // 409-afhandeling en de waarschuwing bij niet-opgeslagen wijzigingen.
  var paneel = document.getElementById("dienst-paneel");
  var PANEEL_VELDEN = ["code", "begin", "eind", "opmerking", "opm_begin", "opm_eind", "uren"];

  // Het paneel wijzigt dienst 1 (en de code(s) uit het code-raster)
  function rasterCel(mw, datum, veld) {
    return document.querySelector(celSelector(mw, datum, veld, "1"));
  }

  if (paneel) {
    var formulier = paneel.querySelector("form");
    var urenVak = paneel.querySelector("[data-paneel-uren]");
    var titel = paneel.querySelector("[data-paneel-titel]");
    var huidig = null;   // {mw, datum, basis: {veld: waarde}}
    var voorbeeldTimer = null;

    var veldVan = function (naam) { return formulier.elements[naam]; };

    // Wat staat er nu (inclusief niet-opgeslagen wijzigingen) in het raster?
    var leesDag = function (mw, datum) {
      var waarden = {};
      PANEEL_VELDEN.forEach(function (veld) {
        var cel = rasterCel(mw, datum, veld);
        var tekst = cel ? cel.textContent.trim() : "";
        // Uren alleen invullen als ze zelf ingevuld zijn; anders rekent de app ze uit
        if (veld === "uren" && cel && !cel.classList.contains("handmatig")) tekst = "";
        waarden[veld] = tekst;
      });
      waarden.uren_getoond = (rasterCel(mw, datum, "uren") || { textContent: "" }).textContent.trim();
      return waarden;
    };

    var gewijzigdeVelden = function () {
      return PANEEL_VELDEN.filter(function (veld) {
        return veldVan(veld).value.trim() !== huidig.basis[veld];
      });
    };

    var toonUren = function (tekst) { urenVak.textContent = tekst || "–"; };

    // Voorbeeld van de uren (en standaardtijden bij een andere dienstcode); niets wordt bewaard
    var paneelVoorbeeld = function () {
      clearTimeout(voorbeeldTimer);
      voorbeeldTimer = setTimeout(function () {
        if (!huidig) return;
        var mw = huidig.mw, datum = huidig.datum;
        var codeGewijzigd = veldVan("code").value !== huidig.basis.code;
        var wijzigingen = gewijzigdeVelden().map(function (veld, i) {
          return { mw: mw, datum: datum, veld: veld, waarde: veldVan(veld).value.trim(),
                   versie: i === 0 ? versieVan(mw, datum) : null };
        });
        if (!wijzigingen.length) { toonUren(huidig.basis.uren_getoond); return; }
        var verzoekVoorbeeld = { opslaan: false, wijzigingen: wijzigingen, dagopmerkingen: [],
                                 ook_tonen: [], ook_dagen: [] };
        post(verzoekVoorbeeld).then(leesAntwoord).then(function (antwoord) {
          if (!huidig || huidig.mw !== mw || huidig.datum !== datum) return;
          var fout = antwoord.fouten[0];
          if (fout) { status(fout.melding, "fout"); toonUren(""); return; }
          var g = antwoord.bijgewerkt[mw + "|" + datum];
          if (!g) return;
          toonUren(g.uren);
          // Andere dienstcode: standaardtijden overnemen (niet als 'eigen tijden' tellen)
          if (codeGewijzigd && !huidig.tijdenAangeraakt) {
            veldVan("begin").value = g.begin;
            veldVan("eind").value = g.eind;
            huidig.basis.begin = g.begin;
            huidig.basis.eind = g.eind;
            huidig.basis.code = veldVan("code").value;
            huidig.vanCode = true;
          }
        }).catch(function () { toonUren(""); });
      }, 250);
    };

    var openPaneel = function (kaart) {
      var mw = kaart.getAttribute("data-mw");
      var datum = kaart.getAttribute("data-datum");
      var waarden = leesDag(mw, datum);
      huidig = { mw: mw, datum: datum, basis: waarden, tijdenAangeraakt: false, kaart: kaart,
                 origineleCode: waarden.code };
      // Twee diensten ('4/7'): als extra keuze tonen, zodat die niet ongemerkt verdwijnt
      var keuzes = veldVan("code");
      keuzes.querySelectorAll("[data-twee-codes]").forEach(function (o) { o.remove(); });
      if (waarden.code && !Array.prototype.some.call(keuzes.options, function (o) { return o.value === waarden.code; })) {
        var extra = document.createElement("option");
        extra.value = waarden.code;
        extra.textContent = waarden.code + " – twee diensten (wijzigen in het code-raster)";
        extra.setAttribute("data-twee-codes", "");
        keuzes.appendChild(extra);
      }
      PANEEL_VELDEN.forEach(function (veld) { veldVan(veld).value = waarden[veld]; });
      titel.textContent = kaart.querySelector(".dk-titel").textContent +
        (kaart.closest("[data-dagpagina]") ? " – " + kaart.closest("[data-dagpagina]").getAttribute("aria-label") : "");
      toonUren(waarden.uren_getoond);
      zetStatusKlasse("raster-status");
      statusVakken.forEach(function (vak) { if (paneel.contains(vak)) vak.textContent = ""; });
      paneel.showModal();
      veldVan("code").focus();
    };

    var sluitPaneel = function () {
      clearTimeout(voorbeeldTimer);
      if (paneel.open) paneel.close();
      if (huidig && huidig.kaart) huidig.kaart.focus();
      huidig = null;
    };

    document.addEventListener("click", function (e) {
      var kaart = e.target.closest ? e.target.closest("[data-bewerk-dag]") : null;
      if (kaart) openPaneel(kaart);
    });
    formulier.addEventListener("input", function (e) {
      if (!huidig) return;
      if (e.target.name === "begin" || e.target.name === "eind") huidig.tijdenAangeraakt = true;
      paneelVoorbeeld();
    });
    formulier.addEventListener("change", paneelVoorbeeld);
    paneel.querySelector("[data-paneel-annuleren]").addEventListener("click", sluitPaneel);
    paneel.addEventListener("cancel", function () { huidig = null; });  // Esc

    paneel.querySelector("[data-paneel-opslaan]").addEventListener("click", function () {
      if (!huidig) return;
      clearTimeout(voorbeeldTimer);
      var mw = huidig.mw, datum = huidig.datum;
      // Dienstcode gewijzigd? Die gaat eerst (zet de standaardtijden); daarna de rest.
      var velden = gewijzigdeVelden();
      if (huidig.vanCode && velden.indexOf("code") === -1 && huidig.origineleCode !== veldVan("code").value) {
        velden.unshift("code");
      }
      var items = [];
      velden.forEach(function (veld) {
        var cel = rasterCel(mw, datum, veld);
        if (cel) items.push({ cel: cel, waarde: veldVan(veld).value.trim() });
      });
      if (!items.length && !heeftWijzigingen()) { sluitPaneel(); return; }
      bewaar(items);
      opslaan(function () { sluitPaneel(); });
    });
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
