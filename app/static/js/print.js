/* ==========================================================
   Printversie van het weekrooster, zoals het papieren rooster.

   De tabel wordt in de browser opgebouwd uit het schermrooster (.rooster),
   zodat de server de week maar één keer hoeft te maken (snelheid). Opbouwen
   gebeurt bij het laden, vlak voor het printen en na een wijziging in het
   raster (raster.js roept window.bouwPrintRooster aan).

   Per dag een witte kolom (opmerking, dienstnaam als gekleurde balk, begin
   en eind) en een smalle grijze kolom met de uren. Op een dag met twee
   diensten staat dienst 1 bovenaan (met de opmerking achter de naam) en
   dienst 2 eronder, net als op het scherm.

   De tabel wordt onzichtbaar op A4-breedte opgemeten (lange namen, dagopmerkingen
   en randen tellen dus mee), niet geschat:
   1. Past alles op één A4, eventueel met kleinere rijen en letters (tot MIN_RIJ_MM),
      dan één pagina. Tot en met 10 medewerkers met overal twee diensten past altijd,
      13 meestal ook (iets kleinere letters).
   2. Anders meerdere pagina's met hooguit 10 medewerkers per pagina (14 = 10 + 4,
      25 = 10 + 10 + 5). Elke pagina is een eigen tabel met de kopregel (weeknummer
      en datums); een medewerker wordt nooit over twee pagina's verdeeld.
   Zonder JavaScript print de browser het gewone schermrooster.
   ========================================================== */
