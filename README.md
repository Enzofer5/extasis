# ÉXTASIS — Sistema de Gestión de Indumentaria

Aplicación web (Flask + MySQL) para administrar el **Depósito Central** y los locales **Concepción** y **Segundo Local**: stock por ubicación y variante, transferencias, solicitudes, compras, POS con código de barras, cajas, cuentas corrientes, devoluciones, empleados, gastos, reportes y auditoría. Se adapta a celular.

---

## 1. Cómo correrlo

1. Abrí la carpeta en VS Code y abrí **`app.py`**.
2. Apretá **▶ (Run Python File)**.
   - La primera vez instala solo las dependencias (`requirements.txt`).
   - Si la base `extasis` no existe, la crea con `database/schema.sql`.
3. Entrá a **http://localhost:5000**.
4. **Desde el celular** (misma red Wi-Fi): usá la dirección `http://IP-DE-LA-PC:5000` que aparece en la terminal.
   Si Windows pregunta por el Firewall, permití el acceso en redes privadas.

### Credenciales de prueba (se obliga a cambiarlas en el primer ingreso)

| Usuario      | Contraseña        | Rol                          |
|--------------|-------------------|------------------------------|
| `admin`      | `Admin2026!`      | Dueño / Administrador        |
| `concepcion` | `Concepcion2026!` | Usuario del Local Concepción |
| `local2`     | `Local2-2026!`    | Usuario del Segundo Local    |

### Configuración (`config.env` o `.env`)

Los datos de conexión están en **`config.env`** (si creás un `.env`, tiene prioridad).

| Variable | Uso |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Conexión MySQL (por defecto el usuario `extasis_app`, sólo con permisos sobre la base `extasis`) |
| `SECRET_KEY` | Firma de sesiones y CSRF. Cambiala si publicás el sistema |
| `PORT` | Puerto (5000) |
| `USAR_HTTPS` | `1` = HTTPS con certificado autofirmado. **Necesario para escanear con la cámara del celular** (los navegadores sólo dan acceso a la cámara en HTTPS o en localhost). El navegador mostrará una advertencia la primera vez: aceptala |

---

## 2. Arquitectura

Arquitectura por capas (MVC):

```
Navegador (HTML + CSS + JS, Chart.js, lector de códigos)
      │  formularios / fetch JSON (con token CSRF)
      ▼
routes/      Controladores (Blueprints): validan entrada, permisos y alcance por local
      │
services/    Reglas de negocio transaccionales: stock, ventas, cajas, cuentas corrientes, reportes
      │
models/      Repositorios: consultas parametrizadas por entidad
      │
db.py        Pool de conexiones MySQL + transacciones (commit / rollback)
      ▼
MySQL 8 (InnoDB, utf8mb4)
```

> **Por qué `extasis/` y no `app/`:** el punto de entrada se llama `app.py` (para correrlo con ▶ en VS Code).
> Si el paquete también se llamara `app/`, Python confundiría ambos nombres. Por eso el paquete se llama `extasis/`.

### Estructura de carpetas

```
Extasis/
├── app.py                  ← ejecutar con ▶
├── requirements.txt
├── config.env / .env.example
├── database/
│   ├── schema.sql          ← tablas, vistas, índices y datos iniciales
│   └── crear_usuario_app.sql
└── extasis/
    ├── __init__.py         ← fábrica de la app, seguridad, errores
    ├── config.py · db.py · setup_db.py
    ├── models/             ← productos, ubicaciones, catálogos, configuración
    ├── services/           ← stock, ventas, caja, cuentas corrientes, reportes, alertas
    ├── routes/             ← un blueprint por módulo (22 módulos)
    ├── utils/              ← auth/permisos, auditoría, helpers
    ├── templates/          ← vistas Jinja por módulo
    └── static/             ← css, js (pos, gráficos), vendor (librerías locales), img, uploads
```

Las librerías de JavaScript (Chart.js, lector de códigos, generador de códigos de barras y de PDF, íconos) están **dentro del proyecto** (`static/vendor`): el sistema funciona aunque se corte internet.

---

## 3. Base de datos

Normalizada (3FN) con PK, FK, UNIQUE, NOT NULL, CHECK e índices.

* **Seguridad:** `roles`, `permisos`, `rol_permisos`, `usuarios`
* **Ubicaciones:** `ubicaciones` (tipo `DEPOSITO` o `LOCAL`) + vista `locales`.
  Depósitos y locales están en una sola tabla, así agregar otro local u otro depósito es sólo un registro nuevo.
