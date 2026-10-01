/* ==========================================================
   Service worker van het Beveiligingsrooster (versie {{ versie }})

   Bewust zuinig, om oude scripts uit een cache te voorkomen (zie CHANGELOG 1.1.1/1.1.2):
   - HTML-pagina's en /api/-antwoorden worden NOOIT gecachet: altijd vers van de server.
     Zonder verbinding toont een pagina de offline-melding.
   - Alleen statische bestanden met ?v=<versie> worden gecachet (cache-first). Een nieuwe
     versie heeft een ander adres (?v=...), dus nooit een oud script.
   - De cache-naam bevat de versie; oude caches worden bij 'activate' opgeruimd.
   ========================================================== */
"use strict";

var VERSIE = "{{ versie }}";
var CACHE = "rooster-{{ versie }}";
var OFFLINE = "{{ offline }}";
var VOORAF = {{ (statisch + [offline])|tojson }};

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.addAll(VOORAF); })
      .then(function () { return self.skipWaiting(); })  // nieuwe versie direct actief
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (namen) {
      return Promise.all(namen.filter(function (naam) { return naam !== CACHE; })
        .map(function (naam) { return caches.delete(naam); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var verzoek = event.request;
  if (verzoek.method !== "GET") return;
  var url = new URL(verzoek.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.indexOf("/api/") === 0) return;  // API: nooit via de service worker

  // Pagina's: altijd van het netwerk, nooit uit of naar de cache. Offline: melding.
  if (verzoek.mode === "navigate") {
    event.respondWith(fetch(verzoek).catch(function () { return caches.match(OFFLINE); }));
    return;
  }

  // Statische bestanden met de juiste versie: eerst de cache, anders ophalen en bewaren
  if (url.pathname.indexOf("/static/") === 0 && url.searchParams.get("v") === VERSIE) {
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(verzoek).then(function (bewaard) {
          return bewaard || fetch(verzoek).then(function (antwoord) {
            if (antwoord.ok) cache.put(verzoek, antwoord.clone());
            return antwoord;
          });
        });
      })
    );
  }
  // Al het andere (oude ?v=, zonder ?v=, downloads): gewoon het netwerk, niets bewaren
});
