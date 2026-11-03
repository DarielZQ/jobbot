# SAP SuccessFactors (Career Site Builder)

**Última verificación:** 2026-10-27 · **Estado:** descubrimiento disponible (`discovery/successfactors.py`). La postulación la hace el usuario en el sitio de la empresa.

## Cómo reconocerlo

URLs del tipo `/go/<Nombre>/<id>/` para listados y `/job/<Ciudad>-<Título>/<id>/` para vacantes, normalmente en un dominio propio de la empresa (por ejemplo `jobs.foundever.com`).

## Descubrimiento (sin login)

- **Feed RSS público:** `GET {base_url}/services/rss/job/?locale=en_US&keywords=<país>`.
- `title` trae la ubicación al final entre paréntesis: `"... (Heredia, Costa Rica, CR)"`. `split_title` la separa solo si el paréntesis contiene comas.
- `link` trae parámetros de rastreo (`feedId`, `utm_*`); se quitan. El número final de la ruta es el ID de la vacante.
- `description` es HTML completo, así que no hace falta pedir el detalle aparte.

## Configuración

En `targets.yaml`:

```yaml
successfactors:
  - { company: "Acme Corp", base_url: "https://jobs.acme.example" }
```

- `keywords` es opcional: por defecto se usa `region.country` en minúsculas. Sin país, la fuente se reporta como "sin configurar".
- `locale` es opcional (por defecto `en_US`).
