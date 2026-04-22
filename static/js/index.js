(function () {
    const url = new URL(window.location.href);
    const hasTimezone = url.searchParams.has("tz") || url.searchParams.has("timezone");
    if (hasTimezone) return;

    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!browserTimezone) return;

    const browserToday = new Intl.DateTimeFormat("en-CA", {
        timeZone: browserTimezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit"
    }).format(new Date());

    url.searchParams.set("tz", browserTimezone);
    if (!url.searchParams.has("date")) {
        url.searchParams.set("date", browserToday);
    }
    window.location.replace(url.toString());
}());

function updateRefreshLine(refreshMs) {
    const bar = document.getElementById("schedule-refresh-bar");
    if (!bar) return;
    const start = Date.now();

    const timer = setInterval(function () {
        const elapsed = Date.now() - start;
        const remaining = Math.max(0, refreshMs - elapsed);
        bar.style.width = ((remaining / refreshMs) * 100).toFixed(2) + "%";
        if (remaining <= 0) clearInterval(timer);
    }, 100);
}
window.addEventListener("DOMContentLoaded", function () {
    const gameCards = Array.from(document.querySelectorAll(".game[data-game-date]"));
    const hasGameUnderway = gameCards.some(function (el) {
        return el.dataset.live === "1";
    });

    const upcomingStarts = gameCards
        .filter(function (el) {
            return el.dataset.notStarted === "1" && Boolean(el.dataset.gameDate);
        })
        .map(function (el) {
            return Date.parse(el.dataset.gameDate);
        })
        .filter(function (ts) {
            return Number.isFinite(ts);
        })
        .sort(function (a, b) {
            return a - b;
        });

    const firstUpcomingStart = upcomingStarts.length ? upcomingStarts[0] : null;
    const firstGameMoreThanMinuteAway =
        firstUpcomingStart === null || (firstUpcomingStart - Date.now()) > 60000;

    const ms = (!hasGameUnderway || firstGameMoreThanMinuteAway) ? 300000 : 15000;
    updateRefreshLine(ms);
    setTimeout(function () { window.location.reload(); }, ms);

    document.querySelectorAll(".game[data-pk]").forEach(function (el) {
        const pk = el.dataset.pk;
        const vs = el.dataset.vs;
        const hs = el.dataset.hs;
        const key = "mlb_score_" + pk;
        const prev = localStorage.getItem(key);
        if (prev !== null && prev !== vs + "|" + hs) {
            const [pv, ph] = prev.split("|").map(Number);
            const cv = Number(vs), ch = Number(hs);
            if (cv > pv || ch > ph) {
                el.classList.add("run-scored");
            }
        }
        localStorage.setItem(key, vs + "|" + hs);
    });

    const detailFrame = document.getElementById("gameview-detail-frame");
    if (detailFrame) {
        document.querySelectorAll(".game[data-pk]").forEach(function (card) {
            card.addEventListener("click", function (event) {
                event.preventDefault();
                const nextSrc = card.dataset.detailUrl;
                if (!nextSrc) return;

                detailFrame.src = nextSrc;

                document.querySelectorAll(".game.selected").forEach(function (selectedCard) {
                    selectedCard.classList.remove("selected");
                });
                card.classList.add("selected");

                const nextUrl = new URL(window.location.href);
                nextUrl.searchParams.set("gamePk", card.dataset.pk || "");
                window.history.replaceState({}, "", nextUrl.toString());
            });
        });
    }
});