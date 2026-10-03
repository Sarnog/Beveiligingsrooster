package nl.beveiligingsrooster.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;

/** Het serveradres: opslaan, lezen en controleren. */
final class Instellingen {

    private static final String BESTAND = "instellingen";
    private static final String SERVER = "server";

    private Instellingen() {
    }

    /** Het opgeslagen serveradres, of null als het nog niet is ingesteld. */
    static String server(Context context) {
        return voorkeuren(context).getString(SERVER, null);
    }

    static void opslaan(Context context, String server) {
        voorkeuren(context).edit().putString(SERVER, server).apply();
    }

    private static SharedPreferences voorkeuren(Context context) {
        return context.getSharedPreferences(BESTAND, Context.MODE_PRIVATE);
    }

    /**
     * Maakt van wat de gebruiker typt een net adres, bijvoorbeeld
     * "rooster.voorbeeld.nl/" wordt "https://rooster.voorbeeld.nl".
     * Geeft null bij een ongeldig adres.
     */
    static String normaliseer(String invoer) {
        String tekst = invoer == null ? "" : invoer.trim();
        if (tekst.isEmpty()) {
            return null;
        }
        if (!tekst.contains("://")) {
            tekst = "https://" + tekst; // zonder schema: veilig standaard https
        }
        Uri uri = Uri.parse(tekst);
        String schema = uri.getScheme();
        if (schema == null) {
            return null;
        }
        schema = schema.toLowerCase();
        if (!schema.equals("http") && !schema.equals("https")) {
            return null;
        }
        if (uri.getHost() == null || uri.getHost().isEmpty() || uri.getUserInfo() != null) {
            return null; // geen host, of "naam:wachtwoord@" in het adres
        }
        String pad = uri.getEncodedPath() == null ? "" : uri.getEncodedPath();
        while (pad.endsWith("/")) {
            pad = pad.substring(0, pad.length() - 1); // geen slash aan het eind
        }
        return schema + "://" + uri.getEncodedAuthority() + pad;
    }

    /**
     * Hoort deze link bij de eigen server? Dan blijft hij in de app; anders opent hij
     * in de browser of een andere app. Alleen de host telt, zodat een doorverwijzing
     * van http naar https op dezelfde server gewoon in de app blijft.
     */
    static boolean zelfdeServer(Uri link, String server) {
        if (link == null || server == null || link.getHost() == null) {
            return false;
        }
        String schema = link.getScheme() == null ? "" : link.getScheme().toLowerCase();
        if (!schema.equals("http") && !schema.equals("https")) {
            return false;
        }
        return link.getHost().equalsIgnoreCase(Uri.parse(server).getHost());
    }
}
