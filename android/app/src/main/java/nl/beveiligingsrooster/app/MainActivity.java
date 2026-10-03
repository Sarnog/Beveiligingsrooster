package nl.beveiligingsrooster.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.print.PrintAttributes;
import android.print.PrintManager;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

/**
 * Het rooster: de eigen website in een WebView, zonder adresbalk.
 *
 * Alles wat je in de browser ziet en mag, zie en mag je hier ook (dezelfde pagina's,
 * dezelfde inlog). Wat een WebView niet vanzelf kan, regelt deze klasse:
 * links naar andere sites openen in de browser, downloaden (CSV, Excel, back-up),
 * een bestand kiezen (Excel-import, back-up terugzetten), printen en de terugknop.
 */
public class MainActivity extends Activity {

    private static final int KIES_BESTAND = 1;

    /**
     * window.print() doet niets in een WebView. Daarom vervangen we het door een aanroep
     * naar de app (Brug.afdrukken). Eerst de printtabel van het weekrooster bijwerken,
     * net als de browser doet bij 'beforeprint' (zie app/static/js/print.js).
     */
    private static final String AFDRUK_SCRIPT =
            "window.print = function () {"
                    + " if (window.bouwPrintRooster) { window.bouwPrintRooster(); }"
                    + " AndroidApp.afdrukken();"
                    + "};";

    private WebView web;
    private ProgressBar voortgang;
    private View fout;
    private TextView foutTekst;

    /** Het serveradres dat nu geladen is (om een wijziging te zien in onResume). */
    private String geladenServer;
    /** Na het wisselen van server: de terug-geschiedenis van de oude server vergeten. */
    private boolean wisGeschiedenis;
    /** Wacht op het gekozen bestand (Excel-import, back-up terugzetten). */
    private ValueCallback<Uri[]> bestandTerug;

    @Override
    protected void onCreate(Bundle opgeslagen) {
        super.onCreate(opgeslagen);

        // Eerste start: eerst het serveradres laten invullen
        if (Instellingen.server(this) == null) {
            startActivity(new Intent(this, ServerActivity.class));
            finish();
            return;
        }

        setContentView(R.layout.activity_main);
        Randen.toepassen(this, findViewById(R.id.wortel));

        web = findViewById(R.id.web);
        voortgang = findViewById(R.id.voortgang);
        fout = findViewById(R.id.fout);
        foutTekst = findViewById(R.id.fout_tekst);
        findViewById(R.id.knop_opnieuw).setOnClickListener(v -> herladen());
        findViewById(R.id.knop_server).setOnClickListener(
                v -> startActivity(new Intent(this, ServerActivity.class)));

        instellen();
        terugknopInstellen();

        // Na bijv. het wisselen van licht/donker: dezelfde pagina terug, anders de startpagina
        if (opgeslagen != null && web.restoreState(opgeslagen) != null) {
            geladenServer = Instellingen.server(this);
        } else {
            laden();
        }
    }

    @SuppressLint("SetJavaScriptEnabled") // de website heeft JavaScript nodig (code-raster, menu)
    private void instellen() {
        WebSettings instellingen = web.getSettings();
        instellingen.setJavaScriptEnabled(true);
        instellingen.setDomStorageEnabled(true); // localStorage: onthoudt o.a. de weergave per dag/medewerker
        instellingen.setUserAgentString(instellingen.getUserAgentString()
                + " BeveiligingsroosterApp/" + BuildConfig.VERSION_NAME);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        // Inloggen blijft bewaard (de sessiecookie van de server), net als in de browser
        CookieManager koekjes = CookieManager.getInstance();
        koekjes.setAcceptCookie(true);
        koekjes.setAcceptThirdPartyCookies(web, false);

        web.addJavascriptInterface(new Brug(), "AndroidApp");
        web.setWebViewClient(new Bladeren());
        web.setWebChromeClient(new Venster());
        web.setDownloadListener((url, userAgent, inhoud, mime, lengte) ->
                downloaden(url, userAgent, inhoud, mime));
    }

