/* Applies the saved theme before first paint. A file, not an inline script, so the
 * site can run under a Content-Security-Policy without 'unsafe-inline'. */
try { var t = localStorage.getItem("luce-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
