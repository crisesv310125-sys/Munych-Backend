# Prueba de carga de la votación de delegados

Script de [k6](https://k6.io) que simula a los delegados votando desde el celular (spec «Tipos de evento y votación», ADR-005).

## Preparación (en un ambiente de prueba, nunca con el evento real)

1. Crea un evento `mun_regular` con sus comités, delegaciones y delegados reales en número: uno por cada delegado de SD-MUN-2026.
2. Pon el evento en `active` y abre la sesión 1 de todos los comités (pantalla **Sesiones → Abrir sesión N en todos**).
3. En **Votación**, genera los accesos y descarga el CSV (`<slug>-accesos-votacion.csv`).

## Ejecución

```
k6 run -e API_URL=https://<api>/api/v1 -e TOKENS=<slug>-accesos-votacion.csv loadtest/votacion.js
```

- `DELEGATES=<n>` limita el número de usuarios virtuales (por defecto, uno por token).
- Cada usuario consulta su boleta cada 20 s y vota por todas las delegaciones de su comité, con 3 a 8 s entre votos.
- Umbrales: menos de 1 % de errores, p95 de la boleta < 800 ms y p95 del voto < 1.5 s.

## Notas

- El límite de peticiones de la boleta va **por token** (20 GET/min y 30 PUT/min), no por IP: todos los delegados del lugar comparten la IP del wifi.
- El pool de la BD es de 5 + 5 conexiones por proceso. Si el p95 sube, revisa los workers del servidor antes de tocar el pool.
- Al terminar, borra el evento de prueba (o ciérralo) y revoca sus accesos.