    /** De startpagina van de (nieuwe) server laden. */
    private void laden() {
        geladenServer = Instellingen.server(this);
        wisGeschiedenis = true;
        fout.setVisibility(View.GONE);
        web.loadUrl(geladenServer + "/");
    }

    private void herladen() {
        fout.setVisibility(View.GONE);
        String url = web.getUrl();
        if (url == null || !Instellingen.zelfdeServer(Uri.parse(url), geladenServer)) {
            laden();
        } else {
            web.reload();
        }
    }

    private void toonFout(String tekst) {
        foutTekst.setText(tekst);
        voortgang.setVisibility(View.GONE);
        fout.setVisibility(View.VISIBLE);
    }

    /** Een link naar iets buiten de eigen server: openen in de browser of een andere app. */
    private void openBuiten(Uri link) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, link));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, R.string.geen_app, Toast.LENGTH_SHORT).show();
        }
    }

    /** Downloads (CSV, Excel, back-up, debuglog) via Android, met de inlog van de app. */
    private void downloaden(String url, String userAgent, String inhoud, String mime) {
        Uri link = Uri.parse(url);
        String schema = link.getScheme() == null ? "" : link.getScheme().toLowerCase();
        if (!schema.equals("http") && !schema.equals("https")) {
            Toast.makeText(this, R.string.download_mislukt, Toast.LENGTH_LONG).show();
            return;
        }
        String naam = URLUtil.guessFileName(url, inhoud, mime);
        try {
            DownloadManager.Request aanvraag = new DownloadManager.Request(link);
            String koekje = CookieManager.getInstance().getCookie(url);
            if (koekje != null) {
                aanvraag.addRequestHeader("Cookie", koekje); // anders ziet de server je niet als ingelogd
            }
            aanvraag.addRequestHeader("User-Agent", userAgent);
            aanvraag.setMimeType(mime);
            aanvraag.setTitle(naam);
            aanvraag.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            aanvraag.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, naam);
            DownloadManager downloads = getSystemService(DownloadManager.class);
            downloads.enqueue(aanvraag);
            Toast.makeText(this, getString(R.string.download_gestart, naam), Toast.LENGTH_SHORT).show();
        } catch (RuntimeException e) {
            Toast.makeText(this, R.string.download_mislukt, Toast.LENGTH_LONG).show();
        }
    }

    // ---------- Terugknop: eerst terug in de website, daarna de app sluiten ----------

    private void terugknopInstellen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::terug);
        }
    }

    @SuppressWarnings("deprecation") // tot en met Android 12; daarna via terugknopInstellen
    @Override
    public void onBackPressed() {
        terug();
    }

    private void terug() {
        if (fout.getVisibility() != View.VISIBLE && web.canGoBack()) {
            web.goBack();
        } else {
            finish();
        }
    }

    // ---------- Levenscyclus ----------

    @Override
    protected void onResume() {
        super.onResume();
        if (web == null) {
            return;
        }
        web.onResume();
        // Serveradres gewijzigd (via "Server wijzigen")? Dan de nieuwe server laden.
        String server = Instellingen.server(this);
        if (server != null && !server.equals(geladenServer)) {
            laden();
        }
    }

    @Override
    protected void onPause() {
        if (web != null) {
            web.onPause();
            CookieManager.getInstance().flush(); // inlog direct bewaren
        }
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle uit) {
        super.onSaveInstanceState(uit);
        if (web != null) {
            web.saveState(uit);
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }

    @Override
    protected void onActivityResult(int verzoek, int resultaat, Intent gegevens) {
        super.onActivityResult(verzoek, resultaat, gegevens);
        if (verzoek != KIES_BESTAND || bestandTerug == null) {
            return;
        }
        Uri[] gekozen = null;
        if (resultaat == RESULT_OK && gegevens != null) {
            ClipData meerdere = gegevens.getClipData();
            if (meerdere != null) {
                gekozen = new Uri[meerdere.getItemCount()];
                for (int i = 0; i < gekozen.length; i++) {
                    gekozen[i] = meerdere.getItemAt(i).getUri();
                }
            } else if (gegevens.getData() != null) {
                gekozen = new Uri[] {gegevens.getData()};
            }
        }
        bestandTerug.onReceiveValue(gekozen); // null = geannuleerd
        bestandTerug = null;
    }

    // ---------- WebView: navigatie en fouten ----------

    private class Bladeren extends WebViewClient {

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest aanvraag) {
            Uri link = aanvraag.getUrl();
            if (Instellingen.zelfdeServer(link, geladenServer)) {
                return false; // eigen server: in de app
            }
            openBuiten(link); // bijv. Google Agenda, webcal:, mailto:
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap icoon) {
            voortgang.setVisibility(View.VISIBLE);
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            voortgang.setVisibility(View.GONE);
            if (wisGeschiedenis) {
                view.clearHistory();
                wisGeschiedenis = false;
            }
            view.evaluateJavascript(AFDRUK_SCRIPT, null);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest aanvraag, WebResourceError fout) {
            if (aanvraag.isForMainFrame()) {
                toonFout(fout.getDescription().toString());
            }
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError fout) {
            handler.cancel(); // nooit een ongeldig certificaat accepteren
            toonFout(getString(R.string.fout_certificaat, certificaatReden(fout)));
        }
    }

    private static String certificaatReden(SslError fout) {
        switch (fout.getPrimaryError()) {
            case SslError.SSL_EXPIRED:
                return "verlopen";
            case SslError.SSL_IDMISMATCH:
                return "hoort bij een ander adres";
            case SslError.SSL_UNTRUSTED:
                return "niet vertrouwd of zelf ondertekend";
            case SslError.SSL_NOTYETVALID:
                return "nog niet geldig";
            default:
                return "ongeldig";
        }
    }

    // ---------- WebView: laadbalk en bestand kiezen ----------

    private class Venster extends WebChromeClient {

        @Override
        public void onProgressChanged(WebView view, int procent) {
            voortgang.setProgress(procent);
            voortgang.setVisibility(procent < 100 ? View.VISIBLE : View.GONE);
        }

        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> terug,
                                         FileChooserParams keuze) {
            if (bestandTerug != null) {
                bestandTerug.onReceiveValue(null); // vorige keuze afbreken
            }
            bestandTerug = terug;
            // Alle bestanden tonen: 'accept=".xlsm,.xlsx"' is geen MIME-type, en de server
            // controleert het bestand toch zelf
            Intent kiezen = new Intent(Intent.ACTION_GET_CONTENT);
            kiezen.addCategory(Intent.CATEGORY_OPENABLE);
            kiezen.setType("*/*");
            if (keuze.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                kiezen.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            }
            try {
                startActivityForResult(Intent.createChooser(kiezen, getString(R.string.kies_bestand)),
                        KIES_BESTAND);
                return true;
            } catch (ActivityNotFoundException e) {
                bestandTerug = null;
                return false;
            }
        }
    }

    // ---------- Brug van de website naar de app (alleen printen) ----------

    private class Brug {

        @JavascriptInterface
        public void afdrukken() {
            runOnUiThread(() -> {
                String naam = getString(R.string.afdruk_naam) + " - " + web.getTitle();
                PrintManager printen = getSystemService(PrintManager.class);
                // Alle printweergaven van de website zijn A4 liggend (style.css, @page)
                PrintAttributes standaard = new PrintAttributes.Builder()
                        .setMediaSize(PrintAttributes.MediaSize.ISO_A4.asLandscape())
                        .build();
                printen.print(naam, web.createPrintDocumentAdapter(naam), standaard);
            });
        }
    }
}
