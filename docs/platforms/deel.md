# Deel

**Última verificación:** 2026-11-10 · **Estado:** descubrimiento disponible (`discovery/deel.py`). La postulación la hace el usuario en `jobs.deel.com`.

## Descubrimiento (sin login)

Deel usa Ashby por dentro, pero su tablero público de Ashby (`jobs.ashbyhq.com/Deel`) está vacío. Las vacantes están en su propia página:

- **Listado:** `GET https://www.deel.com/careers/`. `robots.txt` no bloquea `/careers`. La página pesa más de 1 MB, así que la fuente corre como máximo cada 12 h (`min_hours_between_runs`).
- La página es Next.js y trae los datos dentro de scripts `self.__next_f.push([1, "<trozo>"])`. Cada trozo es una cadena JSON; unidos, contienen un objeto `"attributes": {...}` por vacante. El filtro de ubicación de la página (`?location=costa+rica`) se aplica en el navegador: el HTML trae todas.
- **Campos usados:** `ashby_id` (ID), `title`, `all_locations` (países desde donde se puede hacer), `ashby_published_date`, `is_listed` y `slug` (enlace a la vacante en deel.com). La postulación está en `external_link` (`jobs.deel.com/.../application`).
- Todas las vacantes son remotas. La ubicación queda como la lista de países, y los filtros de `search.yaml` dejan las que incluyen el tuyo.

## Configuración

En `targets.yaml`:

```yaml
deel: {}
```

`url` y `min_hours_between_runs` son opcionales.

## Particularidades

- Si la página deja de traer vacantes en ese formato, la fuente lo reporta como error: no es lo mismo que "hoy no hay vacantes". Tras 3 fallos seguidos, la pestaña Decisiones pregunta si desactivarla.
- El 2026-11-10 había 241 vacantes. 5 incluían Costa Rica, todas de ingeniería o seguridad. Las de ventas y soporte para Latinoamérica eran para México, Colombia, Chile, Argentina y Brasil.