(function () {
  "use strict";

  // A4 liggend: 210 mm hoog min 2 x 6 mm marge (@page), min 4 mm speling voor verschillen
  // tussen browsers en printers. Alles wordt echt opgemeten, niet geschat.
  var BESCHIKBAAR_MM = 194;
  var MIN_RIJ_MM = 3.4, MAX_RIJ_MM = 7.5, NORMAAL_RIJ_MM = 4.6;
  var PER_PAGINA = 10;  // meerdere pagina's: 10 medewerkers (met twee diensten) per pagina
  var PX_PER_MM = 96 / 25.4;

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

  // Eén printtabel (één pagina) met de kopregel en de blokken van deze medewerkers
  function maakTabel(kopInfo, gegevens, rij, volgende) {
    var schaal = Math.min(1, rij / NORMAAL_RIJ_MM);
    var tabel = el("table", "print-tabel" + (volgende ? " p-volgende" : ""));
    tabel.style.setProperty("--p-rij", rij.toFixed(2) + "mm");
    tabel.style.setProperty("--p-f", schaal.toFixed(3));
    var kolommen = el("colgroup");
    kolommen.appendChild(el("col", "p-naamkol"));
    kopInfo.datums.forEach(function () {
      kolommen.appendChild(el("col", "p-tijdkol"));
      kolommen.appendChild(el("col", "p-tijdkol"));
      kolommen.appendChild(el("col", "p-grijskol"));
    });
    kolommen.appendChild(el("col", "p-urenkol"));
    tabel.appendChild(kolommen);

    // Kopregel: weeknummer, per dag de datum (met dagopmerking als label), Uren
    var kop = el("thead"), kopRij = el("tr");
    var weeknr = el("th", "p-weeknr");
    weeknr.appendChild(el("small", "", kopInfo.team));
    weeknr.appendChild(document.createTextNode("Weeknummer "));
    weeknr.appendChild(el("strong", "", kopInfo.week));
    kopRij.appendChild(weeknr);
    kopInfo.koppen.forEach(function (th, i) {
      var cel = el("th", "p-dag" + (th.classList.contains("weekend") ? " weekend" : ""), tekstVan(th));
      cel.colSpan = 2;
      var label = el("span", "p-dagopm", tekstVan(kopInfo.dagopm[i]));
      label.setAttribute("data-pdagopm", kopInfo.datums[i]);
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
    return tabel;
  }

  // Hoogte in mm zoals de printer hem ziet (de tabel staat onzichtbaar op paginabreedte)
  function mm(e) {
    return e.getBoundingClientRect().height / PX_PER_MM;
  }

  function bouw() {
    var rooster = document.querySelector('.rooster[data-raster="visueel"]');
    var doel = document.querySelector("[data-print-rooster]");
    if (!rooster || !doel) return;

    var kopInfo = {
      team: doel.getAttribute("data-team"), week: doel.getAttribute("data-week"),
      koppen: Array.prototype.slice.call(rooster.querySelectorAll("thead th.dagkop")),
      dagopm: rooster.querySelectorAll("thead .dagopm"),
    };
    kopInfo.datums = Array.prototype.map.call(kopInfo.dagopm, function (c) { return c.getAttribute("data-datum"); });

    // Per blok de plekken per dag; een blok met een dag met twee diensten krijgt 4 regels
    var gegevens = Array.prototype.map.call(rooster.querySelectorAll("tbody.blok"), function (blok) {
      var dagen = kopInfo.datums.map(function (datum) { return plekken(blok, datum); });
      return { blok: blok, dagen: dagen, twee: dagen.some(function (p) { return p.twee; }) };
    });
    var regels = 0;
    gegevens.forEach(function (g) { regels += g.twee ? 4 : 3; });

    // Opmeten gebeurt onzichtbaar op de breedte van een A4 liggend (zie .p-meten)
    doel.classList.add("p-meten");
    var tabellen = [];
    try {
      // 1. Alles op één pagina: de rijhoogte vult de pagina. Gemeten te hoog (lange namen,
      //    dagopmerkingen, randen)? Dan de rijen kleiner, tot MIN_RIJ_MM.
      var rij = Math.min(MAX_RIJ_MM, BESCHIKBAAR_MM / Math.max(regels, 1) * 0.92);
      for (var poging = 0; poging < 6 && rij >= MIN_RIJ_MM - 0.001; poging++) {
        var tabel = maakTabel(kopInfo, gegevens, rij, false);
        doel.replaceChildren(tabel);
        var hoogte = mm(tabel);
        if (hoogte <= BESCHIKBAAR_MM) { tabellen = [tabel]; break; }
        var kopHoogte = mm(tabel.tHead);
        var nieuw = rij * (BESCHIKBAAR_MM - kopHoogte) / (hoogte - kopHoogte) - 0.02;
        rij = rij > MIN_RIJ_MM && nieuw < MIN_RIJ_MM ? MIN_RIJ_MM : nieuw;
      }

      // 2. Past het niet: meerdere pagina's met hooguit PER_PAGINA medewerkers per pagina.
      //    De rijhoogte is zo dat 10 blokken met twee diensten (40 regels) op een pagina
      //    passen (hooguit normaal); elke pagina wordt opgemeten gevuld met hele blokken.
      if (!tabellen.length) {
        var proef = maakTabel(kopInfo, gegevens, NORMAAL_RIJ_MM, false);
        doel.replaceChildren(proef);
        var perRegel = (mm(proef) - mm(proef.tHead)) / Math.max(regels, 1);
        var paginaRij = NORMAAL_RIJ_MM * (BESCHIKBAAR_MM - mm(proef.tHead)) / (perRegel * 4 * PER_PAGINA);
        paginaRij = Math.max(MIN_RIJ_MM, Math.min(NORMAAL_RIJ_MM, paginaRij - 0.02));
        proef = maakTabel(kopInfo, gegevens, paginaRij, false);
        doel.replaceChildren(proef);
        var kop = mm(proef.tHead), verdeling = [], pagina = [], gevuld = kop;
        Array.prototype.forEach.call(proef.tBodies, function (b, i) {
          var h = mm(b);
          if (pagina.length && (pagina.length >= PER_PAGINA || gevuld + h > BESCHIKBAAR_MM)) {
            verdeling.push(pagina);
            pagina = [];
            gevuld = kop;
          }
          pagina.push(gegevens[i]);
          gevuld += h;
        });
        verdeling.push(pagina);
        tabellen = verdeling.map(function (deel, i) { return maakTabel(kopInfo, deel, paginaRij, i > 0); });
      }
    } finally {
      doel.classList.remove("p-meten");
    }
    doel.replaceChildren.apply(doel, tabellen);
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
