// Prueba de carga de la votación de delegados (k6). Ver loadtest/README.md.
//
//   k6 run -e API_URL=https://api.ejemplo.mx/api/v1 -e TOKENS=accesos.csv loadtest/votacion.js
//
// TOKENS es el CSV que descarga el panel en «Votación → Descargar CSV con enlaces»
// (la última columna es el enlace; el token es lo que va después de «#/votar/»).
// Cada usuario virtual es un delegado: consulta su boleta cada 20 s (como la página)
// y, con el voto entre pares abierto, envía una vez sus premios (mejor delegado,
// delegado distinguido, mención de honor).

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
  if (ballot.peer_vote.status !== 'open' || ballot.picks.length > 0) {
    sleep(20); // esperando a que abra (o ya votó), como la página
    return;
  }

  // Elige una delegación distinta al azar para cada premio y envía la boleta una vez.
  sleep(10 + Math.random() * 20); // tiempo de buscar y revisar
  const pool = [...ballot.delegations].sort(() => Math.random() - 0.5);
  const picks = ballot.awards.map((a, i) => ({ award_type: a.award_type, delegation_id: pool[i].delegation_id }));
  const vote = http.post(`${API_URL}/vote/ballot`, JSON.stringify({ picks }), { headers, tags: { name: 'vote' } });
  // 409: otra iteración del mismo delegado ya votó (el voto no se puede cambiar).
  check(vote, { 'voto 200/409': (r) => r.status === 200 || r.status === 409 });
  sleep(20);
}
