/* Lista editable de renglones (transferencias, solicitudes, compras) */
window.Lineas = function (cfg) {
  // cfg: {tbody, hidden, conPrecio, maxStock (bool), onChange}
  const items = [];
  function render() {
    cfg.tbody.innerHTML = items.length ? items.map((it, i) => `
      <tr>
        <td class="cell-main">${esc(it.producto)}<div class="muted" style="font-size:.8rem">T. ${esc(it.talle)} · ${esc(it.color)} · ${esc(it.codigo_barras)}</div></td>
        ${cfg.maxStock ? `<td class="num">${it.stock}</td>` : ""}
        <td class="num"><input type="number" min="1" ${cfg.maxStock ? `max="${it.stock}"` : ""} value="${it.cantidad}" data-i="${i}" data-f="cantidad" style="width:90px;min-height:36px"></td>
        ${cfg.conPrecio ? `<td class="num"><input type="number" min="0" step="0.01" value="${it.precio}" data-i="${i}" data-f="precio" style="width:120px;min-height:36px"></td>
          <td class="num">${money(it.cantidad * it.precio)}</td>` : ""}
        <td class="text-right"><button type="button" class="btn btn-sm btn-ghost" data-del="${i}" title="Quitar"><i data-lucide="trash-2"></i></button></td>
      </tr>`).join("") : `<tr><td colspan="6" class="muted">Todavía no agregaste productos.</td></tr>`;
    sync(); icons();
  }
  function sync() {
    cfg.hidden.value = JSON.stringify(items.map((i) => ({ variante_id: i.variante_id, cantidad: i.cantidad, precio: i.precio })));
    if (cfg.onChange) cfg.onChange(items);
  }
  cfg.tbody.addEventListener("input", (e) => {
    const el = e.target; if (!el.dataset.f) return;
    const it = items[+el.dataset.i];
    it[el.dataset.f] = el.dataset.f === "cantidad" ? Math.max(0, parseInt(el.value || 0)) : Math.max(0, parseFloat(el.value || 0));
    if (cfg.conPrecio) { const sub = el.closest("tr").children[cfg.maxStock ? 4 : 3]; if (sub) sub.textContent = money(it.cantidad * it.precio); }
    sync();
  });
  cfg.tbody.addEventListener("click", (e) => { const b = e.target.closest("[data-del]"); if (b) { items.splice(+b.dataset.del, 1); render(); } });
  render();
  return {
    agregar(v) {
      const ex = items.find((i) => i.variante_id === v.variante_id);
      if (ex) { ex.cantidad += 1; }
      else { items.push({ ...v, cantidad: 1, precio: cfg.precioVenta ? v.precio : (v.costo ?? v.precio ?? 0) }); }
      if (cfg.maxStock && (ex || items[items.length - 1]).cantidad > v.stock) { toast(`Atención: el origen tiene ${v.stock} u. disponibles`, false); }
      beep(true); render();
    },
    items, render,
  };
};
