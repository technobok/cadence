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

    function setTheme(theme) {
        if (theme === 'system') {
            html.setAttribute('data-theme', getSystemTheme());
            localStorage.removeItem(THEME_KEY);
        } else {
            html.setAttribute('data-theme', theme);
            localStorage.setItem(THEME_KEY, theme);
        }
    }

    function toggleTheme() {
        const current = html.getAttribute('data-theme');
        const next = current === 'light' ? 'dark' : 'light';
        setTheme(next);
    }

    // Initialize theme on page load
    function initTheme() {
        const stored = getStoredTheme();
        if (stored) {
            setTheme(stored);
        } else {
            setTheme('system');
        }
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
            toggle.addEventListener('click', toggleTheme);
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
