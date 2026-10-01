/* ==========================================================
   Printversie van het weekrooster, zoals het papieren rooster.

   De tabel wordt in de browser opgebouwd uit het schermrooster (.rooster),
   zodat de server de week maar één keer hoeft te maken (snelheid). Opbouwen
   gebeurt bij het laden, vlak voor het printen en na een wijziging in het
   raster (raster.js roept window.bouwPrintRooster aan).

   Per dag een witte kolom (opmerking, dienstnaam als gekleurde balk, begin
   en eind) en een smalle grijze kolom met de uren. Een tweede dienst staat
   onder de eerste. De rijhoogte vult de pagina; pas als dat niet past wordt
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

  // Begin | eind | uren (grijs) per dag
  function tijdRegel(klasse, dagen) {
    var tr = el("tr", klasse);
    dagen.forEach(function (d) {
      tr.appendChild(kopie("td", "p-tijd", d.begin, d.attr("begin")));
      tr.appendChild(kopie("td", "p-tijd", d.eind, d.attr("eind")));
      var uren = kopie("td", "p-grijs p-uren", d.uren, d.attr("uren"));
      tr.appendChild(uren);
    });
    return tr;
  }

  // Gegevens van één dienst (1 of 2) van een medewerker op een dag, uit het schermrooster
  function dienstVan(blok, mw, datum, vn) {
    var sel = '[data-mw="' + mw + '"][data-datum="' + datum + '"]' + (vn === "2" ? '[data-vn="2"]' : ':not([data-vn="2"])');
    return {
      naam: blok.querySelector('[data-toon="dienstnaam"]' + sel),
      begin: blok.querySelector('[data-veld="begin"]' + sel),
      eind: blok.querySelector('[data-veld="eind"]' + sel),
      uren: blok.querySelector('[data-toon="uren"]' + sel),
      attr: function (veld) { return { "data-pmw": mw, "data-pdatum": datum, "data-pvn": vn, "data-p": veld }; }
    };
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

    // Maat: aantal regels (3 per medewerker, 5 met een tweede dienst)
    var regels = 0;
    blokken.forEach(function (b) { regels += b.querySelector("tr.tweede-rij") ? 5 : 3; });
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

    blokken.forEach(function (blok) {
      var mw = blok.getAttribute("data-blok");
      var tweede = !!blok.querySelector("tr.tweede-rij");
      var body = el("tbody", "p-blok");
      var naamBron = blok.querySelector(".naamkol");
      var naam = el("th", "p-naam");
      naam.rowSpan = tweede ? 5 : 3;
      naam.appendChild(document.createTextNode(naamBron.firstChild ? naamBron.firstChild.textContent.trim() : ""));
      var functie = naamBron.querySelector("small");
      if (functie) naam.appendChild(el("small", "", tekstVan(functie)));

      var d1 = datums.map(function (datum) { return dienstVan(blok, mw, datum, "1"); });
      var d2 = datums.map(function (datum) { return dienstVan(blok, mw, datum, "2"); });

      // Regel a: opmerking (met de opmerkingtijden erachter)
      var opmerkingen = datums.map(function (datum) {
        var sel = '[data-mw="' + mw + '"][data-datum="' + datum + '"]';
        var bron = blok.querySelector('[data-veld="opmerking"]' + sel);
        var cel = kopie("td", "p-opm", bron, { "data-pmw": mw, "data-pdatum": datum, "data-pvn": "1", "data-p": "opmerking" });
        var van = tekstVan(blok.querySelector('[data-veld="opm_begin"]' + sel));
        var tot = tekstVan(blok.querySelector('[data-veld="opm_eind"]' + sel));
        if (van || tot) cel.textContent = (cel.textContent + " (" + van + "–" + tot + ")").trim();
        return cel;
      });
      var a = dagRegel("p-a", opmerkingen);
      a.insertBefore(naam, a.firstChild);
      var contract = blok.querySelector(".urenkol.contract");
      a.appendChild(el("td", "p-contract", contract ? contract.getAttribute("data-pcontract") || "" : ""));
      body.appendChild(a);

      // Regel c: dienstnaam als gekleurde balk; regel d: begin, eind en uren
      var c = dagRegel("p-c", d1.map(function (d) { return kopie("td", "p-dienst", d.naam, d.attr("dienstnaam")); }));
      var totaal = el("td", "p-totaal", tekstVan(blok.querySelector("[data-totaal]")));
      totaal.rowSpan = tweede ? 4 : 2;
      totaal.setAttribute("data-ptotaal", mw);
      c.appendChild(totaal);
      body.appendChild(c);
      body.appendChild(tijdRegel("p-d", d1));
      if (tweede) {
        body.appendChild(dagRegel("p-e", d2.map(function (d) { return kopie("td", "p-dienst", d.naam, d.attr("dienstnaam")); })));
        body.appendChild(tijdRegel("p-f", d2));
      }
      tabel.appendChild(body);
    });

    // Eén lege reserveregel, om met de hand iemand bij te schrijven (alleen als die past)
    if (reserve) {
      var leeg = datums.map(function () { return { attr: function () { return {}; } }; });
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
      body.appendChild(tijdRegel("p-d", leeg));
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
