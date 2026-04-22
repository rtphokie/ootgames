function updateRefreshLine(refreshMs) {
    const bar = document.getElementById("standings-refresh-bar");
    if (!bar) return;

    const start = Date.now();
    const timer = setInterval(function () {
        const elapsed = Date.now() - start;
        const remainingMs = Math.max(0, refreshMs - elapsed);
        const percent = (remainingMs / refreshMs) * 100;
        bar.style.width = percent.toFixed(2) + "%";
        if (remainingMs <= 0) {
            clearInterval(timer);
        }
    }, 100);
}

(function () {
    const url = new URL(window.location.href);
    const hasTimezone = url.searchParams.has("tz") || url.searchParams.has("timezone");
    if (hasTimezone) return;

    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!browserTimezone) return;

    url.searchParams.set("tz", browserTimezone);
    window.location.replace(url.toString());
}());

window.addEventListener("DOMContentLoaded", function () {
    const refreshMs = 15000;
    updateRefreshLine(refreshMs);
    setTimeout(function () {
        window.location.reload();
    }, refreshMs);
});