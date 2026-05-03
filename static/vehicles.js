// static/vehicles.js - Make all table columns sortable

document.addEventListener("DOMContentLoaded", function () {
    const table = document.querySelector("table");
    if (!table) return;
    const headers = table.querySelectorAll("th");
    const tbody = table.querySelector("tbody");

    function updateSummary() {
        const groups = {};
        tbody.querySelectorAll("tr").forEach(row => {
            if (row.style.display === "none") return;
            const make = row.dataset.make;
            const model = row.dataset.model;
            const trim = row.children[2].innerText.trim().replace(/\bHybrid\b/gi, "").trim() || "—";
            const key = `${make}||${model}`;
            if (!groups[key]) groups[key] = { make, model, total: 0, trims: {} };
            groups[key].total++;
            groups[key].trims[trim] = (groups[key].trims[trim] || 0) + 1;
        });

        const el = document.getElementById("vehicle-summary");
        const entries = Object.values(groups);
        if (entries.length === 0) {
            el.innerHTML = '<span class="summary-empty">No vehicles match the selected filters.</span>';
            return;
        }
        el.innerHTML = entries.map(({ make, model, total, trims }) => {
            const trimHtml = Object.entries(trims)
                .sort((a, b) => b[1] - a[1])
                .map(([trim, n]) => `<span class="summary-trim">${trim}&nbsp;(${n})</span>`)
                .join("");
            return `<div class="summary-item">
                <span class="summary-heading">${make} ${model}</span>
                <span class="summary-total">${total}</span>
                <span class="summary-trims">${trimHtml}</span>
            </div>`;
        }).join("");
    }

    function applyFilters() {
        const checkedVehicles = new Set([...document.querySelectorAll(".vehicle-filter:checked")].map(cb => cb.value));
        const maxPrice = parseFloat((document.getElementById("price-max").value || "").replace(/[^\d.]/g, "")) || Infinity;
        const maxMiles = parseFloat((document.getElementById("miles-max").value || "").replace(/[^\d.]/g, "")) || Infinity;
        const maxDist = parseFloat((document.getElementById("dist-max").value || "").replace(/[^\d.]/g, "")) || Infinity;
        const selectedYears = new Set([...document.querySelectorAll(".year-filter:checked")].map(cb => cb.value));
        const selectedDrivetrains = new Set([...document.querySelectorAll(".drivetrain-filter:checked")].map(cb => cb.value));
        const selectedPowertrains = new Set([...document.querySelectorAll(".powertrain-filter:checked")].map(cb => cb.value));
        tbody.querySelectorAll("tr").forEach(row => {
            const price = parseFloat((row.dataset.price || "").replace(/[^\d.]/g, ""));
            const miles = parseFloat((row.dataset.miles || "").replace(/[^\d.]/g, ""));
            const dist = parseFloat((row.dataset.distance || "").replace(/[^\d.]/g, ""));
            const visible = checkedVehicles.has(row.dataset.vehicle)
                && (selectedYears.size === 0 || selectedYears.has(row.dataset.year))
                && (selectedDrivetrains.size === 0 || selectedDrivetrains.has(row.dataset.drivetrain))
                && (selectedPowertrains.size === 0 || selectedPowertrains.has(row.dataset.powertrain))
                && (isNaN(price) || price <= maxPrice)
                && (isNaN(miles) || miles <= maxMiles)
                && (isNaN(dist) || dist <= maxDist);
            row.style.display = visible ? "" : "none";
        });
        updateSummary();
    }

    document.querySelectorAll(".vehicle-filter").forEach(cb => cb.addEventListener("change", applyFilters));

    document.querySelectorAll(".year-filter").forEach(cb => cb.addEventListener("change", applyFilters));
    document.querySelectorAll(".drivetrain-filter").forEach(cb => cb.addEventListener("change", applyFilters));
    document.querySelectorAll(".powertrain-filter").forEach(cb => cb.addEventListener("change", applyFilters));

    let searchDebounce;
    function onNumericInput() {
        applyFilters();
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(() => document.getElementById("search-form").submit(), 800);
    }

    document.getElementById("price-max").addEventListener("input", onNumericInput);
    document.getElementById("miles-max").addEventListener("input", onNumericInput);
    document.getElementById("dist-max").addEventListener("input", onNumericInput);

    updateSummary();

    headers.forEach((th, idx) => {
        th.style.cursor = "pointer";
        th.title = "Sort by this column";
        th.addEventListener("click", function () {
            sortTableByColumn(table, idx);
        });
    });

    function parseValue(val) {
        // Try to parse as float, fallback to string
        let num = parseFloat(val.replace(/[^\d.-]/g, ""));
        if (!isNaN(num)) return num;
        return val.toLowerCase();
    }

    function sortTableByColumn(table, column) {
        const rows = Array.from(tbody.querySelectorAll("tr"));
        const isAsc = !headers[column].classList.contains("sorted-asc");
        rows.sort((a, b) => {
            let aText = a.children[column].innerText.trim();
            let bText = b.children[column].innerText.trim();
            let aVal = parseValue(aText);
            let bVal = parseValue(bText);
            if (aVal < bVal) return isAsc ? -1 : 1;
            if (aVal > bVal) return isAsc ? 1 : -1;
            return 0;
        });
        // Remove old rows
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        // Add sorted rows
        rows.forEach(row => tbody.appendChild(row));
        // Update header classes
        headers.forEach(h => h.classList.remove("sorted-asc", "sorted-desc"));
        headers[column].classList.add(isAsc ? "sorted-asc" : "sorted-desc");
    }
});
