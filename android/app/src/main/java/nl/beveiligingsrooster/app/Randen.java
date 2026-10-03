package nl.beveiligingsrooster.app;

import android.app.Activity;
import android.graphics.Insets;
import android.os.Build;
import android.view.View;
import android.view.WindowInsets;

/**
 * Houdt de inhoud vrij van de statusbalk, de navigatiebalk en het toetsenbord.
 *
 * Vanaf Android 11 tekent de app tot in de randen van het scherm (vanaf Android 15 is dat
 * verplicht). De buitenste laag krijgt dan zoveel opvulling als de balken en het toetsenbord
 * hoog zijn; in die opvulling is de themakleur te zien. Op Android 10 doen de kleuren uit
 * het thema en adjustResize (in het manifest) hetzelfde.
 */
final class Randen {

    private Randen() {
    }

    static void toepassen(Activity activity, View wortel) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return;
        }
        activity.getWindow().setDecorFitsSystemWindows(false);
        wortel.setOnApplyWindowInsetsListener((view, randen) -> {
            Insets r = randen.getInsets(WindowInsets.Type.systemBars()
                    | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
            view.setPadding(r.left, r.top, r.right, r.bottom);
            return WindowInsets.CONSUMED;
        });
    }
}