* **Catálogo:** `categorias` (con subcategorías por `parent_id`), `marcas`, `temporadas`, `talles`, `colores`, `productos`, `variantes_producto`
* **Stock:** `stock` (variante × ubicación), `movimientos_stock`
* **Logística:** `solicitudes_stock`, `detalle_solicitudes`, `transferencias`, `detalle_transferencias`
* **Compras:** `proveedores`, `compras`, `detalle_compras`, `pagos` (pagos a proveedores)
* **Ventas:** `ventas`, `detalle_ventas`, `devoluciones`, `detalle_devoluciones`, `metodos_pago`
* **Caja:** `cajas`, `movimientos_caja`
* **Clientes:** `clientes`, `cuentas_corrientes`, `movimientos_cuenta_corriente` + vista `v_saldos_cc`
* **Personal y gastos:** `empleados`, `pagos_empleados`, `gastos`, `categorias_gasto`
* **Control:** `inventarios`, `detalle_inventarios`, `auditoria`, `configuracion`

Relaciones principales:

```
productos 1─N variantes_producto (producto + talle + color, cada una con su código de barras)
variantes_producto 1─N stock N─1 ubicaciones
ventas N─1 cajas N─1 ubicaciones (locales)
ventas 1─N detalle_ventas N─1 variantes_producto
clientes 1─1 cuentas_corrientes 1─N movimientos_cuenta_corriente
```

En `detalle_ventas` se guardan el precio y el costo **del momento de la venta**. Es un dato histórico, no una duplicación: si mañana cambia el precio, los reportes de ganancia no se alteran.

---

## 4. Cómo funciona

### Stock por ubicación
El stock no es un número global: cada fila de `stock` es **variante + ubicación + cantidad** (más su stock mínimo para alertas).
Toda modificación pasa por `services/stock_service.mover()`, que bloquea la fila (`SELECT … FOR UPDATE`), impide que el stock quede negativo y deja un registro en `movimientos_stock` (fecha, tipo, origen, destino, usuario y motivo).
El stock total de un producto es la suma de todas las ubicaciones.

### Transferencias
`Depósito −10  →  Local +10`, en una única transacción: si algo falla, no se mueve nada.
* **Transferencia directa** (dueño): descuenta del origen y suma al destino en el mismo momento.
* **Solicitud del local:** Pendiente → Aprobada → Preparando → **Enviada** (descuenta del depósito; la mercadería queda *en tránsito*) → **Recibida** (el local confirma la llegada y recién ahí se suma a su stock). También puede quedar Rechazada.

### Cajas
* Una caja por local; la base de datos **impide tener dos cajas abiertas** en el mismo local.
* Sin caja abierta no se puede vender.
* Ventas, cobros de cuenta corriente, ingresos, retiros, gastos y devoluciones generan movimientos de caja automáticamente.
* Cierre: `Monto inicial + ventas en efectivo + cobros en efectivo + ingresos − retiros − gastos − devoluciones = EFECTIVO ESPERADO`. Se ingresa el EFECTIVO REAL y se guarda la diferencia.

### POS y código de barras
1. Lector USB: funciona como un teclado que escribe el código y Enter. El campo de búsqueda queda siempre enfocado.
2. Cámara del celular o de la PC: botón 📷 (requiere HTTPS, ver `USAR_HTTPS`).
3. Búsqueda manual por código o por nombre.

Código → buscar variante → verificar stock **del local** → agregar al carrito. Si no hay stock aparece *"Producto sin stock en este local."*; se puede habilitar la venta sin stock en Configuración.
El servidor vuelve a validar precios y stock al finalizar la venta. El precio nunca se toma del navegador, salvo que el que vende sea el dueño.
Cada variante recibe un código **EAN-13** interno (prefijo `200`, reservado para uso interno de comercios). Se puede reemplazar por el código del fabricante y se imprimen etiquetas desde la ficha del producto.

### Ticket
Diseño para impresora térmica de 80 mm: Imprimir, PDF y reimpresión desde el historial de ventas.

### Permisos
* **Dueño:** acceso total.
* **Usuario de local:** caja, POS, ventas, clientes, devoluciones, solicitudes e inventario **sólo de su local**. No ve el stock ni las ventas del otro local, no modifica precios ni el depósito y no accede a finanzas, usuarios ni configuración. Esto se controla en el servidor, no sólo ocultando botones.

### Seguridad
Contraseñas con hash (scrypt), cambio de contraseña obligatorio en el primer ingreso, sesiones con cookies `HttpOnly`/`SameSite`, protección CSRF en todos los formularios y llamadas, consultas 100 % parametrizadas (contra SQL Injection), escape automático de Jinja (contra XSS), bloqueo temporal por intentos fallidos de ingreso, variables sensibles en `.env` y auditoría de cada acción.

---

## 5. Preparado para crecer
Se pueden sumar más locales y depósitos (son filas en `ubicaciones`), más usuarios, categorías y productos. El método de pago Mercado Pago ya está separado, y la capa de servicios permite agregar después facturación electrónica, e-commerce, venta online y reservas (por ejemplo, una ubicación virtual "Online" con su propio stock).
