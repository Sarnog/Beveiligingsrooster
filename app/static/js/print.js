/* ==========================================================
   Printversie van het weekrooster, zoals het papieren rooster.

   De tabel wordt in de browser opgebouwd uit het schermrooster (.rooster),
   zodat de server de week maar één keer hoeft te maken (snelheid). Opbouwen
   gebeurt bij het laden, vlak voor het printen en na een wijziging in het
   raster (raster.js roept window.bouwPrintRooster aan).

   Per dag een witte kolom (opmerking, dienstnaam als gekleurde balk, begin
   en eind) en een smalle grijze kolom met de uren. Op een dag met twee
   diensten staat dienst 1 bovenaan (met de opmerking achter de naam) en
   dienst 2 eronder, net als op het scherm. De rijhoogte vult de pagina; pas als dat niet past wordt
   het lettertype kleiner. De reserveregel komt er alleen bij als die past.
   Zonder JavaScript print de browser het gewone schermrooster.
   ========================================================== */
(function () {
  "use strict";

  var BESCHIKBAAR_MM = 184;  // A4 liggend (210 mm) min marges en kopregel
  var MIN_RIJ_MM = 3.4, MAX_RIJ_MM = 7.5, NORMAAL_RIJ_MM = 4.6, RESERVE_MIN_MM = 4.4;

  function el(tag, klasse, tekst) {
    var e = document.createElement(tag);
    if (klasse) e.className = klasse;
    if (tekst) e.textContent = tekst;
    return e;
  }

  function tekstVan(cel) {
    return cel ? cel.textContent.trim() : "";
  }

  // Cel met de tekst en kleur (style) van een cel uit het schermrooster
  function kopie(tag, klasse, bron, attributen) {
    var cel = el(tag, klasse, tekstVan(bron));
    if (bron && bron.getAttribute("style")) cel.setAttribute("style", bron.getAttribute("style"));
    Object.keys(attributen || {}).forEach(function (k) { cel.setAttribute(k, attributen[k]); });
    return cel;
  }

  function grijs(klasse) {
    return el("td", "p-grijs" + (klasse ? " " + klasse : ""));
  }

  // Eén regel met per dag een cel over twee kolommen plus de grijze kolom
  function dagRegel(klasse, cellen) {
    var tr = el("tr", klasse);
    cellen.forEach(function (cel) {
      cel.colSpan = 2;
      tr.appendChild(cel);
      tr.appendChild(grijs());
    });
    return tr;
  }

  // Attributen van de bron (voor raster.js en de tests): medewerker, dag, dienst en veld
  function kenmerk(bron) {
    if (!bron || !bron.getAttribute("data-veld")) return {};
    return { "data-pmw": bron.getAttribute("data-mw"), "data-pdatum": bron.getAttribute("data-datum"),
             "data-pvn": bron.getAttribute("data-vn") || "1",
             "data-p": bron.getAttribute("data-toon") || bron.getAttribute("data-veld") };
  }

  // Begin | eind | uren (grijs) per dag; bronnen: per dag [begin, eind, uren] of null (leeg)
  function tijdRegel(klasse, dagen) {
    var tr = el("tr", klasse);
    dagen.forEach(function (d) {
      d = d || [null, null, null];
      tr.appendChild(kopie("td", "p-tijd", d[0], kenmerk(d[0])));
      tr.appendChild(kopie("td", "p-tijd", d[1], kenmerk(d[1])));
      tr.appendChild(kopie("td", "p-grijs p-uren", d[2], kenmerk(d[2])));
    });
    return tr;
  }

  // Gekleurde dienstnaambalk; bij twee diensten met de opmerking erachter (data-opm)
  function balk(bron) {
    var cel = kopie("td", "p-dienst", bron, kenmerk(bron));
    if (bron && bron.getAttribute("data-opm")) cel.textContent += " – " + bron.getAttribute("data-opm");
    return cel;
  }

  // Opmerking met de opmerkingtijden erachter
  function opmerking(plek) {
    var cel = kopie("td", "p-opm", plek.a, kenmerk(plek.a));
    var van = tekstVan(plek.b1), tot = tekstVan(plek.b2);
    if (van || tot) cel.textContent = (cel.textContent + " (" + van + "–" + tot + ")").trim();
    return cel;
  }

  // De cellen van één dag in een blok, op hun vaste plek (zie week.html)
  function plekken(blok, datum) {
    var plek = {};
    blok.querySelectorAll('[data-plek][data-datum="' + datum + '"]').forEach(function (c) {
      plek[c.getAttribute("data-plek")] = c;
    });
    plek.twee = !!(plek.a && plek.a.getAttribute("data-toon") === "dienstnaam");
    return plek;
  }

  function bouw() {
    var rooster = document.querySelector('.rooster[data-raster="visueel"]');
    var doel = document.querySelector("[data-print-rooster]");
    if (!rooster || !doel) return;

    var koppen = rooster.querySelectorAll("thead th.dagkop");
    var datums = Array.prototype.map.call(rooster.querySelectorAll("thead .dagopm"), function (c) {
      return c.getAttribute("data-datum");
    });
    var dagopm = rooster.querySelectorAll("thead .dagopm");
    var blokken = rooster.querySelectorAll("tbody.blok");

    // Per blok de plekken per dag; een blok met een dag met twee diensten krijgt 4 regels
    var gegevens = Array.prototype.map.call(blokken, function (blok) {
      var dagen = datums.map(function (datum) { return plekken(blok, datum); });
      return { blok: blok, dagen: dagen, twee: dagen.some(function (p) { return p.twee; }) };
    });

    // Maat: aantal regels (3 per medewerker, 4 met een dag met twee diensten)
    var regels = 0;
    gegevens.forEach(function (g) { regels += g.twee ? 4 : 3; });
    var reserve = (regels + 3) * RESERVE_MIN_MM <= BESCHIKBAAR_MM;
    var rij = Math.max(Math.min(MAX_RIJ_MM, BESCHIKBAAR_MM / Math.max(regels + (reserve ? 3 : 0), 1)), MIN_RIJ_MM);
    var schaal = Math.min(1, rij / NORMAAL_RIJ_MM);
    var tabel = el("table", "print-tabel");
    tabel.style.setProperty("--p-rij", rij.toFixed(2) + "mm");
    tabel.style.setProperty("--p-f", schaal.toFixed(3));
    var kolommen = el("colgroup");
    kolommen.appendChild(el("col", "p-naamkol"));
    datums.forEach(function () {
      kolommen.appendChild(el("col", "p-tijdkol"));
      kolommen.appendChild(el("col", "p-tijdkol"));
      kolommen.appendChild(el("col", "p-grijskol"));
    });
    kolommen.appendChild(el("col", "p-urenkol"));
    tabel.appendChild(kolommen);

    // Kopregel: weeknummer, per dag de datum (met dagopmerking als label), Uren
    var kop = el("thead"), kopRij = el("tr");
    var weeknr = el("th", "p-weeknr");
    weeknr.appendChild(el("small", "", doel.getAttribute("data-team")));
    weeknr.appendChild(document.createTextNode("Weeknummer "));
    weeknr.appendChild(el("strong", "", doel.getAttribute("data-week")));
    kopRij.appendChild(weeknr);
    koppen.forEach(function (th, i) {
      var cel = el("th", "p-dag" + (th.classList.contains("weekend") ? " weekend" : ""), tekstVan(th));
      cel.colSpan = 2;
      var label = el("span", "p-dagopm", tekstVan(dagopm[i]));
      label.setAttribute("data-pdagopm", datums[i]);
      cel.appendChild(label);
      kopRij.appendChild(cel);
      kopRij.appendChild(el("th", "p-grijs"));
    });
    kopRij.appendChild(el("th", "p-urenkop", "Uren"));
    kop.appendChild(kopRij);
    tabel.appendChild(kop);

    gegevens.forEach(function (g) {
      var blok = g.blok;
      var mw = blok.getAttribute("data-blok");
      var body = el("tbody", "p-blok");
      var naamBron = blok.querySelector(".naamkol");
      var naam = el("th", "p-naam");
      naam.rowSpan = g.twee ? 4 : 3;
      naam.appendChild(document.createTextNode(naamBron.firstChild ? naamBron.firstChild.textContent.trim() : ""));
      var functie = naamBron.querySelector("small");
      if (functie) naam.appendChild(el("small", "", tekstVan(functie)));

      // Regel a: opmerking, of bij twee diensten de balk van dienst 1
      var a = dagRegel("p-a", g.dagen.map(function (p) { return p.twee ? balk(p.a) : opmerking(p); }));
      a.insertBefore(naam, a.firstChild);
      var contract = blok.querySelector(".urenkol.contract");
      a.appendChild(el("td", "p-contract", contract ? contract.getAttribute("data-pcontract") || "" : ""));
      body.appendChild(a);
      // Regel b (alleen in een blok met twee diensten): tijden van dienst 1
      if (g.twee) {
        body.appendChild(tijdRegel("p-b", g.dagen.map(function (p) { return p.twee ? [p.b1, p.b2, p.b3] : null; })));
      }
      // Regel c: dienstnaambalk; regel d: begin, eind en uren
      var c = dagRegel("p-c", g.dagen.map(function (p) { return balk(p.c); }));
      var totaal = el("td", "p-totaal", tekstVan(blok.querySelector("[data-totaal]")));
      totaal.rowSpan = g.twee ? 3 : 2;
      totaal.setAttribute("data-ptotaal", mw);
      if (g.twee) {
        body.lastChild.appendChild(totaal);
      } else {
        c.appendChild(totaal);
      }
      body.appendChild(c);
      body.appendChild(tijdRegel("p-d", g.dagen.map(function (p) { return [p.d1, p.d2, p.d3]; })));
      tabel.appendChild(body);
    });

    // Eén lege reserveregel, om met de hand iemand bij te schrijven (alleen als die past)
    if (reserve) {
      var body = el("tbody", "p-blok p-reserve");
      var a = dagRegel("p-a", datums.map(function () { return el("td", "p-opm"); }));
      var naam = el("th", "p-naam", "Reserve 1");
      naam.rowSpan = 3;
      a.insertBefore(naam, a.firstChild);
      a.appendChild(el("td", "p-contract"));
      body.appendChild(a);
      var c = dagRegel("p-c", datums.map(function () { return el("td", "p-dienst"); }));
      var totaal = el("td", "p-totaal");
      totaal.rowSpan = 2;
      c.appendChild(totaal);
      body.appendChild(c);
      body.appendChild(tijdRegel("p-d", datums.map(function () { return null; })));
      tabel.appendChild(body);
    }

    doel.replaceChildren(tabel);
    document.documentElement.classList.add("print-klaar");
  }

  window.bouwPrintRooster = bouw;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bouw);
  } else {
    bouw();
  }
  window.addEventListener("beforeprint", bouw);
})();
