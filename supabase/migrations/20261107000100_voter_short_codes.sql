-- Código corto de respaldo para los accesos de los delegados (2026-11-07).
--
-- Si la cámara no lee el QR, el delegado escribe un código de 10 caracteres
-- (p. ej. K7M2Q-9XH4T) que sirve igual que el token. Como el token, solo se guarda
-- su SHA-256 (con prefijo "code:"); el código en claro solo llega al generarlo.
-- Los accesos generados antes no tienen código: hay que regenerarlos para tenerlo.

alter table app.voter_tokens
  add column code_hash text;

alter table app.voter_tokens
  add constraint voter_tokens_code_hash_key unique (code_hash);

comment on column app.voter_tokens.code_hash is
  'SHA-256 de "code:" + código corto normalizado. null en accesos anteriores al 2026-11-07.';
