/* ÉXTASIS — utilidades comunes */
(function () {
  "use strict";

  // ---------------- helpers globales ----------------
  const fmt = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  window.money = (n) => "$ " + fmt.format(Math.round((Number(n) || 0) * 100) / 100);
  window.csrfToken = () => document.querySelector('meta[name="csrf-token"]').content;
  window.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  window.api = async function (url, opts = {}) {
    const o = Object.assign({ headers: {} }, opts);
    o.headers["X-CSRFToken"] = csrfToken();
    o.headers["X-Requested-With"] = "fetch";
    if (o.json !== undefined) {
      o.method = o.method || "POST";
      o.headers["Content-Type"] = "application/json";
      o.body = JSON.stringify(o.json);
      delete o.json;
    }
    const r = await fetch(url, o);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); }
    if (!r.ok) throw new Error((data && data.error) || "Error de comunicación con el servidor");
    return data;
  };

  window.toast = function (msg, ok = true) {
    let area = document.querySelector(".toast-area");
    if (!area) { area = document.createElement("div"); area.className = "toast-area"; document.body.appendChild(area); }
    const t = document.createElement("div");
    t.className = "toast " + (ok ? "ok" : "err");
    t.textContent = msg;
    area.appendChild(t);
    setTimeout(() => t.remove(), ok ? 2200 : 4000);
  };

  window.beep = function (ok = true) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = ok ? 1200 : 300; o.connect(g); g.connect(ctx.destination);
      g.gain.value = 0.08; o.start(); setTimeout(() => { o.stop(); ctx.close(); }, ok ? 90 : 250);
    } catch (e) { /* sin audio */ }
  };

  window.icons = () => { if (window.lucide) window.lucide.createIcons(); };

  // ---------------- modal ----------------
  window.Modal = {
    open(id) { const m = document.getElementById(id); if (m) { m.classList.add("show"); const f = m.querySelector("[autofocus]"); if (f) setTimeout(() => f.focus(), 50); } },
    close(id) { const m = document.getElementById(id); if (m) m.classList.remove("show"); },
  };
  document.addEventListener("click", (e) => {
    const op = e.target.closest("[data-modal]");
    if (op) { e.preventDefault(); Modal.open(op.dataset.modal); }
    const cl = e.target.closest("[data-close]");
    if (cl) { e.preventDefault(); cl.closest(".modal").classList.remove("show"); }
    if (e.target.classList && e.target.classList.contains("modal")) e.target.classList.remove("show");
  });

  // ---------------- escáner por cámara ----------------
  window.Escaner = {
    _inst: null,
    async abrir(onCode) {
      if (!window.Html5Qrcode) { toast("No se pudo cargar el lector de cámara (revisá la conexión).", false); return; }
      if (!window.isSecureContext) {
        toast("La cámara requiere HTTPS o localhost. Activá USAR_HTTPS=1 en el .env para usarla desde el celular.", false);
        return;
      }
      Modal.open("modal-scanner");
      const F = window.Html5QrcodeSupportedFormats;
      this._inst = new Html5Qrcode("scanner-region", {
        formatsToSupport: [F.EAN_13, F.EAN_8, F.CODE_128, F.CODE_39, F.UPC_A, F.UPC_E, F.QR_CODE, F.ITF],
        verbose: false,
      });
      let leido = false;
      try {
        await this._inst.start({ facingMode: "environment" }, { fps: 12, qrbox: { width: 280, height: 140 } },
          (text) => { if (leido) return; leido = true; beep(true); this.cerrar(); onCode(text.trim()); });
      } catch (err) {
        toast("No se pudo acceder a la cámara: " + err, false);
        this.cerrar();
      }
    },
    async cerrar() {
      Modal.close("modal-scanner");
      if (this._inst) { try { await this._inst.stop(); await this._inst.clear(); } catch (e) { } this._inst = null; }
    },
  };

  // ---------------- buscador de variantes reutilizable ----------------
  // new VariantePicker({input, results, onPick, ubicacion: () => id, mostrarStock: true})
  window.VariantePicker = function (cfg) {
    const input = cfg.input, box = cfg.results;
    let timer = null, ultimo = [];
    const ub = () => (cfg.ubicacion ? cfg.ubicacion() : "") || "";
    function render(items) {
      ultimo = items;
      if (!items.length) { box.innerHTML = input.value.trim() ? '<div class="muted" style="padding:.5rem">Sin resultados</div>' : ""; return; }
      box.innerHTML = items.map((v, i) => `
        <div class="result ${cfg.mostrarStock !== false && v.stock <= 0 ? "sin-stock" : ""}" data-i="${i}">
          ${v.imagen ? `<img class="thumb" src="${esc(v.imagen)}" alt="">` : `<div class="thumb"><i data-lucide="shirt"></i></div>`}
          <div class="info"><div class="name">${esc(v.producto)}</div>
            <div class="meta">T. ${esc(v.talle)} · ${esc(v.color)} · ${esc(v.codigo_barras)}</div></div>
          <div class="text-right"><div class="price">${money(v.precio)}</div>
            ${cfg.mostrarStock !== false ? `<div class="meta">Stock: <b>${v.stock}</b></div>` : ""}</div>
        </div>`).join("");
      icons();
    }
    async function buscar(q) {
      if (!q) { render([]); return; }
      try { render(await api(`/api/variantes/buscar?q=${encodeURIComponent(q)}&ubicacion_id=${ub()}`)); }
      catch (e) { toast(e.message, false); }
    }
    async function porCodigo(code) {
      const items = await api(`/api/variantes/codigo?codigo=${encodeURIComponent(code)}&ubicacion_id=${ub()}`);
      if (items.length === 1) { pick(items[0]); return true; }
      if (items.length > 1) { render(items); toast("Elegí talle y color", true); return true; }
      return false;
    }
    function pick(v) { cfg.onPick(v); input.value = ""; render([]); input.focus(); }
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => buscar(input.value.trim()), 250); });
    input.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        e.preventDefault(); clearTimeout(timer);
        const q = input.value.trim(); if (!q) return;
        try {
          if (!(await porCodigo(q))) { await buscar(q); if (!ultimo.length) { beep(false); toast("Producto no encontrado", false); } }
        } catch (err) { toast(err.message, false); }
      } else if (e.key === "Escape") { render([]); }
    });
    box.addEventListener("click", (e) => { const r = e.target.closest(".result"); if (r) pick(ultimo[+r.dataset.i]); });
    document.addEventListener("click", (e) => { if (!box.contains(e.target) && e.target !== input && cfg.cerrarAlClick !== false) render([]); });
    return { porCodigo: async (c) => { try { if (!(await porCodigo(c))) { beep(false); toast("Código no encontrado: " + c, false); } } catch (e) { toast(e.message, false); } }, render };
  };

  // ---------------- inicialización ----------------
  document.addEventListener("DOMContentLoaded", () => {
    // sidebar móvil
    const sb = document.querySelector(".sidebar"), bd = document.querySelector(".backdrop");
    document.querySelectorAll(".menu-btn").forEach((b) => b.addEventListener("click", () => { sb.classList.toggle("open"); bd.classList.toggle("show"); }));
    if (bd) bd.addEventListener("click", () => { sb.classList.remove("open"); bd.classList.remove("show"); });

    // tablas -> tarjetas en celular (data-label automático)
    document.querySelectorAll("table.cards").forEach((t) => {
      const heads = [...t.querySelectorAll("thead th")].map((th) => th.textContent.trim());
      t.querySelectorAll("tbody tr, tfoot tr").forEach((tr) => {
        [...tr.children].forEach((td, i) => { if (!td.hasAttribute("data-label")) td.setAttribute("data-label", heads[i] || ""); });
      });
    });

    // filas clickeables
    document.querySelectorAll("tr[data-href]").forEach((tr) => {
      tr.classList.add("row-link");
      tr.addEventListener("click", (e) => { if (!e.target.closest("a,button,input,form,select")) location.href = tr.dataset.href; });
    });

    // confirmaciones
    document.querySelectorAll("form[data-confirm]").forEach((f) => f.addEventListener("submit", (e) => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));

    // flashes
    document.querySelectorAll(".flash .x").forEach((x) => x.addEventListener("click", () => x.parentElement.remove()));

    // evitar doble envío
    document.querySelectorAll("form:not([data-multi])").forEach((f) => f.addEventListener("submit", () => {
      setTimeout(() => f.querySelectorAll("button[type=submit]").forEach((b) => (b.disabled = true)), 0);
      setTimeout(() => f.querySelectorAll("button[type=submit]").forEach((b) => (b.disabled = false)), 4000);
    }));

    icons();
  });
})();
