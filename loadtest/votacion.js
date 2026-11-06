// Prueba de carga de la votación de delegados (k6). Ver loadtest/README.md.
//
//   k6 run -e API_URL=https://api.ejemplo.mx/api/v1 -e TOKENS=accesos.csv loadtest/votacion.js
//
// TOKENS es el CSV que descarga el panel en «Votación → Descargar CSV con enlaces»
// (la última columna es el enlace; el token es lo que va después de «#/votar/»).
// Cada usuario virtual es un delegado: consulta su boleta cada 20 s (como la página)
// y vota por todas las delegaciones de su comité en la sesión abierta.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

const API_URL = __ENV.API_URL || 'http://127.0.0.1:8000/api/v1';
const DELEGATES = Number(__ENV.DELEGATES || 0);

const tokens = new SharedArray('tokens', () =>
  open(__ENV.TOKENS || 'accesos.csv')
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.split('#/votar/')[1])
    .filter(Boolean)
    .map((t) => t.replace(/"/g, '').trim()),
);

const VUS = DELEGATES || tokens.length;

export const options = {
  scenarios: {
    delegados: {
      executor: 'ramping-vus',
      stages: [
        { duration: '30s', target: VUS }, // todos entran al abrir la sesión
        { duration: '3m', target: VUS }, // votan durante la sesión
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:ballot}': ['p(95)<800'],
    'http_req_duration{name:vote}': ['p(95)<1500'],
  },
};

export default function () {
  const token = tokens[(__VU - 1) % tokens.length];
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const res = http.get(`${API_URL}/vote/ballot`, { headers, tags: { name: 'ballot' } });
  check(res, { 'boleta 200': (r) => r.status === 200 });
  if (res.status !== 200) {
    sleep(20);
    return;
  }
  const ballot = res.json();
  if (!ballot.open_session || !ballot.rubric) {
    sleep(20); // esperando la siguiente sesión, como la página
    return;
  }

  // Vota por cada delegación, una a la vez, como en el celular.
  for (const d of ballot.delegations) {
    const items = ballot.rubric.criteria.map((c) => ({
      delegation_id: d.delegation_id,
      criterion_id: c.id,
      value: ballot.rubric.scale_min + Math.floor(Math.random() * (ballot.rubric.scale_max - ballot.rubric.scale_min + 1)),
    }));
    const vote = http.put(`${API_URL}/vote/ballot`, JSON.stringify({ items }), { headers, tags: { name: 'vote' } });
    check(vote, { 'voto 200': (r) => r.status === 200 });
    sleep(3 + Math.random() * 5); // tiempo de mover los sliders
  }
  sleep(20);
}
