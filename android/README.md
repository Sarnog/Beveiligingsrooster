# Android-app

Een echte Android-app (APK) voor het Beveiligingsrooster. De app toont **je eigen website**, zonder adresbalk, met hetzelfde uiterlijk en dezelfde knoppen als in de browser. Je logt in met je gewone gebruikersnaam en wachtwoord; de planner kan in de app ook diensten wijzigen.

## Hoe werkt het?

- Bij de eerste start vul je het **serveradres** in, bijvoorbeeld `https://rooster.voorbeeld.nl` of op het eigen netwerk `http://192.168.1.10:8000`. De app controleert dat adres via `/health`.
- Daarna opent de app de website. Alles wat in de browser kan, kan hier ook: *Mijn rooster*, weekrooster, kalender, beheer, licht/donker.
- **Server wijzigen:** houd het app-icoon ingedrukt → *Server wijzigen*. Of tik op *Server wijzigen* op het foutscherm als de server niet bereikbaar is.
- **Links naar andere sites** (bijv. *Toevoegen aan mijn agenda*) openen in de browser of agenda-app.
- **Downloaden** (CSV, Excel, back-up) gaat naar de map *Downloads*, met een melding als het klaar is.
- **Bestand kiezen** (Excel-import, back-up terugzetten) en **printen** (A4 liggend, of *Opslaan als PDF*) werken ook.
- De app volgt licht/donker van de telefoon, net als de website.
- Er staat **geen roosterdata in de app**; alles komt live van je server. Alleen de inlog (cookie) en het serveradres worden bewaard.

> Aan de server hoeft niets te veranderen. De app gebruikt dezelfde pagina's als de browser.

## De APK bouwen (zonder zelf iets te installeren)

GitHub bouwt de app voor je:

1. Ga op GitHub naar **Actions → Android-app**.
2. Klik rechts op **Run workflow** → **Run workflow** (of push een wijziging in de map `android/`).
3. Wacht tot de run groen is (een paar minuten) en open hem.
4. Onderaan bij **Artifacts** staat **Beveiligingsrooster-android**. Download dat zip-bestand en pak het uit: daarin zit `Beveiligingsrooster.apk`.

## Installeren op de telefoon

1. Zet `Beveiligingsrooster.apk` op de telefoon (bijv. via Google Drive, een USB-kabel of mail aan jezelf).
2. Tik op het bestand. Android vraagt of je **apps uit deze bron** wilt toestaan (bijv. *Bestanden* of *Drive*): zet dat aan.
3. Tik op **Installeren**. Play Protect kan waarschuwen dat de app onbekend is: kies *Toch installeren*.
4. Open **Rooster** en vul het serveradres in.

Werkt op Android 10 en nieuwer.

## Eigen sleutel (aanbevolen, eenmalig)

Elke APK is ondertekend met een sleutel. Zonder eigen sleutel maakt GitHub bij elke run een nieuwe tijdelijke sleutel; een nieuwere APK installeert dan **niet** over de oude heen (eerst de oude verwijderen, en opnieuw inloggen). Met een eigen sleutel is een nieuwe APK gewoon een update.

Eenmalig, op een computer met Java (bijv. je Debian-machine: `sudo apt install default-jdk-headless`):

```sh
# 1. Sleutel maken (vraagt om een wachtwoord en je naam; bewaar het bestand en wachtwoord goed!)
keytool -genkeypair -v -keystore rooster.jks -alias rooster \
  -keyalg RSA -keysize 4096 -validity 10000

# 2. Omzetten naar tekst om in GitHub te plakken
base64 -w0 rooster.jks > rooster.jks.txt
```

Ga daarna op GitHub naar **Settings → Secrets and variables → Actions → New repository secret** en maak deze vier geheimen:

| Naam | Waarde |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | de inhoud van `rooster.jks.txt` |
| `ANDROID_KEYSTORE_WACHTWOORD` | het wachtwoord uit stap 1 |
| `ANDROID_SLEUTEL_ALIAS` | `rooster` |
| `ANDROID_SLEUTEL_WACHTWOORD` | hetzelfde wachtwoord (tenzij je een apart sleutelwachtwoord koos) |

Zet `rooster.jks` **nooit** in git (de `.gitignore` houdt hem al tegen) en bewaar een kopie: kwijt = geen updates meer, alleen opnieuw installeren.

> Wissel je van tijdelijke naar eigen sleutel, dan moet je de app één keer verwijderen en de nieuwe installeren.

## Zelf bouwen met Android Studio (optioneel)

Open de map `android/` in Android Studio en kies *Run*. Of in een terminal (met de Android SDK):

```sh
cd android
./gradlew assembleDebug   # APK in app/build/outputs/apk/debug/
```

## Goed om te weten

- **Gebruik https** als de app via internet verbindt (zie de README van de server: reverse proxy of tunnel). Over gewoon `http://` kan iemand op hetzelfde netwerk je wachtwoord meelezen; de app waarschuwt daarvoor.
- Een **zelf ondertekend certificaat** accepteert de app niet (net als een browser zonder uitzondering). Gebruik een echt certificaat, bijv. via Let's Encrypt in je reverse proxy.
- **Versienummer:** `versionName` staat in `app/build.gradle`. Het interne nummer (`versionCode`) telt in GitHub Actions vanzelf op, zodat Android een nieuwe APK als update ziet.
- De app is los van de serverversie: een nieuwe server-release vraagt geen nieuwe app.
