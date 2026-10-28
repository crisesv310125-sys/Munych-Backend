# Fixtures del motor de cálculo

Casos de prueba de `apps/api/src/munych_api/scoring_engine`. El backend los ejecuta en
`tests/unit/test_scoring_fixtures.py`, y el frontend los reutilizará en la fase 2 para
comprobar que su cálculo coincide. **La forma es estable**: si hay que cambiarla, se
versiona y se avisa al equipo del frontend.

## Forma de un caso

```jsonc
{
  "name": "Descripción legible del caso",
  "rubric": {
    "scale_min": 1,
    "scale_max": 4,
    "criteria": [{ "id": "c1", "weight": "60", "position": 1 }]   // weight: decimal en texto
  },
  "sessions": ["s1", "s2"],                                         // ids de sesión, en orden
  "delegations": [{ "id": "MX", "delegate_ids": ["mx-1"] }],
  "scores": [
    { "judge_id": "j1", "delegate_id": "mx-1", "session_id": "s1", "criterion_id": "c1", "value": 3 }
  ],
  "expected": {
    "delegates": {
      "mx-1": { "final_score": "82.50", "session_scores": { "s1": "82.50", "s2": null } }
    },
    "ranking": [
      {
        "delegation_id": "MX", "position": 1, "tied": false, "score": "82.50",
        "criteria_averages": { "c1": "3.50" },
        "incomplete_flags": [
          { "kind": "incomplete", "delegate_id": "mx-1", "session_id": "s1", "judge_id": "j2" }
        ]
      }
    ]
  }
}
```

- Los identificadores son cadenas opacas: el motor no interpreta su contenido.
- Todos los números esperados son **cadenas con 2 decimales**, redondeadas mitad hacia arriba
  (`ROUND_HALF_UP`) **solo al final**. `null` significa "sin nota".
- `ranking` está en el orden en que se presenta. Entre delegaciones empatadas (`tied: true`),
  el orden es por `delegation_id` para que sea determinista.

## Reglas que implementan (sección 6.3 de la especificación)

1. **Nota ponderada** de un delegado, por un juez, en una sesión:
   `Σ (value_i / scale_max) × weight_i` (0–100). Si el juez no calificó **todos** los criterios,
   la terna se excluye y se marca `incomplete`.
2. **Nota de sesión** = media de las notas ponderadas de los jueces completos. Si no hay
   ninguna, la sesión se marca `session_without_scores` y no cuenta.
3. **Nota final** del delegado = media de sus notas de sesión. Sin ninguna, se marca
   `delegate_without_scores`.
4. **Nota de la delegación** = media de las notas finales de sus delegados que tienen nota.
5. **Ranking** descendente. Desempate: mayor media en el criterio de mayor peso (entre pesos
   iguales, el de menor `position`). Si persiste, misma posición y `tied: true`. Las delegaciones
   sin nota van al final.
6. `criteria_averages`: media de los valores de cada criterio en las ternas **completas** de los
   delegados de la delegación (todas las sesiones y jueces).

## Tipos de marca (`incomplete_flags[].kind`)

| kind | Significado | session_id | judge_id |
|---|---|---|---|
| `incomplete` | El juez no calificó todos los criterios del delegado en la sesión | sí | sí |
| `session_without_scores` | El delegado no tiene ninguna nota completa en la sesión | sí | `null` |
| `delegate_without_scores` | El delegado no tiene nota final | `null` | `null` |

## Casos

| Archivo | Cubre |
|---|---|
| `01_basico.json` | Caso básico con 2 jueces |
| `02_delegacion_doble.json` | Delegación doble (media de delegados) |
| `03_juez_incompleto.json` | Terna incompleta excluida y marcada |
| `04_sesion_sin_notas.json` | Sesión sin notas y delegación sin ninguna nota |
| `05_empate_resuelto_por_criterio.json` | Empate resuelto por el criterio de mayor peso (y menor `position`) |
| `06_empate_no_resuelto.json` | Empate que decide el administrador |
| `07_escala_0_10.json` | Escala distinta de 1–4, con valor 0 |
| `08_un_solo_juez.json` | Un solo juez, rúbrica por defecto, 2 sesiones, redondeo |
| `09_escala_1_3_decimales_periodicos.json` | Decimales periódicos; redondeo solo al final |
