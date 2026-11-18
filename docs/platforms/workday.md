# Workday

**Última verificación:** 2026-11-14 · **Estado:** descubrimiento disponible (`discovery/workday.py`). La postulación la hace el usuario en el sitio de la empresa.

## Descubrimiento (sin login)

El sitio de empleo de cada empresa usa un endpoint JSON propio, sin autenticación:

- **Listado:** `POST https://{host}/wday/cxs/{tenant}/{site}/jobs` con
  `{"appliedFacets": {...}, "limit": 20, "offset": N, "searchText": ""}`. El máximo por página es 20.
- **Detalle:** `GET https://{host}/wday/cxs/{tenant}/{site}{externalPath}` → `jobPostingInfo.jobDescription` (HTML). Solo se pide para las vacantes que pasan los filtros de título y ubicación (`enrich`).
- **URL pública:** `https://{host}/{site}{externalPath}`.

## Configuración

En `targets.yaml`:

```yaml
workday:
  - { company: "Acme Corp", host: acme.wd5.myworkdayjobs.com, tenant: acme, site: External }
```

- `country` es opcional: por defecto se usa `region.country` de `settings.yaml`. Sin país, la fuente se reporta como "sin configurar".
- Para encontrar `host`, `tenant` y `site`, copia la URL de la página de empleos de la empresa y pruébala:

  ```bash
  uv run python scripts/probe_workday.py https://acme.wd5.myworkdayjobs.com/External
  ```

  Si responde, imprime la línea lista para pegar.

## Particularidades

- **El filtro de país cambia de nombre según la empresa:** `locationCountry` (Kyndryl, Equifax, Medtronic), `Location_Country` (HP, Abbott), `Country` (Baxter), `locations` (Intel, HPE, Thermo Fisher), `locationHierarchy1` (Philips), `Country_and_Jurisdiction` (Citi). `find_country_facet` recorre el árbol de facetas y prefiere el parámetro que contenga "country".
- `total` solo es confiable en la primera página; se toma de ahí.
- `locationsText` puede decir `"2 Locations"`: si se aplicó la faceta de país, se le agrega `| <país>`.
- `bulletFields[0]` suele ser el ID de requisición; se usa como `ats_job_id` junto con el tenant.
- `postedOn` da una edad relativa ("Posted Today", "Posted 3 Days Ago", "Posted 30+ Days Ago", o en español "Publicado hace 3 días"). `posted_on` la convierte en una fecha aproximada (ADR-020); "30+" se lee como 31 días, fuera del límite de un mes.
- Algunas empresas devuelven **422** o **404** cuando el `site` adivinado no es el correcto. Hay que copiar la URL real desde su página de empleos y probarla con `probe_workday.py`.
- Algunas empresas no tienen faceta para el país: en ese caso se busca por texto con el nombre del país y deciden los filtros de ubicación.
- **Mantenimiento:** cada empresa tiene su propia ventana. Suele caer en sábado, y la mensual o trimestral puede durar toda la mañana. Mientras dura, el endpoint redirige a `static.community.workday.com`, a una página titulada «Workday is currently unavailable.».
  - JobBot lo reporta como «Sin datos: el sitio respondió una página en vez de datos», con el título de la página, y vuelve a consultar en la próxima corrida.
  - Pasó el 2026-11-14 (segundo sábado del mes): a las 08:30, 16 de 18 empresas estaban en mantenimiento.
- **Verificación anti-bots de Cloudflare (desde el 2026-11-14):**
  - **Síntomas:** responde **429** con el encabezado `cf-mitigated: challenge` y una página «Security Check – Enable JavaScript and cookies to continue». Al principio fallaba una parte de las empresas, distinta en cada corrida (15 de 18 un día, 7 o 12 otro). El 2026-11-18 fallaron las 27 en las dos corridas del día.
  - **El ritmo cuenta:** un día, desde la misma red, otro programa recibía datos mientras JobBot era bloqueado, así que pesa que JobBot se identifique como programa con su `User-Agent` honesto. Pero el 2026-11-18, tras media hora sin consultas, la primera pasó y las siguientes, segundos después, volvieron 429.
  - **Qué hace JobBot:** no la evade, ni cambiando el `User-Agent` ni con un navegador (ADR-003), y consulta menos (ADR-032):
    - no reintenta, y al primer bloqueo deja de consultar las demás empresas en esa corrida, porque todas comparten el mismo Cloudflare;
    - consulta Workday una vez por día, contando las consultas bloqueadas: la primera corrida del día lo hace (normalmente la de las 08:30) y las búsquedas de después lo saltan;
    - deja 5 s entre cualquier consulta a `*.myworkdayjobs.com` (`settings.yaml: http.host_min_interval_s`).
  - **Si una empresa queda bloqueada tres corridas seguidas,** la pestaña Decisiones pregunta si desactivarla y recomienda seguir intentando. Las alertas de LinkedIn por empresa cubren esas vacantes por correo.
