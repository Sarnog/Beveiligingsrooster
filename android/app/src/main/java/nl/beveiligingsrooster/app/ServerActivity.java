package nl.beveiligingsrooster.app;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Scherm om het serveradres in te vullen. Verschijnt bij de eerste start, via de knop
 * "Server wijzigen" op het foutscherm en via lang drukken op het app-icoon.
 */
public class ServerActivity extends Activity {

    private EditText adres;
    private TextView melding;
    private TextView httpWaarschuwing;
    private Button knop;

    /** Adres waarvan de controle al mislukte: nog een keer op de knop = toch opslaan. */
    private String mislukt;

    @Override
    protected void onCreate(Bundle opgeslagen) {
        super.onCreate(opgeslagen);
        setContentView(R.layout.activity_server);
        Randen.toepassen(this, findViewById(R.id.wortel));

        adres = findViewById(R.id.adres);
        melding = findViewById(R.id.melding);
        httpWaarschuwing = findViewById(R.id.http_waarschuwing);
        knop = findViewById(R.id.knop_verbinden);

        String huidig = Instellingen.server(this);
        if (huidig != null) {
            adres.setText(huidig);
        }
        werkWaarschuwingBij();

        adres.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                // Ander adres: opnieuw controleren
                mislukt = null;
                melding.setVisibility(View.GONE);
                knop.setText(R.string.server_verbinden);
                werkWaarschuwingBij();
            }
        });
        adres.setOnEditorActionListener((veld, actie, toets) -> {
            verbinden();
            return true;
        });
        knop.setOnClickListener(v -> verbinden());
    }

    /** Waarschuwing tonen als het adres met http:// begint (geen versleuteling). */
    private void werkWaarschuwingBij() {
        String server = Instellingen.normaliseer(adres.getText().toString());
        boolean http = server != null && server.startsWith("http://");
        httpWaarschuwing.setVisibility(http ? View.VISIBLE : View.GONE);
    }

    private void verbinden() {
        String server = Instellingen.normaliseer(adres.getText().toString());
        if (server == null) {
            toonMelding(getString(R.string.server_ongeldig));
            return;
        }
        if (server.equals(mislukt)) {
            opslaanEnOpenen(server); // tweede keer: "Toch opslaan"
            return;
        }
        knop.setEnabled(false);
        knop.setText(R.string.server_bezig);
        melding.setVisibility(View.GONE);

        // Netwerk mag niet op de hoofdthread: even controleren in de achtergrond
        new Thread(() -> {
            String fout = controleer(server);
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) {
                    return;
                }
                knop.setEnabled(true);
                if (fout == null) {
                    opslaanEnOpenen(server);
                } else {
                    mislukt = server;
                    knop.setText(R.string.server_toch_opslaan);
                    toonMelding(getString(R.string.server_onbereikbaar, fout));
                }
            });
        }).start();
    }

    /**
     * Vraagt /health op bij de server. Geeft null als het een Beveiligingsrooster is,
     * anders een korte reden.
     */
    private static String controleer(String server) {
        HttpURLConnection verbinding = null;
        try {
            verbinding = (HttpURLConnection) new URL(server + "/health").openConnection();
            verbinding.setConnectTimeout(8000);
            verbinding.setReadTimeout(8000);
            int code = verbinding.getResponseCode();
            if (code != 200) {
                return "HTTP " + code;
            }
            try (InputStream in = verbinding.getInputStream()) {
                byte[] buffer = new byte[256]; // {"status":"ok"} is klein
                int gelezen = in.read(buffer);
                String tekst = gelezen > 0 ? new String(buffer, 0, gelezen, StandardCharsets.UTF_8) : "";
                return tekst.contains("\"status\"") ? null : "geen Beveiligingsrooster";
            }
        } catch (IOException | IllegalArgumentException e) {
            String reden = e.getMessage();
            return reden != null ? reden : e.getClass().getSimpleName();
        } finally {
            if (verbinding != null) {
                verbinding.disconnect();
            }
        }
    }

    private void toonMelding(String tekst) {
        melding.setText(tekst);
        melding.setVisibility(View.VISIBLE);
    }

    private void opslaanEnOpenen(String server) {
        Instellingen.opslaan(this, server);
        Intent rooster = new Intent(this, MainActivity.class);
        rooster.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(rooster);
        finish();
    }
}
