# Cómo contribuir

Gracias por querer mejorar JobBot. Los issues y pull requests son bienvenidos: fuentes nuevas, presets de otros países, correcciones, documentación y traducciones.

Antes de empezar, lee [`docs/architecture.md`](docs/architecture.md) y las decisiones en [`docs/decisions.md`](docs/decisions.md).

## Qué consultar

| Si necesitas saber… | Consulta |
| :--- | :--- |
| Cómo instalar y usar | [`README.es.md`](README.es.md) y [`docs/getting-started.md`](docs/getting-started.md) |
| Qué debe hacer el sistema | [`docs/requirements.md`](docs/requirements.md) |
| Cómo funciona por dentro | [`docs/architecture.md`](docs/architecture.md) |
| Por qué se decidió algo | [`docs/decisions.md`](docs/decisions.md) |
| Estrategia de búsqueda | [`docs/job-search.md`](docs/job-search.md) |
| Cómo se comporta una fuente | [`docs/platforms/`](docs/platforms/) |
| Qué viene después | [`ROADMAP.md`](ROADMAP.md) |

## Reglas no negociables

1. **Sin evasión anti-bot** (ADR-003). Nada de stealth plugins, resolvedores de CAPTCHA, fingerprint spoofing ni proxies rotativos. Si un sitio bloquea o muestra un challenge, esa fuente se detiene y avisa.
2. **Nunca postular por el usuario** (ADR-019). JobBot descubre y asiste; no llena ni envía formularios.
3. **Nunca inventar datos del usuario.** Todo texto de CV y todo cambio de perfil sale de `profile/` o de una respuesta explícita del usuario. Si falta un dato, se pregunta.
4. **Los tests no tocan la red.** Usan `httpx.MockTransport` y fixtures en `tests/fixtures/`. Ningún test ni script de prueba envía nada real.
5. **Secretos y datos personales solo en `JOBBOT_HOME`** (`.env`, `profile/private/`, `data/`). Nunca en el repositorio, en logs, en issues ni en commits. Gmail se usa solo con `gmail.readonly`; no se amplía el permiso.
6. **Un dato vive en un solo lugar.** Los documentos referencian los YAML de configuración; no copian sus valores.
7. **Decisión de arquitectura nueva → ADR** al final de `docs/decisions.md`.
8. **Un documento nuevo se crea solo cuando tiene contenido real.** La ficha de `docs/platforms/` se crea junto con su adapter.

## Convenciones

- Documentación en **español**, salvo `README.md` (inglés). Código, identificadores y mensajes de commit en **inglés**.
- Python ≥ 3.11, type hints, `ruff` (largo de línea 100).
- Paquete en `src/jobbot/`.
- Cada fuente implementa `discovery.base.Source` y devuelve `core.models.Job`.
- Toda llamada HTTP pasa por `core.http.HttpClient` (intervalo mínimo por host, `Retry-After`, reintentos, `User-Agent` honesto).
- Rutas de datos siempre con `jobbot.paths`; nunca rutas fijas ni relativas al repositorio.

## Preparar el entorno

```bash
git clone https://github.com/<usuario>/jobbot.git
cd jobbot
uv sync --extra gmail --extra resumes
```

Para probar sin tocar tus datos reales, usa una carpeta de datos aparte:

```bash
# Linux / macOS
export JOBBOT_HOME="$HOME/JobBot-dev"
# Windows (PowerShell, solo para esta terminal)
$env:JOBBOT_HOME = "$HOME\JobBot-dev"

uv run jobbot init --preset costa-rica-it
```

## Tests y lint

```bash
uv run pytest          # tests, sin red
uv run ruff check .    # lint
uv run ruff format .   # formato
```

CI (`.github/workflows/ci.yml`) corre `pytest`, `ruff check` y `ruff format --check src tests scripts` en Windows, Linux y macOS, más el escaneo de privacidad con todo el historial (`uv run python scripts/privacy_scan.py --history`). Un pull request se acepta solo con todo en verde.

## Agregar una fuente de vacantes

1. **Revisa sus condiciones** antes de escribir código:
   - Términos de uso y `robots.txt`: ¿permiten consultar el listado o la API de forma automática?
   - Límite de consultas (por hora o por día) y `crawl-delay`.
   - ¿Pide login? Si pide login, **no** se acepta como fuente automática.
   - ¿Bloquea bots (403, Cloudflare, CAPTCHA)? Si bloquea, no se fuerza (ADR-003); busca otra vía, como sus alertas por correo.
