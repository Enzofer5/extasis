/* ÉXTASIS — Punto de venta */
(function () {
  "use strict";
  const CFG = window.POS_CFG;
  const KEY = "extasis_pos_" + CFG.ubicacion;
  const $ = (id) => document.getElementById(id);

  let cart = [];       // {variante_id, producto, talle, color, codigo_barras, precio, stock, cantidad}
  let cliente = null;  // {id, nombre, apellido, dni, saldo}
  let entidadSel = null, planSel = null; // tarjeta / crédito y plan de cuotas elegidos

  // -------- persistencia del carrito (por si se recarga la página) --------
  function guardar() { try { sessionStorage.setItem(KEY, JSON.stringify({ cart, cliente })); } catch (e) { } }
  function cargar() {
    try { const d = JSON.parse(sessionStorage.getItem(KEY) || "null"); if (d) { cart = d.cart || []; cliente = d.cliente || null; } } catch (e) { }
  }

  // -------- carrito --------
  function agregar(v) {
    const ex = cart.find((i) => i.variante_id === v.variante_id);
    const actual = ex ? ex.cantidad : 0;
    if (!CFG.sinStock && v.stock <= actual) {
      beep(false);
      toast(v.stock <= 0 ? "Producto sin stock en este local." : `Sólo hay ${v.stock} unidad(es) en stock.`, false);
      return;
    }
    if (ex) { ex.cantidad += 1; ex.stock = v.stock; }
    else cart.push({ variante_id: v.variante_id, producto: v.producto, talle: v.talle, color: v.color, codigo_barras: v.codigo_barras,
                     precio: v.precio, stock: v.stock, cantidad: 1 });
    beep(true);
    toast(`+ ${v.producto} T.${v.talle}`);
    render();
  }

  function setCantidad(i, n) {
    const it = cart[i]; if (!it) return;
    n = parseInt(n, 10) || 0;
    if (n <= 0) { cart.splice(i, 1); render(); return; }
    if (!CFG.sinStock && n > it.stock) { toast(`Sólo hay ${it.stock} unidad(es) en stock.`, false); n = it.stock; }
    it.cantidad = n; render();
  }

  function calc() {
    const sub = cart.reduce((a, i) => a + i.precio * i.cantidad, 0);
    const tipo = $("desc-tipo").value, val = Math.max(0, parseFloat($("desc-valor").value || 0));
    let desc = tipo === "porc" ? Math.round(sub * Math.min(val, 100)) / 100 : val;
    if (desc > sub) desc = sub;
    const base = Math.round((sub - desc) * 100) / 100;
    const plan = planActivo();
    const rec = plan ? Math.round(base * plan.interes) / 100 : 0;
    return { sub, desc, rec, plan, total: Math.round((base + rec) * 100) / 100 };
  }

  function render() {
    const rows = $("cart-rows"), list = $("cart-list");
    rows.innerHTML = cart.map((i, idx) => `
      <tr><td><b>${esc(i.producto)}</b><div class="muted" style="font-size:.78rem">${esc(i.color)} · ${esc(i.codigo_barras)}</div></td>
        <td>${esc(i.talle)}</td>
        <td class="center"><div class="qty"><button type="button" data-q="${idx}" data-d="-1">−</button><input type="number" value="${i.cantidad}" data-set="${idx}" inputmode="numeric"><button type="button" data-q="${idx}" data-d="1">+</button></div></td>
        <td class="num">${money(i.precio)}</td><td class="num"><b>${money(i.precio * i.cantidad)}</b></td>
        <td><button class="btn btn-sm btn-ghost" type="button" data-del="${idx}"><i data-lucide="x"></i></button></td></tr>`).join("");
    list.innerHTML = cart.map((i, idx) => `
      <div class="cart-item">
        <div><div class="name">${esc(i.producto)}</div><div class="meta">T. ${esc(i.talle)} · ${esc(i.color)} · ${money(i.precio)} c/u</div></div>
        <div class="sub">${money(i.precio * i.cantidad)}</div>
        <div class="qty"><button type="button" data-q="${idx}" data-d="-1">−</button><input type="number" value="${i.cantidad}" data-set="${idx}" inputmode="numeric"><button type="button" data-q="${idx}" data-d="1">+</button></div>
        <div class="text-right"><button class="btn btn-sm btn-ghost" type="button" data-del="${idx}"><i data-lucide="trash-2"></i>Quitar</button></div>
      </div>`).join("");
    const vacio = cart.length === 0;
    $("cart-empty").style.display = vacio ? "" : "none";
    $("cart-table-wrap").style.visibility = vacio ? "hidden" : "visible";
    $("n-items").textContent = cart.reduce((a, i) => a + i.cantidad, 0);
    const t = calc();
    $("t-sub").textContent = money(t.sub);
    $("t-desc").textContent = "− " + money(t.desc);
    $("t-total").textContent = money(t.total);
    $("l-rec").style.display = t.rec > 0 ? "" : "none";
    if (t.plan) $("t-rec-lbl").textContent = `Interés ${entidadSel.nombre} ${t.plan.cuotas} cuotas (${t.plan.interes}%)`;
    $("t-rec").textContent = "+ " + money(t.rec);
    pintarCuotas(t.total - t.rec);
    vuelto();
    // cliente
    $("cli-sel").style.display = cliente ? "" : "none";
    $("cli-buscar").style.display = cliente ? "none" : "";
    if (cliente) $("cli-nombre").textContent = `${cliente.apellido}, ${cliente.nombre}${cliente.saldo > 0 ? " · debe " + money(cliente.saldo) : ""}`;
    guardar(); icons();
  }

  function metodoSel() { return document.querySelector('input[name="metodo"]:checked'); }
  function opcionesFin() { const m = metodoSel(); return m ? (CFG.financiacion || {})[m.dataset.codigo] : null; }
  function planActivo() { return entidadSel && planSel ? entidadSel.planes.find((p) => p.id === planSel) || null : null; }
  function pintarPlanes() {
    const ops = opcionesFin(), box = $("plan-box");
    if (!ops) { box.style.display = "none"; entidadSel = null; planSel = null; return; }
    box.style.display = "";
    $("plan-titulo").textContent = metodoSel().dataset.codigo === "CREDITO" ? "Tarjeta" : "Crédito";
    $("plan-vacio").style.display = ops.length ? "none" : "";
    if (!entidadSel || !ops.find((e) => e.id === entidadSel.id)) { entidadSel = ops[0] || null; planSel = null; }
    $("plan-entidades").innerHTML = ops.map((e) => `<a href="#" class="chip ${entidadSel && e.id === entidadSel.id ? "on" : ""}" data-ent="${e.id}">${esc(e.nombre)}</a>`).join("");
    if (entidadSel && !planSel) planSel = entidadSel.planes[0].id;
  }
  function pintarCuotas(base) {
    const cont = $("plan-cuotas");
    if (!entidadSel) { cont.innerHTML = ""; return; }
    cont.innerHTML = entidadSel.planes.map((p) => {
      const tot = Math.round(base * (100 + p.interes)) / 100;
      return `<label class="plan-op"><input type="radio" name="plan" value="${p.id}" ${p.id === planSel ? "checked" : ""}>
        <span><b>${p.cuotas} ${p.cuotas === 1 ? "pago" : "cuotas"}</b> de ${money(tot / p.cuotas)}
        <small>${p.interes > 0 ? "+" + p.interes + "% · total " + money(tot) : "sin interés"}</small></span></label>`;
    }).join("");
  }
  $("plan-entidades").addEventListener("click", (e) => {
    const a = e.target.closest("[data-ent]"); if (!a) return; e.preventDefault();
    entidadSel = opcionesFin().find((x) => x.id === +a.dataset.ent); planSel = entidadSel.planes[0].id;
    pintarPlanes(); render();
  });
  $("plan-cuotas").addEventListener("change", (e) => { if (e.target.name === "plan") { planSel = +e.target.value; render(); } });
  function vuelto() {
    const m = metodoSel(); const efectivo = m && m.dataset.codigo === "EFECTIVO";
    $("vuelto-box").style.display = efectivo ? "" : "none";
    const paga = parseFloat($("paga-con").value || 0), total = calc().total;
    $("vuelto").textContent = efectivo && paga > 0 ? (paga >= total ? `Vuelto: ${money(paga - total)}` : `Faltan ${money(total - paga)}`) : "";
  }

  // eventos del carrito
  document.addEventListener("click", (e) => {
    const q = e.target.closest("[data-q]");
    if (q) { const i = +q.dataset.q; setCantidad(i, cart[i].cantidad + +q.dataset.d); return; }
    const d = e.target.closest("[data-del]");
    if (d && (d.closest("#cart-rows") || d.closest("#cart-list"))) { cart.splice(+d.dataset.del, 1); render(); }
  });
  document.addEventListener("change", (e) => { if (e.target.dataset && e.target.dataset.set !== undefined) setCantidad(+e.target.dataset.set, e.target.value); });
  ["desc-tipo", "desc-valor"].forEach((id) => $(id).addEventListener("input", render));
  $("paga-con").addEventListener("input", vuelto);
  document.querySelectorAll('input[name="metodo"]').forEach((r) => r.addEventListener("change", () => { pintarPlanes(); render(); }));
  $("btn-vaciar").addEventListener("click", () => { if (cart.length && confirm("¿Vaciar el carrito?")) { cart = []; render(); } });

  // -------- búsqueda / escaneo de productos --------
  const picker = new VariantePicker({
    input: $("scan"), results: $("res"), ubicacion: () => CFG.ubicacion, onPick: agregar, cerrarAlClick: false,
  });
  $("btn-cam").addEventListener("click", () => Escaner.abrir((code) => picker.porCodigo(code)));
  // mantener el foco en el input para el lector USB (salvo que se esté escribiendo en otro campo)
  document.addEventListener("keydown", (e) => {
    const t = e.target.tagName;
    if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return;
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) $("scan").focus();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "F2") { e.preventDefault(); cobrar(); } });

  // -------- clientes --------
  let ct = null;
  $("cli-q").addEventListener("input", () => {
    clearTimeout(ct);
    ct = setTimeout(async () => {
      const q = $("cli-q").value.trim(); const box = $("cli-res");
      if (!q) { box.innerHTML = ""; return; }
      try {
        const rows = await api("/api/clientes/buscar?q=" + encodeURIComponent(q));
        box.innerHTML = rows.length ? rows.map((c, i) => `<div class="result" data-c="${i}"><div class="info"><div class="name">${esc(c.apellido)}, ${esc(c.nombre)}</div>
          <div class="meta">${c.dni ? "DNI " + esc(c.dni) : ""}${c.saldo > 0 ? " · debe " + money(c.saldo) : ""}</div></div></div>`).join("")
          : '<div class="muted" style="padding:.5rem">Sin resultados</div>';
        box.onclick = (e) => { const r = e.target.closest("[data-c]"); if (r) { cliente = rows[+r.dataset.c]; $("cli-q").value = ""; box.innerHTML = ""; render(); } };
      } catch (err) { toast(err.message, false); }
    }, 250);
  });
  $("cli-quitar").addEventListener("click", () => { cliente = null; render(); });
  $("f-cli").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target).entries());
    try {
      const r = await api("/api/clientes", { json: fd });
      cliente = r.cliente; Modal.close("m-cli"); e.target.reset(); render(); toast("Cliente registrado");
    } catch (err) { toast(err.message, false); }
  });

  // -------- finalizar venta --------
  let enviando = false;
  async function cobrar() {
    if (enviando) return;
    if (!cart.length) { toast("El carrito está vacío.", false); return; }
    const m = metodoSel();
    if (!m) { toast("Seleccioná un método de pago.", false); return; }
    if (m.dataset.codigo === "CTACTE" && !cliente) { toast("Para cuenta corriente seleccioná un cliente.", false); $("cli-q").focus(); return; }
    const t = calc();
    if (opcionesFin() && opcionesFin().length && !t.plan) { toast("Elegí la tarjeta / crédito y las cuotas.", false); return; }
    const detallePlan = t.plan ? `\n${entidadSel.nombre} en ${t.plan.cuotas} ${t.plan.cuotas === 1 ? "pago" : "cuotas"} de ${money(t.total / t.plan.cuotas)}` : "";
    if (!confirm(`¿Confirmar venta por ${money(t.total)}?${detallePlan}`)) return;
    enviando = true; $("btn-cobrar").disabled = true;
    try {
      const r = await api("/api/ventas", { json: {
        ubicacion_id: CFG.ubicacion,
        items: cart.map((i) => ({ variante_id: i.variante_id, cantidad: i.cantidad })),
        descuento_tipo: $("desc-tipo").value, descuento_valor: $("desc-valor").value || 0,
        cliente_id: cliente ? cliente.id : null, metodo_pago_id: m.value, observaciones: $("obs").value,
        plan_id: t.plan ? t.plan.id : null,
      } });
      const paga = parseFloat($("paga-con").value || 0);
      $("ok-num").textContent = "N° " + r.venta_id;
      $("ok-total").textContent = money(t.total);
      $("ok-vuelto").textContent = m.dataset.codigo === "EFECTIVO" && paga > t.total ? "Vuelto: " + money(paga - t.total)
        : (t.plan ? `${entidadSel.nombre}: ${t.plan.cuotas} ${t.plan.cuotas === 1 ? "pago" : "cuotas"} de ${money(t.total / t.plan.cuotas)}` : "");
      $("ok-ticket").href = r.ticket_url + "?auto=1";
      cart = []; cliente = null; $("desc-valor").value = 0; $("paga-con").value = ""; $("obs").value = "";
      render(); Modal.open("m-ok"); beep(true);
    } catch (err) { beep(false); toast(err.message, false); }
    finally { enviando = false; $("btn-cobrar").disabled = false; }
  }
  $("btn-cobrar").addEventListener("click", cobrar);
  $("ok-nueva").addEventListener("click", () => { Modal.close("m-ok"); $("scan").focus(); });

  cargar(); pintarPlanes(); render();
})();
