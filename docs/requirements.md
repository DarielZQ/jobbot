# Requisitos

## Objetivo

Ayudar a una persona que busca empleo en soporte TI (y en áreas cercanas, como datos) a encontrar las vacantes que encajan con su perfil, decidir rápido y llevar el seguimiento de sus postulaciones, desde su propia computadora.

Tres condiciones mandan sobre todo lo demás:

- **El usuario postula.** JobBot descubre, filtra y asiste; nunca envía una postulación (ADR-019).
- **Las cuentas del usuario no corren riesgo.** Nada de automatizar sitios que lo prohíben ni de evadir protecciones (ADR-003, ADR-005).
- **Los datos del usuario no salen de su computadora**, salvo las consultas a las fuentes que él configura.

## Requisitos funcionales

| ID | Requisito | Estado |
| :--- | :--- | :--- |
| FR-01 | Descubrir vacantes desde las fuentes de `config/targets.yaml` sin login: APIs públicas, JSON de sitios de empleo y listados públicos. | Disponible |
| FR-02 | Normalizar cada vacante a un modelo común (`Job`) y guardarla en SQLite dentro de `JOBBOT_HOME`. | Disponible |
| FR-03 | Detectar duplicados: la misma vacante en la misma fuente (`ats` + `ats_job_id`) y entre fuentes (`dedupe_key`). Avisar si una pendiente parece una vacante a la que el usuario ya postuló desde otra fuente o ubicación. | Disponible |
| FR-04 | Aplicar filtros duros (título, seniority, ubicación, requisitos excluyentes) definidos en `config/search.yaml`, guardando el motivo de descarte. | Disponible |
| FR-05 | Listar vacantes y estadísticas por CLI, y generar un informe HTML sin usar la red. | Disponible |
| FR-06 | Recomendar la variante de CV de cada vacante según la familia de roles y el idioma del anuncio. | Disponible |
| FR-07 | Leer alertas de empleo de LinkedIn, CompuTrabajo, Indeed y elempleo desde Gmail, en solo lectura (ADR-012). | Disponible (extra `gmail`) |
| FR-08 | Marcar como postuladas las vacantes cuya confirmación llega por correo (ADR-018). | Disponible (extra `gmail`) |
| FR-09 | Registrar lo que hace el usuario: postulaciones manuales, entrevistas, rechazos y descartes, con opción de deshacer. | Disponible |
| FR-10 | Panel local en el navegador con las pestañas Pendientes, Postuladas, Entrevistas, Cerradas, Descartadas y Decisiones. | Disponible |
| FR-11 | Corrida diaria programada: búsqueda, informe y aviso si hay novedades (Windows: `scripts/windows/`; Linux y macOS: cron con `scripts/run_daily.sh`). | Disponible; aviso de escritorio solo en Windows |
| FR-12 | Detener una fuente que bloquea al bot (403, challenge) y reportarlo, sin reintentar con trucos. Una fuente sin país configurado se reporta como "sin configurar" en vez de adivinar. | Disponible |
| FR-13 | `jobbot init --preset <nombre>`: crear la carpeta de datos desde plantillas, sin sobrescribir archivos existentes. | Disponible |
| FR-14 | `jobbot grill setup-profile`: entrevista que llena el perfil y la búsqueda sin inventar datos, mostrando el cambio y pidiendo confirmación antes de escribir. | Disponible |
| FR-15 | Detectores de grill-me después de cada corrida diaria, con un máximo de 3 preguntas nuevas por día que nunca se repiten; se responden en el panel o con `jobbot grill pendientes`. | Disponible |
| FR-16 | Generar los CV en PDF desde YAML y no generar ninguno si alguno incumple `profile/resumes/checks.yaml`. | Disponible (extra `resumes`) |
| FR-17 | Desactivar una fuente sin borrarla de `targets.yaml` (`settings.yaml: disabled_sources`). | Disponible |
| FR-18 | Reporte semanal del embudo: descubiertas → postuladas → respuestas → entrevistas. | Planeado |

## Fuera de alcance

- Enviar postulaciones, llenar formularios o subir archivos en nombre del usuario.
- Iniciar sesión en LinkedIn, Indeed u otros sitios de empleo.
- Evadir CAPTCHAs, fingerprinting o bloqueos (sin stealth, sin proxies rotativos).
- Funcionar como servicio en la nube o compartir datos entre usuarios.

## Requisitos no funcionales

- **Cumplimiento:** sin evasión anti-bot (ADR-003). LinkedIn e Indeed solo por las alertas que el usuario recibe en su correo (ADR-005, ADR-013). Cada fuente respeta los límites que publica.
- **Veracidad:** ningún texto que genere JobBot (CV, cambios de perfil) puede contener datos que no estén en `profile/`. Si falta un dato, se pregunta.
- **Idempotencia:** volver a correr una búsqueda o releer los mismos correos no duplica vacantes ni cambia lo ya resuelto.
- **Cortesía de red:** intervalo mínimo por host, respeto de `Retry-After`, `User-Agent` honesto con contacto opcional.
- **Privacidad:** datos personales, credenciales y sesiones solo en `JOBBOT_HOME`; registros sin datos personales; el repositorio no contiene datos de ningún usuario.
- **Local:** todo corre en la computadora del usuario; el panel solo escucha en `127.0.0.1`.
- **Portabilidad:** Windows, Linux y macOS con Python 3.11 o superior. Lo específico de Windows (tarea programada, acceso directo, notificaciones) es opcional.
- **Testeable sin red:** cada fuente tiene fixtures y tests con `httpx.MockTransport`.

## Criterios de aceptación de la versión pública

- `jobbot init` + `jobbot discover` funcionan en una carpeta de datos nueva en Windows, Linux y macOS, y una segunda corrida no crea duplicados.
- `uv run pytest` pasa sin red y `uv run ruff check .` pasa, en CI con los tres sistemas operativos.
- El escaneo de privacidad de CI pasa: ningún archivo versionado contiene datos de un usuario, rutas reales ni credenciales.
- `jobbot grill setup-profile` nunca escribe sin confirmación y nunca completa un dato que el usuario no dio.
- Los detectores de grill-me no generan más de 3 preguntas nuevas por día ni repiten una pregunta resuelta.