2. **Adapter:** crea `src/jobbot/discovery/<fuente>.py` con una clase que herede de `Source`:
   - `name`: nombre que se ve en la salida (`<tipo>:<empresa>` si hay una por empresa).
   - `fetch()`: devuelve los `Job` del listado, con llamadas baratas.
   - `enrich(job)` (opcional): pide el detalle solo de las vacantes que pasan los filtros de título y ubicación.
   - `min_hours_between_runs`: si la fuente pide consultas espaciadas.
   - Usa `self.client` (`HttpClient`) para todo HTTP.
3. **Configuración:** agrega su modelo Pydantic en `src/jobbot/config.py`, la clave en `Targets` y el registro en `discovery/pipeline.py: build_sources`. Si la fuente usa país, código de país o zona horaria, toma el valor por defecto de `region` en `config.with_region`, y en `fetch()` llama a `discovery.base.require(...)` para que, sin país, la fuente quede "sin configurar" en vez de adivinar.
4. **Fixture y test:** guarda una respuesta real **anonimizada** en `tests/fixtures/<fuente>_<algo>.json|html|xml` y escribe el test con `httpx.MockTransport` (las fixtures `make_client` y `load_fixture` están en `tests/conftest.py`). Cubre al menos: paginación, campos opcionales vacíos, ID estable y que una segunda corrida no duplica.
5. **Ficha:** crea `docs/platforms/<fuente>.md` (o una sección en `job-boards.md` si es una bolsa simple) con: endpoint, campos usados, términos de uso, límite de consultas y cómo se respeta, si requiere login y fecha de verificación.
6. **Preset:** si la fuente sirve para un preset, agrégala a su `targets.yaml` en `src/jobbot/templates/presets/<preset>/`.

## Agregar un preset

Un preset es un punto de partida para un país o un tipo de búsqueda.

1. Crea `src/jobbot/templates/presets/<pais>-<area>/` (por ejemplo `mexico-it`) con:
   - `settings.yaml`: el bloque `region` (`country`, `country_code`, `country_slug`, `utc_offset`, `timezone`).
   - `search.yaml`: familias de roles (con `label` y `cv`), `title.exclude`, `description.exclude` y `location` (`local`, `local_exclude`, `remote_ok`, `remote_reject`).
   - `targets.yaml`: empresas y bolsas **verificadas** (que respondan y tengan vacantes del país). Para Workday, verifica cada una con `scripts/probe_workday.py`.
2. Comenta en los YAML lo que no sea obvio, con la fecha de verificación.
3. Agrega un test en `tests/test_setup.py` que cargue el preset y verifique que cada fuente recibe su país (como el de `costa-rica-it`). Si el país no está en `src/jobbot/templates/grill/countries.yaml`, agrégalo para que `grill setup-profile` lo ofrezca.
4. Agrega el preset a la tabla de presets de `README.md` y `README.es.md`.
5. **Sin datos personales:** nada de ciudades de residencia, empleadores o historial de una persona. Un preset describe un mercado, no a alguien.

## Agregar un tema o un detector de grill-me

### Tema de entrevista

Un tema es un archivo `src/jobbot/templates/grill/<tema>.yaml` con la clave `questions`, y se corre con `uv run jobbot grill <tema>`. El modelo es `setup-profile.yaml`.

| Campo | Para qué |
| :--- | :--- |
| `topic`, `title`, `intro` | Nombre, título y texto inicial |
| `id`, `ask` | Identificador y texto de cada pregunta |
| `options` o `text: true` | Opciones cortas (se eligen por letra) o respuesta libre |
| `optional` | Una respuesta libre puede quedar vacía |
| `other` | La opción que pide escribir una respuesta libre (p. ej. "Otro") |
| `recommended`, `reason` | Respuesta recomendada y su motivo. **Solo en preferencias:** un dato sobre el usuario nunca lleva recomendada |
| `depends_on` | Se pregunta en una ronda posterior, cuando esas preguntas tienen respuesta |
| `when` | Solo se pregunta si una respuesta previa fue esa |
| `apply` | Nombre de la función de `src/jobbot/grill/apply.py` (`APPLIERS`) que convierte la respuesta en cambios |

Ejemplo de una pregunta:

