/* Cadence custom JavaScript */

// Theme management (system/light/dark)
(function() {
    const THEME_KEY = 'cadence-theme';
    const html = document.documentElement;

    function getSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function getStoredTheme() {
        return localStorage.getItem(THEME_KEY);
    }

    function getThemeMode() {
        // Returns 'system', 'light', or 'dark'
        return getStoredTheme() || 'system';
    }

    function setTheme(mode) {
        if (mode === 'system') {
            html.setAttribute('data-theme', getSystemTheme());
            localStorage.removeItem(THEME_KEY);
        } else {
            html.setAttribute('data-theme', mode);
            localStorage.setItem(THEME_KEY, mode);
        }
        updateToggleButton(mode);
    }

    function cycleTheme() {
        // Cycle: system → light → dark → system
        const current = getThemeMode();
        const next = current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system';
        setTheme(next);
    }

    function updateToggleButton(mode) {
        const toggle = document.getElementById('theme-toggle');
        if (!toggle) return;

        // Update button content based on mode
        const icons = {
            system: '\u2699',  // gear
            light: '\u2600',   // sun
            dark: '\u263E'     // moon
        };
        toggle.textContent = icons[mode] || icons.system;
        toggle.setAttribute('title', 'Theme: ' + mode + ' (click to change)');
    }

    // Initialize theme on page load
    function initTheme() {
        const mode = getThemeMode();
        setTheme(mode);
    }

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        if (!getStoredTheme()) {
            setTheme('system');
        }
    });

    // Initialize
    initTheme();

    // Bind toggle button
    document.addEventListener('DOMContentLoaded', function() {
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.addEventListener('click', cycleTheme);
            updateToggleButton(getThemeMode());
        }
    });
})();

// HTMX event handlers
document.addEventListener('htmx:beforeRequest', function(event) {
    // Add loading state
});

document.addEventListener('htmx:afterRequest', function(event) {
    // Remove loading state
});

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach(function(flash) {
        setTimeout(function() {
            flash.style.transition = 'opacity 0.5s';
            flash.style.opacity = '0';
            setTimeout(function() {
                flash.remove();
            }, 500);
        }, 5000);
    });
});

// Send browser timezone with all requests
(function() {
    var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    // Set as HTMX header for AJAX requests
    document.body.setAttribute('hx-headers', JSON.stringify({'X-Timezone': tz}));
    // Set as cookie for full page requests
    document.cookie = 'tz=' + tz + ';path=/;SameSite=Lax';
})();
