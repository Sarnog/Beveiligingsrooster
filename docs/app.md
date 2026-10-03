# Een echte app bouwen op het Beveiligingsrooster

Sinds versie 1.3.0 is de website al een **installeerbare app (PWA)**. Voor de meeste teams is dat genoeg. Dit document beschrijft wat er klaarstaat, en hoe je later een app in de App Store of Play Store kunt maken.

## Wat er nu al is

| Onderdeel | Waar | Wat het doet |
|---|---|---|
| Telefoonweergave | alle pagina's | Geen inzoomen of zijwaarts scrollen; *Mijn rooster* en het weekrooster zijn voor de telefoon gemaakt; de planner kan op de telefoon een dienst wijzigen. |
| Manifest | `/manifest.webmanifest` | Naam, icoon, themakleur, `display: standalone` (geen adresbalk). |
| Iconen | `app/static/icons/` | 192 en 512 px, een *maskable* versie voor Android en een `apple-touch-icon` voor iOS. Opnieuw maken: `python scripts/maak-iconen.py`. |
| Service worker | `/sw.js` | Bewaart alleen scripts/CSS/iconen met versienummer, en een offline-pagina. Nooit roosterdata, pagina's of API-antwoorden: je ziet altijd het actuele rooster. |
| API | `/api/v1/…` | Alleen lezen: wie ben ik, mijn rooster, weekrooster, dienstcodes. Zie [api.md](api.md) en [openapi.yaml](openapi.yaml). |
| Inloggen voor apps | *Account → API-tokens* | Persoonlijke tokens met verloopdatum, als hash bewaard, ongeldig na wachtwoordwijziging. |

## De PWA installeren (nu al)

Voorwaarde: de app is bereikbaar via **HTTPS** (zie de README, *Bereikbaarheid en HTTPS*). Via gewoon `http://<ip>:8000` installeert een telefoon geen app en werkt de service worker niet; de website zelf werkt dan wel.

- **Android (Chrome):** open de site → menu ⋮ → *App installeren* (of *Toevoegen aan startscherm*).
- **iPhone/iPad (Safari):** open de site → deelknop → *Zet op beginscherm*.

## Android-app (APK)

In de map [`android/`](../android/README.md) staat een kleine Android-app die je eigen website toont (zonder adresbalk), met een instelbaar serveradres. Downloaden, bestand kiezen, printen en links naar andere apps werken. GitHub Actions bouwt de APK (*Actions → Android-app*). Installeren en ondertekenen: zie [android/README.md](../android/README.md).

## Later: een app in de winkels

Er zijn twee eenvoudige routes. Beide gebruiken de bestaande website en API; er hoeft aan de server niets te veranderen.

### Route 1: de PWA verpakken (aanbevolen om mee te beginnen)

- **Android:** met *Trusted Web Activity* (bijvoorbeeld via [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap) of PWABuilder). De app opent je eigen site, zonder adresbalk. Je hebt alleen een bestand `/.well-known/assetlinks.json` op de server nodig (Digital Asset Links); dat is één extra route of een regel in de reverse proxy.
- **iOS:** Apple accepteert een pure website-in-een-doosje meestal niet. Daar is route 2 beter.

### Route 2: Capacitor (iOS en Android)

[Capacitor](https://capacitorjs.com/) maakt van een webapp een echte app met toegang tot bijvoorbeeld pushberichten.

1. Maak een klein, apart front-end-project (bijvoorbeeld met Vite) dat alleen de API gebruikt: inloggen met een API-token, *Mijn rooster* en het weekrooster tonen.
2. Bewaar het token in de beveiligde opslag van het toestel (Keychain/Keystore, bijvoorbeeld met een Capacitor-plugin voor *secure storage*), nooit in gewone `localStorage`.
3. Laat de gebruiker het token aanmaken op de website (*Account → API-tokens*) en plakken of scannen in de app.
4. `npx cap add ios` / `npx cap add android`, bouwen en ondertekenen in Xcode of Android Studio.

Omdat de app een andere oorsprong heeft (`capacitor://localhost` of `https://localhost`), moet de server dan **CORS** toestaan voor de API, alleen voor die oorsprong en alleen voor `/api/v1/`. Dat staat nu bewust uit.

## Wat er later nog bij moet (niet in 1.3.0)

- **Schrijven via de API** (een dienst wijzigen vanuit de app): in `/api/v1` met dezelfde regels als de website (alleen beheerders, versie/409-controle). CSRF is bij tokens niet nodig; bij een sessie wel (dat is al zo geregeld).
- **Pushberichten** bij een roosterwijziging: de worker kan dan een bericht sturen (Web Push voor de PWA, of FCM/APNs voor een Capacitor-app).
- **CORS** voor een app met een eigen oorsprong (zie hierboven).
- Een **inlogscherm in de app** dat zelf een token aanvraagt (nu maak je het token op de website).