```yaml
topic: disponibilidad
title: "Tu disponibilidad"
intro: "Unas preguntas sobre horarios. Enter acepta la recomendada."
questions:
  - id: nights
    ask: "¿Aceptas turnos nocturnos?"
    options: ["Sí", "No", "Solo temporalmente"]
    recommended: "Sí"
    reason: "Muchos puestos de soporte de entrada rotan turnos."
    apply: shifts_nights
```

- Un valor nuevo de `apply` necesita su función en `APPLIERS`. Usa `Plan.set`, `Plan.delete` o `Plan.edit_list`: solo calculan el cambio, que la CLI muestra antes de preguntar "¿Los guardo? [s/N]".
- Los archivos del usuario se editan con `ruamel.yaml`, que conserva sus comentarios.
- Agrega tests en `tests/test_grill.py`: rondas y dependencias, que los datos sobre el usuario no tengan recomendada y los cambios que produce cada respuesta.

### Detector

Los detectores viven en `src/jobbot/grill/signals.py` y corren después de cada `jobbot daily` (`refresh`):

- Cada detector devuelve propuestas con `key` única (p. ej. `skill:<nombre>`), `kind`, `question`, `options`, `recommended` y `reason`. La clave evita que una pregunta se repita.
- Agrega el detector a la lista de propuestas de `refresh` y su efecto a `answer`. Cada opción debe decir con claridad qué hace; responder aplica solo eso.
- Es determinista: mismas entradas, mismas preguntas. Sin red y sin modelo de lenguaje.
- Respeta el máximo global de 3 preguntas nuevas por día.
- Si la pregunta es sobre un dato del usuario, no lleva recomendada.
- Tiene tests en `tests/test_grill.py` con una base temporal.
- Se documenta en la tabla de detectores de `docs/architecture.md`.

## Escaneo de privacidad

`scripts/privacy_scan.py` revisa todos los archivos que git versiona (o versionaría) y falla si encuentra:

- Correos fuera de los dominios de ejemplo (`example.invalid`, `example.com`), de los remitentes de los sitios de empleo y de `users.noreply.github.com`.
- Carpetas de usuario de Windows distintas del marcador `C:\Users\<Usuario>`.
- Firmas automáticas de herramientas en commits o textos.
- Cualquier término de tu lista personal, si la pasas.

```bash
uv run python scripts/privacy_scan.py                                  # archivos versionados
uv run python scripts/privacy_scan.py --history                        # también cada commit, con autor y correo
uv run python scripts/privacy_scan.py --denylist "$HOME/jobbot-denylist.txt"   # tus términos personales
```

**Lista personal:** un archivo de texto con un término por línea (tu nombre, tu ciudad, tu correo, tus empleadores…). Guárdalo **fuera del repositorio**: contiene justo los datos que protege. El escaneo nunca imprime el término encontrado, solo el archivo, la línea y el número del término.

Reglas para no romperlo:

- **Fixtures con datos inventados.** Si copias una respuesta real de una API o un correo de alerta, reemplaza nombres de personas, correos, teléfonos e IDs personales. Para ejemplos usa "Alex Ejemplo", `dariel@example.invalid` y empresas como "Acme Corp" o "Ejemplo Servicios TI S.A.".
- **Nada de tu carpeta de datos** en commits, issues ni capturas de pantalla.
- Revisa el autor y el correo de tus commits antes de abrir el pull request: si no quieres publicar tu correo, usa el correo `noreply` que ofrece GitHub.

## Mensajes de commit

- En inglés, en imperativo y cortos (hasta ~72 caracteres en el título): `Add Recruitee source`, `Fix Workday facet lookup for tenants without country`.
- Un cambio lógico por commit.
- Si hace falta contexto, agrégalo en el cuerpo del mensaje: qué cambia y por qué.

## Checklist del pull request

- [ ] `uv run pytest` pasa sin red.
- [ ] `uv run ruff check .` y `uv run ruff format --check src tests scripts` pasan.
- [ ] `uv run python scripts/privacy_scan.py` pasa (idealmente también con `--history` y tu `--denylist`): sin datos personales, rutas reales ni credenciales.
- [ ] Fuente nueva: términos revisados, límites declarados, fixture anonimizada, test y ficha en `docs/platforms/`.
- [ ] Decisión de arquitectura nueva: ADR en `docs/decisions.md`.
- [ ] Documentación actualizada (README, guía o ficha) si cambia el uso.
- [ ] `ROADMAP.md` actualizado si el cambio completa o agrega un plan.
