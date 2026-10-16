/* ÉXTASIS — gráficos (Chart.js) */
window.Charts = (function () {
  const PALETA = ["#2f5f8a", "#6f93b3", "#1e9a5a", "#d49a12", "#d6393f", "#8a63c7", "#2a9d9d", "#d0743c", "#66707d", "#a9c7e0"];
  function base() {
    if (!window.Chart) return false;
    Chart.defaults.color = "#66707d";
    Chart.defaults.borderColor = "#e2e6eb";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.maintainAspectRatio = false;
    return true;
  }
  const moneyTick = (v) => "$ " + new Intl.NumberFormat("es-AR", { notation: "compact" }).format(v);
  const moneyTip = { callbacks: { label: (c) => ` ${c.dataset.label ? c.dataset.label + ": " : ""}${money(c.parsed.y ?? c.parsed.x ?? c.parsed)}` } };

  function barras(id, labels, values, opts = {}) {
    const el = document.getElementById(id); if (!el) return;
    if (!labels.length) { el.parentElement.innerHTML = '<div class="empty">Sin datos todavía</div>'; return; }
    new Chart(el, {
      type: "bar",
      data: { labels, datasets: [{ label: opts.label || "", data: values, backgroundColor: opts.color || PALETA[0], borderRadius: 6, maxBarThickness: 46 }] },
      options: {
        indexAxis: opts.horizontal ? "y" : "x",
        plugins: { legend: { display: false }, tooltip: opts.unidades ? {} : moneyTip },
        scales: opts.horizontal
          ? { x: { ticks: { callback: opts.unidades ? undefined : moneyTick } }, y: { ticks: { autoSkip: false } } }
          : { y: { beginAtZero: true, ticks: { callback: opts.unidades ? undefined : moneyTick } } },
      },
    });
  }
  function dona(id, labels, values, unidades) {
    const el = document.getElementById(id); if (!el) return;
    if (!labels.length) { el.parentElement.innerHTML = '<div class="empty">Sin datos todavía</div>'; return; }
    new Chart(el, {
      type: "doughnut",
      data: { labels, datasets: [{ data: values, backgroundColor: PALETA, borderColor: "#ffffff", borderWidth: 2 }] },
      options: { cutout: "62%", plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => ` ${c.label}: ${unidades ? c.parsed + " u." : money(c.parsed)}` } } } },
    });
  }
  function lineas(id, labels, series) {
    const el = document.getElementById(id); if (!el) return;
    new Chart(el, {
      type: "line",
      data: { labels, datasets: series.map((s, i) => ({ label: s.label, data: s.data, borderColor: s.color || PALETA[i],
        backgroundColor: (s.color || PALETA[i]) + "22", fill: i === 0, tension: .3, pointRadius: 3 })) },
      options: { plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } }, tooltip: moneyTip },
        scales: { y: { ticks: { callback: moneyTick } } } },
    });
  }
  async function dashboard(url) {
    if (!base()) return;
    let d;
    try { d = await api(url); } catch (e) { return; }
    barras("ch-7", d.ultimos7.labels, d.ultimos7.values);
    dona("ch-mp", d.metodos.labels, d.metodos.values);
    dona("ch-cat", d.categorias.labels, d.categorias.values);
    barras("ch-top", d.top.labels, d.top.values, { horizontal: true, unidades: true, color: PALETA[1] });
    if (d.locales) barras("ch-loc", d.locales.labels, d.locales.values, { color: PALETA[2] });
    if (d.ganancia) lineas("ch-gan", d.ganancia.labels, [{ label: "Ventas", data: d.ganancia.ventas }, { label: "Ganancia", data: d.ganancia.ganancia, color: "#1e9a5a" }]);
    if (d.stock) barras("ch-stock", d.stock.labels, d.stock.values, { unidades: true, color: PALETA[3] });
  }
  return { base, barras, dona, lineas, dashboard, PALETA };
})();
