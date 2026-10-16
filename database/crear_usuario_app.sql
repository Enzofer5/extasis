-- Usuario de MySQL exclusivo para la aplicación ÉXTASIS
-- (evita usar root desde la app). Se puede ejecutar más de una vez.
CREATE USER IF NOT EXISTS 'extasis_app'@'localhost' IDENTIFIED BY 'Extasis_6s8lZe-Yu3YfOWZ';
-- Si el usuario ya existía con otra contraseña, la iguala a la de config.env
ALTER USER 'extasis_app'@'localhost' IDENTIFIED BY 'Extasis_6s8lZe-Yu3YfOWZ' ACCOUNT UNLOCK;
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES, CREATE VIEW, SHOW VIEW
  ON extasis.* TO 'extasis_app'@'localhost';
FLUSH PRIVILEGES;
