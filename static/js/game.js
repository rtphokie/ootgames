function updateRefreshLine(refreshMs) {
    const bar = document.getElementById("refresh-line-bar");
    if (!bar) {
        return;
    }
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

window.addEventListener("DOMContentLoaded", function () {
    let refreshMs = 5000;
    const gamePk = {{ game_pk | tojson }};
    const stateToken = {{ state_token | tojson }};
    const gameStatus = ({{ status | tojson }} || "").toLowerCase();
    const storageKey = "mlb_state_" + String(gamePk);
    const isFinal = gameStatus.startsWith("final")
        || gameStatus.startsWith("game over")
        || gameStatus.startsWith("completed");

    if (isFinal) {
        const refreshWrap = document.querySelector(".refresh-wrap");
        if (refreshWrap) {
            refreshWrap.style.display = "none";
        }
        return;
    }

    try {
        const previousState = localStorage.getItem(storageKey);
        if (previousState === stateToken) {
            refreshMs = 10000;
        }
        localStorage.setItem(storageKey, stateToken);
    } catch (err) {
        // If storage is unavailable, keep the default refresh.
    }

    updateRefreshLine(refreshMs);
    setTimeout(function () {
        window.location.reload();
    }, refreshMs);
});