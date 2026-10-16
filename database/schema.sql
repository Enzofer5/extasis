-- =====================================================================
--  ÉXTASIS — Sistema de Gestión de Indumentaria
--  Esquema MySQL 8 (InnoDB, utf8mb4) normalizado (3FN)
--  Ejecutar completo en MySQL Workbench (Ctrl+Shift+Enter)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS extasis
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE extasis;

SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------
-- SEGURIDAD: roles, permisos, usuarios
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  codigo        VARCHAR(30)  NOT NULL UNIQUE,
  nombre        VARCHAR(60)  NOT NULL,
  descripcion   VARCHAR(255) NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS permisos (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  codigo        VARCHAR(60)  NOT NULL UNIQUE,
  descripcion   VARCHAR(255) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rol_permisos (
  rol_id        INT UNSIGNED NOT NULL,
  permiso_id    INT UNSIGNED NOT NULL,
  PRIMARY KEY (rol_id, permiso_id),
  CONSTRAINT fk_rp_rol     FOREIGN KEY (rol_id)     REFERENCES roles(id)    ON DELETE CASCADE,
  CONSTRAINT fk_rp_permiso FOREIGN KEY (permiso_id) REFERENCES permisos(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- UBICACIONES (depósitos y locales en una sola tabla => escalable)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ubicaciones (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre        VARCHAR(100) NOT NULL UNIQUE,
  tipo          ENUM('DEPOSITO','LOCAL') NOT NULL,
  direccion     VARCHAR(200) NULL,
  telefono      VARCHAR(40)  NULL,
  responsable   VARCHAR(100) NULL,
  horarios      VARCHAR(150) NULL,
  observaciones TEXT NULL,
  activo        TINYINT(1)   NOT NULL DEFAULT 1,
  creado_en     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_ubic_tipo (tipo, activo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS usuarios (
  id                     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre                 VARCHAR(100) NOT NULL,
  username               VARCHAR(50)  NOT NULL UNIQUE,
  email                  VARCHAR(120) NULL,
  password_hash          VARCHAR(255) NOT NULL,
  rol_id                 INT UNSIGNED NOT NULL,
  ubicacion_id           INT UNSIGNED NULL,
  activo                 TINYINT(1)   NOT NULL DEFAULT 1,
  debe_cambiar_password  TINYINT(1)   NOT NULL DEFAULT 1,
  ultimo_login           DATETIME     NULL,
  creado_en              DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_usr_rol  FOREIGN KEY (rol_id)       REFERENCES roles(id),
  CONSTRAINT fk_usr_ubic FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- PERSONAS: empleados, clientes, proveedores
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS empleados (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre         VARCHAR(80)  NOT NULL,
  apellido       VARCHAR(80)  NOT NULL,
  dni            VARCHAR(15)  NOT NULL UNIQUE,
  telefono       VARCHAR(40)  NULL,
  email          VARCHAR(120) NULL,
  puesto         ENUM('Vendedor','Encargado','Cajero','Administrativo','Depósito','Otro') NOT NULL DEFAULT 'Vendedor',
  fecha_ingreso  DATE         NULL,
  sueldo         DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (sueldo >= 0),
  activo         TINYINT(1)   NOT NULL DEFAULT 1,
  ubicacion_id   INT UNSIGNED NULL,
  CONSTRAINT fk_emp_ubic FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id),
  INDEX idx_emp_nombre (apellido, nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS clientes (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre         VARCHAR(80)  NOT NULL,
  apellido       VARCHAR(80)  NOT NULL,
  dni            VARCHAR(15)  NULL UNIQUE,
  telefono       VARCHAR(40)  NULL,
  whatsapp       VARCHAR(40)  NULL,
  email          VARCHAR(120) NULL,
  direccion      VARCHAR(200) NULL,
  ubicacion_id   INT UNSIGNED NULL COMMENT 'Local donde se registró',
  activo         TINYINT(1)   NOT NULL DEFAULT 1,
  creado_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cli_ubic FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id),
  INDEX idx_cli_nombre (apellido, nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS proveedores (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  razon_social   VARCHAR(150) NOT NULL,
  nombre         VARCHAR(100) NULL,
  cuit           VARCHAR(15)  NULL UNIQUE,
  dni            VARCHAR(15)  NULL,
  telefono       VARCHAR(40)  NULL,
  email          VARCHAR(120) NULL,
  direccion      VARCHAR(200) NULL,
  contacto       VARCHAR(100) NULL,
  activo         TINYINT(1)   NOT NULL DEFAULT 1,
  observaciones  TEXT NULL,
  creado_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_prov_rs (razon_social)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- CATÁLOGO
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categorias (
  id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre     VARCHAR(80) NOT NULL,
  parent_id  INT UNSIGNED NULL COMMENT 'NULL = categoría, con valor = subcategoría',
  activo     TINYINT(1)  NOT NULL DEFAULT 1,
  UNIQUE KEY uq_cat (nombre, parent_id),
  CONSTRAINT fk_cat_parent FOREIGN KEY (parent_id) REFERENCES categorias(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS marcas (
  id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre  VARCHAR(80) NOT NULL UNIQUE,
  activo  TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS temporadas (
  id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre  VARCHAR(60) NOT NULL UNIQUE,
  activo  TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS talles (
  id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre  VARCHAR(20) NOT NULL UNIQUE,
  orden   INT         NOT NULL DEFAULT 0,
  activo  TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS colores (
  id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre  VARCHAR(40) NOT NULL UNIQUE,
  hex     CHAR(7)     NULL,
  activo  TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS productos (
  id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  codigo_interno   VARCHAR(30)  NOT NULL UNIQUE,
  codigo_barras    VARCHAR(40)  NULL UNIQUE,
  nombre           VARCHAR(150) NOT NULL,
  marca_id         INT UNSIGNED NULL,
  categoria_id     INT UNSIGNED NULL,
  subcategoria_id  INT UNSIGNED NULL,
  descripcion      TEXT NULL,
  precio_compra    DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (precio_compra >= 0),
  precio_venta     DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (precio_venta >= 0),
  imagen           VARCHAR(200) NULL,
  activo           TINYINT(1)   NOT NULL DEFAULT 1,
  temporada_id     INT UNSIGNED NULL,
  genero           ENUM('Hombre','Mujer','Unisex','Niño','Niña') NOT NULL DEFAULT 'Unisex',
  creado_en        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_prod_marca  FOREIGN KEY (marca_id)        REFERENCES marcas(id),
  CONSTRAINT fk_prod_cat    FOREIGN KEY (categoria_id)    REFERENCES categorias(id),
  CONSTRAINT fk_prod_subcat FOREIGN KEY (subcategoria_id) REFERENCES categorias(id),
  CONSTRAINT fk_prod_temp   FOREIGN KEY (temporada_id)    REFERENCES temporadas(id),
  INDEX idx_prod_nombre (nombre),
  INDEX idx_prod_cat (categoria_id, activo)
) ENGINE=InnoDB;

-- PRODUCTO + TALLE + COLOR = VARIANTE (cada una con su código de barras)
CREATE TABLE IF NOT EXISTS variantes_producto (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  producto_id    INT UNSIGNED NOT NULL,
  talle_id       INT UNSIGNED NOT NULL,
  color_id       INT UNSIGNED NOT NULL,
  codigo_barras  VARCHAR(40)  NOT NULL UNIQUE,
  activo         TINYINT(1)   NOT NULL DEFAULT 1,
  UNIQUE KEY uq_variante (producto_id, talle_id, color_id),
  CONSTRAINT fk_var_prod  FOREIGN KEY (producto_id) REFERENCES productos(id),
  CONSTRAINT fk_var_talle FOREIGN KEY (talle_id)    REFERENCES talles(id),
  CONSTRAINT fk_var_color FOREIGN KEY (color_id)    REFERENCES colores(id)
) ENGINE=InnoDB;

-- STOCK POR VARIANTE Y UBICACIÓN
CREATE TABLE IF NOT EXISTS stock (
  variante_id   INT UNSIGNED NOT NULL,
  ubicacion_id  INT UNSIGNED NOT NULL,
  cantidad      INT          NOT NULL DEFAULT 0,
  stock_minimo  INT          NOT NULL DEFAULT 2,
  actualizado_en DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (variante_id, ubicacion_id),
  CONSTRAINT fk_stock_var  FOREIGN KEY (variante_id)  REFERENCES variantes_producto(id),
  CONSTRAINT fk_stock_ubic FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id),
  INDEX idx_stock_ubic (ubicacion_id, cantidad)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS movimientos_stock (
  id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fecha            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  tipo             ENUM('ENTRADA','SALIDA','VENTA','DEVOLUCION','TRANSFERENCIA','AJUSTE','COMPRA','ANULACION') NOT NULL,
  variante_id      INT UNSIGNED NOT NULL,
  cantidad         INT          NOT NULL,
  origen_id        INT UNSIGNED NULL,
  destino_id       INT UNSIGNED NULL,
  usuario_id       INT UNSIGNED NOT NULL,
  motivo           VARCHAR(255) NULL,
  referencia_tipo  VARCHAR(30)  NULL,
  referencia_id    INT UNSIGNED NULL,
  CONSTRAINT fk_ms_var  FOREIGN KEY (variante_id) REFERENCES variantes_producto(id),
  CONSTRAINT fk_ms_ori  FOREIGN KEY (origen_id)   REFERENCES ubicaciones(id),
  CONSTRAINT fk_ms_des  FOREIGN KEY (destino_id)  REFERENCES ubicaciones(id),
  CONSTRAINT fk_ms_usr  FOREIGN KEY (usuario_id)  REFERENCES usuarios(id),
  INDEX idx_ms_fecha (fecha),
  INDEX idx_ms_tipo (tipo, fecha)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- SOLICITUDES Y TRANSFERENCIAS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS solicitudes_stock (
  id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  ubicacion_id      INT UNSIGNED NOT NULL COMMENT 'Local que solicita',
  usuario_id        INT UNSIGNED NOT NULL,
  fecha             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  estado            ENUM('Pendiente','Aprobada','Preparando','Enviada','Recibida','Rechazada') NOT NULL DEFAULT 'Pendiente',
  observaciones     VARCHAR(255) NULL,
  respuesta         VARCHAR(255) NULL,
  actualizado_por   INT UNSIGNED NULL,
  actualizado_en    DATETIME NULL,
  CONSTRAINT fk_sol_ubic FOREIGN KEY (ubicacion_id)    REFERENCES ubicaciones(id),
  CONSTRAINT fk_sol_usr  FOREIGN KEY (usuario_id)      REFERENCES usuarios(id),
  CONSTRAINT fk_sol_upd  FOREIGN KEY (actualizado_por) REFERENCES usuarios(id),
  INDEX idx_sol_estado (estado)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS detalle_solicitudes (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  solicitud_id  INT UNSIGNED NOT NULL,
  variante_id   INT UNSIGNED NOT NULL,
  cantidad      INT NOT NULL CHECK (cantidad > 0),
  CONSTRAINT fk_ds_sol FOREIGN KEY (solicitud_id) REFERENCES solicitudes_stock(id) ON DELETE CASCADE,
  CONSTRAINT fk_ds_var FOREIGN KEY (variante_id)  REFERENCES variantes_producto(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS transferencias (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  fecha          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  origen_id      INT UNSIGNED NOT NULL,
  destino_id     INT UNSIGNED NOT NULL,
  usuario_id     INT UNSIGNED NOT NULL,
  estado         ENUM('En tránsito','Completada') NOT NULL DEFAULT 'Completada',
  solicitud_id   INT UNSIGNED NULL,
  observaciones  VARCHAR(255) NULL,
  CONSTRAINT fk_tr_ori FOREIGN KEY (origen_id)    REFERENCES ubicaciones(id),
  CONSTRAINT fk_tr_des FOREIGN KEY (destino_id)   REFERENCES ubicaciones(id),
  CONSTRAINT fk_tr_usr FOREIGN KEY (usuario_id)   REFERENCES usuarios(id),
  CONSTRAINT fk_tr_sol FOREIGN KEY (solicitud_id) REFERENCES solicitudes_stock(id),
  CONSTRAINT chk_tr_dist CHECK (origen_id <> destino_id),
  INDEX idx_tr_fecha (fecha)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS detalle_transferencias (
  id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  transferencia_id  INT UNSIGNED NOT NULL,
  variante_id       INT UNSIGNED NOT NULL,
  cantidad          INT NOT NULL CHECK (cantidad > 0),
  CONSTRAINT fk_dt_tr  FOREIGN KEY (transferencia_id) REFERENCES transferencias(id) ON DELETE CASCADE,
  CONSTRAINT fk_dt_var FOREIGN KEY (variante_id)      REFERENCES variantes_producto(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- MÉTODOS DE PAGO
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metodos_pago (
  id        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  codigo    VARCHAR(20) NOT NULL UNIQUE,
  nombre    VARCHAR(40) NOT NULL,
  activo    TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- COMPRAS Y PAGOS A PROVEEDORES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compras (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  proveedor_id    INT UNSIGNED NOT NULL,
  ubicacion_id    INT UNSIGNED NOT NULL COMMENT 'Depósito que recibe',
  numero_factura  VARCHAR(40)  NULL,
  fecha           DATE         NOT NULL,
  total           DECIMAL(14,2) NOT NULL DEFAULT 0,
  metodo_pago_id  INT UNSIGNED NULL,
  monto_pagado    DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT 'Pagado al momento de la compra',
  usuario_id      INT UNSIGNED NOT NULL,
  observaciones   VARCHAR(255) NULL,
  creado_en       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_co_prov FOREIGN KEY (proveedor_id)   REFERENCES proveedores(id),
  CONSTRAINT fk_co_ubic FOREIGN KEY (ubicacion_id)   REFERENCES ubicaciones(id),
  CONSTRAINT fk_co_mp   FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago(id),
  CONSTRAINT fk_co_usr  FOREIGN KEY (usuario_id)     REFERENCES usuarios(id),
  UNIQUE KEY uq_factura (proveedor_id, numero_factura),
  INDEX idx_co_fecha (fecha)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS detalle_compras (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  compra_id      INT UNSIGNED NOT NULL,
  variante_id    INT UNSIGNED NOT NULL,
  cantidad       INT NOT NULL CHECK (cantidad > 0),
  precio_compra  DECIMAL(12,2) NOT NULL CHECK (precio_compra >= 0),
  CONSTRAINT fk_dc_co  FOREIGN KEY (compra_id)   REFERENCES compras(id) ON DELETE CASCADE,
  CONSTRAINT fk_dc_var FOREIGN KEY (variante_id) REFERENCES variantes_producto(id)
) ENGINE=InnoDB;

-- "pagos": pagos realizados a proveedores (a cuenta o por compra)
CREATE TABLE IF NOT EXISTS pagos (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  proveedor_id    INT UNSIGNED NOT NULL,
  compra_id       INT UNSIGNED NULL,
  fecha           DATE NOT NULL,
  monto           DECIMAL(14,2) NOT NULL CHECK (monto > 0),
  metodo_pago_id  INT UNSIGNED NOT NULL,
  usuario_id      INT UNSIGNED NOT NULL,
  observaciones   VARCHAR(255) NULL,
  creado_en       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_pa_prov FOREIGN KEY (proveedor_id)   REFERENCES proveedores(id),
  CONSTRAINT fk_pa_co   FOREIGN KEY (compra_id)      REFERENCES compras(id),
  CONSTRAINT fk_pa_mp   FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago(id),
  CONSTRAINT fk_pa_usr  FOREIGN KEY (usuario_id)     REFERENCES usuarios(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- CAJAS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cajas (
  id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  ubicacion_id        INT UNSIGNED NOT NULL,
  usuario_apertura_id INT UNSIGNED NOT NULL,
  fecha_apertura      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  monto_inicial       DECIMAL(14,2) NOT NULL DEFAULT 0 CHECK (monto_inicial >= 0),
  estado              ENUM('ABIERTA','CERRADA') NOT NULL DEFAULT 'ABIERTA',
  usuario_cierre_id   INT UNSIGNED NULL,
  fecha_cierre        DATETIME NULL,
  efectivo_esperado   DECIMAL(14,2) NULL,
  efectivo_real       DECIMAL(14,2) NULL,
  diferencia          DECIMAL(14,2) NULL,
  observaciones       VARCHAR(255) NULL,
  -- columna generada: sólo puede haber UNA caja ABIERTA por local
  abierta_flag        INT UNSIGNED AS (IF(estado = 'ABIERTA', ubicacion_id, NULL)) STORED,
  UNIQUE KEY uq_caja_abierta (abierta_flag),
  CONSTRAINT fk_caja_ubic FOREIGN KEY (ubicacion_id)        REFERENCES ubicaciones(id),
  CONSTRAINT fk_caja_ua   FOREIGN KEY (usuario_apertura_id) REFERENCES usuarios(id),
  CONSTRAINT fk_caja_uc   FOREIGN KEY (usuario_cierre_id)   REFERENCES usuarios(id),
  INDEX idx_caja_fecha (ubicacion_id, fecha_apertura)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- VENTAS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ventas (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  ubicacion_id    INT UNSIGNED NOT NULL,
  caja_id         INT UNSIGNED NOT NULL,
  usuario_id      INT UNSIGNED NOT NULL,
  cliente_id      INT UNSIGNED NULL,
  fecha           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  subtotal        DECIMAL(14,2) NOT NULL,
  descuento       DECIMAL(14,2) NOT NULL DEFAULT 0,
  total           DECIMAL(14,2) NOT NULL,
  metodo_pago_id  INT UNSIGNED NOT NULL,
  estado          ENUM('Completada','Anulada','Devuelta') NOT NULL DEFAULT 'Completada',
  observaciones   VARCHAR(255) NULL,
  CONSTRAINT fk_v_ubic FOREIGN KEY (ubicacion_id)   REFERENCES ubicaciones(id),
  CONSTRAINT fk_v_caja FOREIGN KEY (caja_id)        REFERENCES cajas(id),
  CONSTRAINT fk_v_usr  FOREIGN KEY (usuario_id)     REFERENCES usuarios(id),
  CONSTRAINT fk_v_cli  FOREIGN KEY (cliente_id)     REFERENCES clientes(id),
  CONSTRAINT fk_v_mp   FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago(id),
  INDEX idx_v_fecha (fecha),
  INDEX idx_v_ubic_fecha (ubicacion_id, fecha)
) ENGINE=InnoDB;

-- precio_unitario y costo_unitario se guardan como valor HISTÓRICO de la venta
CREATE TABLE IF NOT EXISTS detalle_ventas (
  id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  venta_id         INT UNSIGNED NOT NULL,
  variante_id      INT UNSIGNED NOT NULL,
  cantidad         INT NOT NULL CHECK (cantidad > 0),
  precio_unitario  DECIMAL(12,2) NOT NULL,
  costo_unitario   DECIMAL(12,2) NOT NULL DEFAULT 0,
  CONSTRAINT fk_dv_v   FOREIGN KEY (venta_id)    REFERENCES ventas(id),
  CONSTRAINT fk_dv_var FOREIGN KEY (variante_id) REFERENCES variantes_producto(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS movimientos_caja (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  caja_id         INT UNSIGNED NOT NULL,
  tipo            ENUM('VENTA','PAGO_CLIENTE','INGRESO','RETIRO','GASTO','DEVOLUCION') NOT NULL,
  concepto        VARCHAR(200) NOT NULL,
  monto           DECIMAL(14,2) NOT NULL CHECK (monto >= 0),
  metodo_pago_id  INT UNSIGNED NOT NULL,
  usuario_id      INT UNSIGNED NOT NULL,
  venta_id        INT UNSIGNED NULL,
  fecha           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mc_caja FOREIGN KEY (caja_id)        REFERENCES cajas(id),
  CONSTRAINT fk_mc_mp   FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago(id),
  CONSTRAINT fk_mc_usr  FOREIGN KEY (usuario_id)     REFERENCES usuarios(id),
  CONSTRAINT fk_mc_v    FOREIGN KEY (venta_id)       REFERENCES ventas(id),
  INDEX idx_mc_caja (caja_id, tipo)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- CUENTAS CORRIENTES DE CLIENTES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cuentas_corrientes (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  cliente_id      INT UNSIGNED NOT NULL UNIQUE,
  limite_credito  DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '0 = sin límite',
  creado_en       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cc_cli FOREIGN KEY (cliente_id) REFERENCES clientes(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS movimientos_cuenta_corriente (
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  cuenta_id         INT UNSIGNED NOT NULL,
  fecha             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  concepto          VARCHAR(200) NOT NULL,
  debe              DECIMAL(14,2) NOT NULL DEFAULT 0 CHECK (debe >= 0),
  haber             DECIMAL(14,2) NOT NULL DEFAULT 0 CHECK (haber >= 0),
  venta_id          INT UNSIGNED NULL,
  metodo_pago_id    INT UNSIGNED NULL,
  usuario_id        INT UNSIGNED NOT NULL,
  CONSTRAINT fk_mcc_cc  FOREIGN KEY (cuenta_id)      REFERENCES cuentas_corrientes(id),
  CONSTRAINT fk_mcc_v   FOREIGN KEY (venta_id)       REFERENCES ventas(id),
  CONSTRAINT fk_mcc_mp  FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago(id),
  CONSTRAINT fk_mcc_usr FOREIGN KEY (usuario_id)     REFERENCES usuarios(id),
  INDEX idx_mcc_cuenta (cuenta_id, fecha)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- DEVOLUCIONES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devoluciones (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  venta_id       INT UNSIGNED NOT NULL,
  ubicacion_id   INT UNSIGNED NOT NULL,
  usuario_id     INT UNSIGNED NOT NULL,
  caja_id        INT UNSIGNED NULL,
  fecha          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  motivo         VARCHAR(255) NOT NULL,
  total          DECIMAL(14,2) NOT NULL,
  reintegro      ENUM('EFECTIVO','CUENTA_CORRIENTE','CAMBIO','NINGUNO') NOT NULL DEFAULT 'EFECTIVO',
  CONSTRAINT fk_dev_v    FOREIGN KEY (venta_id)     REFERENCES ventas(id),
  CONSTRAINT fk_dev_ubic FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id),
  CONSTRAINT fk_dev_usr  FOREIGN KEY (usuario_id)   REFERENCES usuarios(id),
  CONSTRAINT fk_dev_caja FOREIGN KEY (caja_id)      REFERENCES cajas(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS detalle_devoluciones (
  id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  devolucion_id     INT UNSIGNED NOT NULL,
  detalle_venta_id  INT UNSIGNED NOT NULL,
  cantidad          INT NOT NULL CHECK (cantidad > 0),
  monto             DECIMAL(14,2) NOT NULL,
  CONSTRAINT fk_dd_dev FOREIGN KEY (devolucion_id)    REFERENCES devoluciones(id) ON DELETE CASCADE,
  CONSTRAINT fk_dd_dv  FOREIGN KEY (detalle_venta_id) REFERENCES detalle_ventas(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- GASTOS Y PAGOS A EMPLEADOS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categorias_gasto (
  id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  nombre  VARCHAR(60) NOT NULL UNIQUE,
  activo  TINYINT(1)  NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS gastos (
  id                 INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  categoria_gasto_id INT UNSIGNED NOT NULL,
  descripcion        VARCHAR(200) NOT NULL,
  monto              DECIMAL(14,2) NOT NULL CHECK (monto > 0),
  ubicacion_id       INT UNSIGNED NULL COMMENT 'NULL = gasto general del negocio',
  fecha              DATE NOT NULL,
  metodo_pago_id     INT UNSIGNED NOT NULL,
  usuario_id         INT UNSIGNED NOT NULL,
  caja_id            INT UNSIGNED NULL COMMENT 'Si se pagó desde una caja',
  observaciones      VARCHAR(255) NULL,
  creado_en          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_g_cat  FOREIGN KEY (categoria_gasto_id) REFERENCES categorias_gasto(id),
  CONSTRAINT fk_g_ubic FOREIGN KEY (ubicacion_id)       REFERENCES ubicaciones(id),
  CONSTRAINT fk_g_mp   FOREIGN KEY (metodo_pago_id)     REFERENCES metodos_pago(id),
  CONSTRAINT fk_g_usr  FOREIGN KEY (usuario_id)         REFERENCES usuarios(id),
  CONSTRAINT fk_g_caja FOREIGN KEY (caja_id)            REFERENCES cajas(id),
  INDEX idx_g_fecha (fecha)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pagos_empleados (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  empleado_id     INT UNSIGNED NOT NULL,
  concepto        VARCHAR(120) NOT NULL,
  periodo         CHAR(7)      NOT NULL COMMENT 'AAAA-MM',
  monto           DECIMAL(14,2) NOT NULL CHECK (monto > 0),
  fecha           DATE NOT NULL,
  metodo_pago_id  INT UNSIGNED NOT NULL,
  usuario_id      INT UNSIGNED NOT NULL,
  observaciones   VARCHAR(255) NULL,
  CONSTRAINT fk_pe_emp FOREIGN KEY (empleado_id)    REFERENCES empleados(id),
  CONSTRAINT fk_pe_mp  FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago(id),
  CONSTRAINT fk_pe_usr FOREIGN KEY (usuario_id)     REFERENCES usuarios(id),
  INDEX idx_pe_periodo (periodo)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- INVENTARIOS FÍSICOS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventarios (
  id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  ubicacion_id      INT UNSIGNED NOT NULL,
  usuario_id        INT UNSIGNED NOT NULL,
  fecha             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  estado            ENUM('Pendiente','Aprobado','Rechazado') NOT NULL DEFAULT 'Pendiente',
  motivo            VARCHAR(255) NOT NULL,
  aprobado_por      INT UNSIGNED NULL,
  fecha_aprobacion  DATETIME NULL,
  CONSTRAINT fk_inv_ubic FOREIGN KEY (ubicacion_id) REFERENCES ubicaciones(id),
  CONSTRAINT fk_inv_usr  FOREIGN KEY (usuario_id)   REFERENCES usuarios(id),
  CONSTRAINT fk_inv_apr  FOREIGN KEY (aprobado_por) REFERENCES usuarios(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS detalle_inventarios (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  inventario_id  INT UNSIGNED NOT NULL,
  variante_id    INT UNSIGNED NOT NULL,
  stock_sistema  INT NOT NULL,
  stock_real     INT NOT NULL CHECK (stock_real >= 0),
  UNIQUE KEY uq_di (inventario_id, variante_id),
  CONSTRAINT fk_di_inv FOREIGN KEY (inventario_id) REFERENCES inventarios(id) ON DELETE CASCADE,
  CONSTRAINT fk_di_var FOREIGN KEY (variante_id)   REFERENCES variantes_producto(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- AUDITORÍA Y CONFIGURACIÓN
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auditoria (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  usuario_id   INT UNSIGNED NULL,
  accion       VARCHAR(255) NOT NULL,
  modulo       VARCHAR(40)  NOT NULL,
  registro_id  VARCHAR(40)  NULL,
  ip           VARCHAR(45)  NULL,
  fecha        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_aud_usr FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
  INDEX idx_aud_fecha (fecha),
  INDEX idx_aud_mod (modulo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS configuracion (
  clave        VARCHAR(60) PRIMARY KEY,
  valor        VARCHAR(255) NOT NULL,
  descripcion  VARCHAR(255) NULL
) ENGINE=InnoDB;

SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- VISTAS DE APOYO
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW locales AS
  SELECT id, nombre, direccion, telefono, responsable, horarios, observaciones, activo
  FROM ubicaciones WHERE tipo = 'LOCAL';

CREATE OR REPLACE VIEW v_saldos_cc AS
  SELECT cc.id AS cuenta_id, cc.cliente_id,
         COALESCE(SUM(m.debe),0) AS debe, COALESCE(SUM(m.haber),0) AS haber,
         COALESCE(SUM(m.debe - m.haber),0) AS saldo,
         MAX(m.fecha) AS ultimo_movimiento
  FROM cuentas_corrientes cc
  LEFT JOIN movimientos_cuenta_corriente m ON m.cuenta_id = cc.id
  GROUP BY cc.id, cc.cliente_id;

-- =====================================================================
--  DATOS INICIALES
-- =====================================================================
INSERT IGNORE INTO roles (id, codigo, nombre, descripcion) VALUES
 (1, 'ADMIN', 'Dueño / Administrador', 'Acceso total al sistema'),
 (2, 'LOCAL', 'Usuario de Local', 'Opera únicamente su local: caja, ventas, clientes y stock propio');

INSERT IGNORE INTO permisos (codigo, descripcion) VALUES
 ('dashboard.ver','Ver dashboard'),
 ('ventas.crear','Realizar ventas (POS)'),
 ('ventas.ver','Consultar ventas'),
 ('ventas.anular','Anular ventas'),
 ('devoluciones.crear','Registrar devoluciones'),
 ('caja.operar','Abrir, operar y cerrar caja'),
 ('caja.ver_todas','Ver cajas de todos los locales'),
 ('clientes.gestionar','Registrar y consultar clientes'),
 ('clientes.cobrar','Cobrar cuentas corrientes'),
 ('stock.ver_local','Ver stock del propio local'),
 ('stock.ver_todo','Ver stock de todas las ubicaciones'),
 ('stock.gestionar','Ajustes, entradas y transferencias'),
 ('solicitudes.crear','Solicitar mercadería al depósito'),
 ('solicitudes.gestionar','Aprobar y despachar solicitudes'),
 ('productos.ver','Ver productos'),
 ('productos.gestionar','Crear/editar productos y precios'),
 ('compras.gestionar','Registrar compras'),
 ('proveedores.gestionar','Administrar proveedores'),
 ('empleados.gestionar','Administrar empleados y pagos'),
 ('gastos.gestionar','Registrar gastos'),
 ('reportes.ver','Ver reportes'),
 ('usuarios.gestionar','Administrar usuarios'),
 ('locales.gestionar','Administrar locales y depósitos'),
 ('configuracion.gestionar','Configurar el sistema'),
 ('inventarios.crear','Cargar inventario físico'),
 ('inventarios.aprobar','Aprobar ajustes de inventario'),
 ('auditoria.ver','Ver auditoría');

-- ADMIN: todos los permisos
INSERT IGNORE INTO rol_permisos (rol_id, permiso_id) SELECT 1, id FROM permisos;
-- LOCAL: permisos operativos del propio local
INSERT IGNORE INTO rol_permisos (rol_id, permiso_id)
  SELECT 2, id FROM permisos WHERE codigo IN
  ('dashboard.ver','ventas.crear','ventas.ver','devoluciones.crear','caja.operar',
   'clientes.gestionar','clientes.cobrar','stock.ver_local','solicitudes.crear',
   'productos.ver','inventarios.crear');

INSERT IGNORE INTO ubicaciones (id, nombre, tipo, direccion, telefono, responsable, horarios) VALUES
 (1, 'Éxtasis — Depósito Central', 'DEPOSITO', NULL, NULL, NULL, NULL),
 (2, 'Éxtasis — Concepción', 'LOCAL', 'Concepción', NULL, NULL, 'Lun a Sáb 9:00 a 13:00 y 17:00 a 21:00'),
 (3, 'Éxtasis — Segundo Local', 'LOCAL', NULL, NULL, NULL, 'Lun a Sáb 9:00 a 13:00 y 17:00 a 21:00');

-- CREDENCIALES DE PRUEBA (se obliga a cambiarlas en el primer inicio de sesión)
--   admin       / Admin2026!
--   concepcion  / Concepcion2026!
--   local2      / Local2-2026!
INSERT IGNORE INTO usuarios (id, nombre, username, password_hash, rol_id, ubicacion_id, debe_cambiar_password) VALUES
 (1, 'Administrador', 'admin', 'scrypt:32768:8:1$bx8njJN5ufYYfTV6$7ee6501b20c09a98e5ac0ac4ea883235d637b5a9b93c8c193a6060392d76dc88f249c933fd3081fdff736e1b888c3e749bb1934b6885c91bfaf3b1c4d425274f', 1, NULL, 1),
 (2, 'Local Concepción', 'concepcion', 'scrypt:32768:8:1$Z15PKUqS4R7gRyCD$d592e99e0e060399bc249b204678d43f3a03c2cf3b7b1ecc3941abec8ef7d2e02ed0ba23f71e8952825118cc5dbfb3df6e54946a05970153db1fd7ca7d192a22', 2, 2, 1),
 (3, 'Segundo Local', 'local2', 'scrypt:32768:8:1$oWWcwFQaq3ZRrLNn$ca9560367459c84c526b7da544e2c655928eb39c7b1f485f559db23fa8c8e4d6c115f18844a985e0d2085826108427c56027584e8c3aed482a5fb824fb199f85', 2, 3, 1);

INSERT IGNORE INTO metodos_pago (id, codigo, nombre) VALUES
 (1,'EFECTIVO','Efectivo'),(2,'DEBITO','Débito'),(3,'CREDITO','Crédito'),
 (4,'TRANSFERENCIA','Transferencia'),(5,'MERCADOPAGO','Mercado Pago'),
 (6,'CTACTE','Cuenta corriente'),(7,'OTRO','Otro');

INSERT IGNORE INTO categorias (id, nombre, parent_id) VALUES
 (1,'Remeras',NULL),(2,'Pantalones',NULL),(3,'Jeans',NULL),(4,'Camisas',NULL),(5,'Buzos',NULL),
 (6,'Camperas',NULL),(7,'Vestidos',NULL),(8,'Faldas',NULL),(9,'Calzado',NULL),(10,'Accesorios',NULL);

INSERT IGNORE INTO temporadas (id, nombre) VALUES
 (1,'Primavera/Verano'),(2,'Otoño/Invierno'),(3,'Todo el año');

INSERT IGNORE INTO talles (id, nombre, orden) VALUES
 (1,'Único',0),(2,'XS',10),(3,'S',20),(4,'M',30),(5,'L',40),(6,'XL',50),(7,'XXL',60),
 (8,'36',100),(9,'38',110),(10,'40',120),(11,'42',130),(12,'44',140),(13,'46',150),(14,'48',160);

INSERT IGNORE INTO colores (id, nombre, hex) VALUES
 (1,'Único','#9aa5b1'),(2,'Negro','#111111'),(3,'Blanco','#ffffff'),(4,'Rojo','#c0392b'),
 (5,'Azul','#1f4e99'),(6,'Verde','#2e7d32'),(7,'Beige','#d8c3a5'),(8,'Gris','#7f8c8d');

INSERT IGNORE INTO categorias_gasto (nombre) VALUES
 ('Alquiler'),('Luz'),('Agua'),('Internet'),('Seguridad'),('Limpieza'),('Mantenimiento'),
 ('Publicidad'),('Transporte'),('Servicios'),('Reparaciones'),('Otros');

INSERT IGNORE INTO configuracion (clave, valor, descripcion) VALUES
 ('nombre_negocio','ÉXTASIS','Nombre que aparece en tickets y encabezados'),
 ('permitir_venta_sin_stock','0','1 = permite vender aunque el local no tenga stock'),
 ('stock_minimo_default','2','Stock mínimo por defecto para alertas de bajo stock'),
 ('dias_vencimiento_cc','30','Días sin pagos para considerar vencida una cuenta corriente'),
 ('dias_antiguedad_producto','180','Días para considerar un producto con mucha antigüedad'),
 ('ticket_pie','¡Gracias por su compra!','Texto al pie del ticket'),
 ('prefijo_codigo_barras','200','Prefijo para códigos de barras generados (EAN-13)');
