# Guía de inicio

Esta guía explica, paso a paso, cómo instalar JobBot, preparar tu perfil y usarlo cada día. Está pensada para alguien que no programa.

- Los comandos son para **PowerShell**, la terminal de Windows. Para abrirla: menú Inicio → escribe "PowerShell" → Enter.
- En Linux y macOS casi todo es igual; las diferencias están en la sección [13](#13-linux-y-macos).
- Donde veas `<Usuario>`, va el nombre de tu usuario de Windows.

## 1. Qué hace y qué no

| JobBot sí | JobBot no |
| :--- | :--- |
| Revisa sitios de empleo de empresas, bolsas con API pública y, si lo activas, las alertas que llegan a tu Gmail | Postular por ti ni llenar formularios |
| Descarta lo que no encaja (seniority, ubicación, requisitos imposibles) y guarda el motivo | Entrar a tus cuentas de LinkedIn, Indeed u otros sitios |
| Detecta la misma vacante en varias fuentes | Evadir CAPTCHAs ni bloqueos anti-bot |
| Te muestra las vacantes que encajan, con su enlace y qué CV subir | Enviar, borrar ni modificar correos |
| Lleva la cuenta de postulaciones, entrevistas y rechazos en un panel con botones | Subir tus datos a ningún servidor |

El flujo es: **JobBot encuentra, filtra y te dice qué CV usar; tú postulas en el sitio y lo marcas en el panel.**

## 2. Instalar lo necesario (una sola vez)

JobBot necesita dos programas: **uv** (instala Python y las dependencias) y **Git** (descarga el proyecto y sus actualizaciones).

```powershell
winget install --id astral-sh.uv -e      # uv
winget install --id Git.Git -e           # Git
```

Si `winget` no existe en tu Windows, instala uv con su instalador oficial y Git desde <https://git-scm.com/download/win>:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Cierra PowerShell, ábrelo de nuevo y verifica:

```powershell
uv --version
git --version
```

No hace falta instalar Python aparte: uv descarga Python 3.11 o superior si no lo tienes.

## 3. Descargar JobBot

```powershell
cd $HOME\Documents
git clone https://github.com/<usuario>/jobbot.git
cd jobbot
uv sync
```

`uv sync` instala todo lo necesario en la carpeta `.venv` del proyecto. La primera vez tarda unos minutos.

**Sin Git:** en la página del repositorio, **Code → Download ZIP**, descomprímelo en `Documents\jobbot` y corre `uv sync` dentro de esa carpeta.

**Desde aquí, todos los comandos se corren dentro de la carpeta del proyecto** (`cd $HOME\Documents\jobbot`).

## 4. Crear tu carpeta de datos

Tus datos (configuración, perfil, base de datos, informes) viven en una carpeta aparte del código. Por defecto es `C:\Users\<Usuario>\JobBot`. Se crea con un preset:

```powershell
uv run jobbot init --preset costa-rica-it
```

| Preset | Úsalo si buscas |
| :--- | :--- |
| `costa-rica-it` | Soporte TI en Costa Rica (presencial, híbrido o remoto). Incluye sitios de empleo de multinacionales, elempleo y las bolsas remotas. Es el preset por defecto |
| `remote-latam` | Solo trabajo remoto abierto a Latinoamérica, desde cualquier país de la región. Trae el país vacío: lo completas en la entrevista (sección 5) |

`init` copia las plantillas del preset y **nunca sobrescribe** un archivo que ya existe: si lo corres otra vez, solo agrega lo que falte. El resultado:

```
C:\Users\<Usuario>\JobBot\
├── .env                     valores privados (sección 6)
├── config\
│   ├── settings.yaml        región, puerto del panel, ritmo de consultas, fuentes desactivadas
│   ├── search.yaml          qué puestos buscas y qué se descarta
│   └── targets.yaml         empresas y bolsas que se consultan
├── profile\
│   ├── facts.yaml           experiencia, educación, habilidades
│   ├── answers.yaml         modalidad, turnos, disponibilidad
│   ├── resumes\             it-support.yaml, data-ai.yaml (texto de cada CV) y checks.yaml
│   └── private\             contact.yaml, compensation.yaml (y luego las credenciales de Gmail)
└── data\                    base de datos, informes y registros (se llenan al usar JobBot)
```

**El perfil que copia `init` es un ejemplo ficticio** (una persona llamada "Alex Ejemplo" que trabaja en "Acme Corp"). Reemplázalo con tus datos antes de postular: la entrevista de la sección 5 cambia lo básico y el resto se edita a mano.

Si corres cualquier otro comando antes de `init`, JobBot responde "No encuentro tu configuración en …" y te muestra el comando para crearla.

### Usar otra ubicación (opcional)

Si quieres la carpeta en otro lugar (por ejemplo, otro disco), define la variable de usuario `JOBBOT_HOME` **antes** de correr `init`:

```powershell
[Environment]::SetEnvironmentVariable("JOBBOT_HOME", "D:\JobBot", "User")
```

Cierra y abre PowerShell para que tome el cambio. Si ya tenías datos, mueve la carpeta completa a la nueva ubicación. El acceso directo y la tarea diaria de Windows también usan esa variable.

En el resto de esta guía, `$HOME\JobBot` es la ubicación por defecto. Si la cambiaste, usa tu ruta.

## 5. Completar tu perfil con la entrevista

```powershell
uv run jobbot grill setup-profile
```

JobBot te entrevista para llenar tu perfil y tu búsqueda:

- Pregunta por **rondas**, con preguntas **numeradas** (Q1, Q2…). Una pregunta que depende de otra llega en la ronda siguiente.
- Cada pregunta trae **opciones cortas** con letra. Respondes con la letra o con el texto de la opción.
- Las preferencias traen una **respuesta recomendada** con su motivo: **Enter la acepta**.
- Las preguntas sobre ti (país, idiomas, nombre, correo) **no traen recomendada**: JobBot no adivina ni inventa datos tuyos. Si eliges "Otro", te pide escribirlo. El teléfono es opcional: Enter lo deja vacío.
- Al final te muestra **cada cambio** y pregunta **"¿Los guardo? [s/N]"**. No escribe nada hasta que respondas `s`. Los comentarios de tus archivos se conservan.

Ejemplo simplificado:

```
Ronda de 5 preguntas:

Q1 - ¿En qué país vives y buscas trabajo?
   a) Costa Rica
   b) México
   ...
Q2 - ¿Qué tipo de puesto buscas?
   a) Soporte TI
   b) Soporte TI y datos
   c) Solo datos
   Recomendada: Soporte TI: Empieza por una familia: menos ruido en tus pendientes. ...
```

Qué pregunta y qué cambia:

| Pregunta | Qué cambia |
| :--- | :--- |
| País | `settings.yaml: region` y el país de `facts.yaml` |
| Tipo de puesto | Qué familias de roles quedan en `search.yaml` |
| Nivel máximo (solo nivel 1, hasta nivel 2, cualquiera salvo senior) | Exclusiones de nivel en `search.yaml: title.exclude` |
| Modalidad (solo remoto, o también presencial o híbrido en tu zona) | `search.yaml: location.local` (vacío si es solo remoto) |
| Zona local (solo si aceptas presencial) | Agrega tus ciudades o cantones a `location.local` |
| Idiomas | Deja de excluir títulos en portugués si lo hablas |
| Nombre, correo y teléfono | `facts.yaml` (nombre) y `private/contact.yaml` (correo y teléfono) |

Puedes repetir la entrevista cuando quieras; vuelve a mostrar los cambios antes de guardar.

## 6. Configuración privada (`.env`)

El archivo `.env` de tu carpeta de datos guarda valores privados. Ábrelo con:

```powershell
notepad $HOME\JobBot\.env
```

| Variable | Para qué | ¿Obligatoria? |
| :--- | :--- | :--- |
| `JOBBOT_CONTACT_EMAIL` | Correo que JobBot incluye en su `User-Agent` para identificarse con honestidad ante los sitios | No, pero se recomienda |

La plantilla trae un correo de ejemplo. Cámbialo por el tuyo o deja el valor vacío:

```
JOBBOT_CONTACT_EMAIL=dariel@example.invalid
```

- `.env` está dentro de tu carpeta de datos: nunca forma parte del repositorio.
- Una variable de entorno real con el mismo nombre tiene prioridad sobre `.env`.
- `JOBBOT_HOME` no se puede poner en `.env`, porque es la que dice dónde está ese archivo.

## 7. Primera búsqueda

```powershell
uv run jobbot discover
```

Tarda de 1 a 3 minutos. Cada fuente muestra una línea como esta:

```
workday:acme       nuevas OK:   2  descartadas:   30  ya vistas:    0  [title_not_target_role=28, description_excluded=2]
```

| Texto | Significa |
| :--- | :--- |
| `nuevas OK` | Vacantes nuevas que pasaron los filtros. Aparecen en el panel y en `jobbot jobs` |
| `descartadas` | Vacantes nuevas que no encajan; entre corchetes, los motivos más comunes |
| `ya vistas` | Vacantes de corridas anteriores; no se repiten |
| `omitida: consultada hace poco` | La fuente pide pocas consultas al día y se respetó su límite |
| `sin configurar` | La fuente necesita un paso tuyo, por ejemplo completar el país en `settings.yaml: region` (JobBot no lo adivina) o configurar Gmail. No es un error |

**Frecuencia recomendada:** una o dos veces al día. Más seguido no encuentra nada nuevo y solo carga a los sitios.

## 8. El panel

```powershell
uv run jobbot panel
```

Se abre en tu navegador, en `http://127.0.0.1:8765`. Solo funciona en tu computadora.

| Pestaña | Para qué | Botones |
| :--- | :--- | :--- |
| **Pendientes** | Vacantes que encajan y no has resuelto, las publicadas más recientemente primero | **Ya postulé**, **No me interesa** |
| **Postuladas** | A las que ya postulaste | **Me llamaron**, **Rechazo / sin respuesta**, **Deshacer** |
| **Entrevistas** | Empresas que te llamaron | **Rechazo** |
| **Cerradas** | Rechazos o sin respuesta | |
| **Descartadas** | Lo que filtró JobBot o descartaste tú en el último mes (`max_age_days`), con el motivo | **Volver a pendientes**, **Quitar de la lista** |
| **Decisiones** | Preguntas cortas de JobBot sobre tu búsqueda (ver abajo) | Una por opción |

- **Postular:** el título abre la vacante. "CV a subir" abre el PDF recomendado y **copiar ruta** copia su ubicación: en la ventana de subir archivo del sitio, pega con Ctrl+V y Enter.
- **"Ya postulaste: #N":** aparece si una vacante abierta se parece a una a la que ya postulaste (misma empresa y título desde otra fuente o ubicación).
- **Buscar ahora:** busca en todas las fuentes en ese momento y muestra el avance.
- **Filtros:** por familia de roles; **100 % remoto** o **Nacionales** (presencial o híbrido en tu país); **Últimas 24 h** (solo las publicadas hace poco); **En español** (anuncios escritos en español); **Entrada** (primer empleo: pasantías, trainee, junior, new grad y early career); y una búsqueda por puesto, empresa o lugar que no distingue tildes.
- **Fecha de publicación:** cada vacante dice "publicada hace X". Con "~", la fecha es aproximada: Workday solo da una edad ("hace 3 días") y en las alertas de LinkedIn se usa la fecha del correo. Indeed y CompuTrabajo por correo no traen fecha: "fecha de publicación desconocida".
- **"Nueva":** publicada en las últimas 24 h (`fresh_hours`). Si la fecha es desconocida, vista por primera vez en las últimas 24 h.
- **"Recomendada por LinkedIn, puede ser vieja":** llegó en un correo de LinkedIn que no es de tus alertas guardadas (empleos similares, sugerencias bajo una confirmación). Mira la fecha en el anuncio antes de postular. Estas van al final de la lista.
- **"La bolsa la marca senior":** Get on Board, Jobicy o Himalayas la etiquetaron senior, pero se publicó hace poco y el título no lo dice, así que pasa igual. Lee los requisitos y decide.
- **Ordenar por:** fecha de publicación (por defecto: lo más nuevo primero), cuándo la vio JobBot o empresa. El panel recuerda tu elección.
- **"Remoto sin país: confirma que acepten…":** el anuncio está en español y dice solo "Remoto". Suele estar abierto a toda la región, pero no siempre: confírmalo antes de postular.
- **"Pide estar matriculado: revisa si aceptan egresados":** la descripción pide ser estudiante activo. Si ya terminaste la carrera, mira si también aceptan egresados o recién graduados antes de postular.
- **Quitar de la lista:** en Descartadas, saca para siempre una vacante que ya revisaste (con **Deshacer** unos segundos). Una nueva búsqueda o un cambio de filtros no la vuelve a traer.
- **Buscar en LinkedIn:** botones que abren en tu navegador la búsqueda de LinkedIn de cada palabra clave, con lo más nuevo primero. Por defecto, solo lo publicado en las últimas 24 h; un grupo puede tener su propio rango. JobBot no entra a LinkedIn: solo arma el enlace. Las palabras clave están en `targets.yaml: linkedin_searches`.
- **Si te equivocas:** después de cada acción aparece **Deshacer** durante unos segundos.
- **Cierre:** el panel se apaga solo 10 minutos después de que cierres la pestaña. Si la página dice que se cerró, ábrelo de nuevo.

### La pestaña Decisiones

Después de cada corrida diaria, JobBot revisa tu base y puede dejarte **hasta 3 preguntas nuevas por día**. Nunca repite una pregunta, y el informe diario dice cuántas tienes pendientes.

| Situación | Opciones | Qué hace cada una |
| :--- | :--- | :--- |
| Una postulación lleva 21 días sin novedades | **Sí, cerrarla** (recomendada) / **Esperar más** | Cerrarla la pasa a Cerradas como sin respuesta; si después te llaman, la pasas a Entrevistas |
| Una fuente falló en sus últimas 3 búsquedas | **Desactivarla** (recomendada) / **Seguir intentando** | Desactivarla la agrega a `settings.yaml: disabled_sources`; para reactivarla, quítala de esa lista |
| Una habilidad aparece en el 30 % o más (y al menos 5) de tus vacantes pendientes con descripción, y tu perfil no la menciona | **Sí, la he usado en el trabajo** / **La estoy aprendiendo** / **No** | Las dos primeras la agregan a `facts.yaml` (`skills.work` o `skills.self_study`). No hay recomendada: es un dato sobre ti |

- Cada opción dice qué hace, y al responder JobBot aplica solo eso.
- También puedes responderlas en la terminal con `uv run jobbot grill pendientes`.
- Las reglas son fijas y no usan ningún modelo de lenguaje. La lista de habilidades que revisa está en `src/jobbot/templates/grill/skills.yaml`.

### Acceso directo en el escritorio (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install_shortcut.ps1
```

- Crea el acceso directo **JobBot** en tu escritorio, que abre el panel sin ventana de consola. Si el panel ya está abierto, solo abre la página.
- Si tus datos no están en `$HOME\JobBot`, el acceso directo usa la variable de usuario `JOBBOT_HOME` (sección 4).
- Para quitarlo, borra "JobBot" del escritorio.

### Probar sin tocar tus datos

Para mirar el panel sobre una copia de la base:

```powershell
Copy-Item $HOME\JobBot\data\jobbot.db $HOME\JobBot\data\copia.db
uv run jobbot panel --db $HOME\JobBot\data\copia.db --port 8766
```

## 9. Búsqueda automática cada día

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install_schedule.ps1 -At 07:00
```

- Crea la tarea **"JobBot - busqueda diaria"** en el **Programador de tareas**, que corre `jobbot daily` a esa hora (por medio de `scripts\windows\run_daily.ps1`). Si la computadora estaba apagada, corre apenas la enciendas.
- Si tus datos están en otra carpeta y no definiste `JOBBOT_HOME`, agrega `-JobbotHome D:\ruta\JobBot`.
- Si hay vacantes nuevas o una fuente necesita atención, aparece una **notificación de Windows**. Al hacer clic se abre el informe. Si no hay nada nuevo, no te molesta.
- Para cambiar la hora, corre el mismo comando con otra hora en `-At`.
- El registro de cada corrida queda en `data\logs\daily-<fecha>.log` dentro de tu carpeta de datos.

Para quitar la tarea:

```powershell
Unregister-ScheduledTask -TaskName 'JobBot - busqueda diaria' -Confirm:$false
```

Comandos útiles:

```powershell
uv run jobbot daily              # correr la búsqueda diaria ahora
uv run jobbot report --open      # regenerar el informe y abrirlo, sin consultar sitios
```

### Linux y macOS

Ver la sección [13](#13-linux-y-macos).

## 10. Alertas por correo (opcional)

JobBot puede leer las alertas de empleo que LinkedIn, CompuTrabajo, Indeed, elempleo y Torre te envían a Gmail, y las confirmaciones de postulación de esos sitios. Solo lee: **no puede enviar, borrar, marcar como leído ni modificar nada**. La configuración toma unos 15 minutos y se hace una sola vez.

### 10.1 Instalar el extra

```powershell
uv sync --extra gmail
```

Si también usas el extra de CV en PDF, instálalos juntos: `uv sync --extra gmail --extra resumes` (ver la sección [14](#14-actualizar-jobbot)).

### 10.2 Crear un proyecto en Google Cloud

1. Entra a <https://console.cloud.google.com/> con la cuenta de Gmail que recibe las alertas.
2. En el selector de proyectos (arriba) → **Nuevo proyecto** → nombre `JobBot` → **Crear**. Es gratis.
3. Con el proyecto `JobBot` seleccionado: **APIs y servicios → Biblioteca** → busca **Gmail API** → **Habilitar**.

### 10.3 Configurar la pantalla de consentimiento

En **APIs y servicios → Pantalla de consentimiento de OAuth** (en la consola nueva se llama **Google Auth Platform**):

1. **Información de la app:** nombre `JobBot`; correo de asistencia: tu correo.
2. **Público (Audience):** tipo **Externo**.
3. **Información de contacto:** tu correo → **Crear**.
4. En **Público → Usuarios de prueba**, agrega **tu propio correo**.

### 10.4 Crear la credencial

1. **APIs y servicios → Credenciales** (o **Google Auth Platform → Clientes**) → **Crear credenciales → ID de cliente de OAuth**.
2. Tipo de aplicación: **App de escritorio**. Nombre: `JobBot` → **Crear**.
3. **Descargar JSON**.
4. Renómbralo a `gmail_credentials.json` y guárdalo en `C:\Users\<Usuario>\JobBot\profile\private\`.

Ese archivo es tuyo y privado: no lo compartas ni lo subas a ningún repositorio.

### 10.5 Autorizar a JobBot

```powershell
uv run jobbot gmail-login
```

Se abre el navegador. Elige tu cuenta. Google mostrará **"Google no verificó esta app"**: es normal, porque la app es tuya y no está publicada. Haz clic en **Avanzado → Ir a JobBot (no seguro) → Continuar**. Al terminar, la terminal dice `Gmail autorizado en modo solo lectura para <tu correo>`.

El permiso que se pide es únicamente `gmail.readonly`.

### 10.6 Activar las fuentes de correo

Las fuentes de correo vienen apagadas. Abre `config\targets.yaml` y, en el bloque `email_alerts`, cambia:

```yaml
email_alerts:
  enabled: true
```

Desde la siguiente búsqueda aparecen las líneas `email:linkedin`, `email:computrabajo`, etc.

### 10.7 Vencimiento cada 7 días

Mientras la app esté en estado **Prueba** (*Testing*), Google vence la autorización más o menos cada 7 días. Cuando la corrida diaria o el panel digan `token de Gmail vencido`, repite:

```powershell
uv run jobbot gmail-login
```

### 10.8 Crear las alertas y validarlas

Sigue [`docs/platforms/email-alerts.md`](platforms/email-alerts.md): cómo crear las alertas en cada sitio, cómo probar que JobBot las lee (`alerts-sample`, `alerts-status`) y qué hacer si no llegan.

### Quitar el acceso

En <https://myaccount.google.com/permissions> → JobBot → **Quitar acceso**. Después pon `enabled: false` en `targets.yaml` y, si quieres, borra `gmail_token.json` de `profile\private\`.

## 11. CV en PDF (opcional)

JobBot puede generar tus CV en PDF desde archivos de texto, para que todas las versiones digan lo mismo.

```powershell
uv sync --extra resumes
uv run playwright install chromium
```

Si también usas el extra de Gmail: `uv sync --extra gmail --extra resumes`.

- El texto de cada variante vive en `profile\resumes\<variante>.yaml` (`it-support.yaml` y `data-ai.yaml`), en español e inglés. Las variantes coinciden con el `cv:` de cada familia de roles en `search.yaml`.
- Tu contacto sale de `profile\private\contact.yaml`.
- **Para cambiar tu CV no se edita el PDF:** se edita el `.yaml` y se regenera.

```powershell
uv run jobbot resumes                          # todas las variantes
uv run jobbot resumes --variant it-support     # solo una variante
uv run jobbot resumes --lang es                # solo un idioma
```

Los PDF quedan en `profile\resumes\<variante>_<es|en>.pdf`. El comando avisa si un CV pasa del máximo de páginas de `settings.yaml` (`resumes.max_pages`).

### Revisiones del CV (`checks.yaml`)

`profile\resumes\checks.yaml` tiene dos listas de reglas, `forbidden` (lo que ningún CV puede decir) y `required` (lo que cada CV debe decir al menos una vez). Cada regla es un `pattern` (expresión regular, sin distinguir mayúsculas) y un `reason` que explica la regla.

Si algún CV rompe una regla, **`jobbot resumes` no genera ningún PDF** y muestra la frase y el motivo. Sirve, por ejemplo, para que una certificación que todavía estás preparando nunca aparezca como obtenida:

```yaml
forbidden:
  - pattern: '\bXYZ-100\b(?![^.\n]*(preparaci[oó]n|preparation))'
    reason: "XYZ-100 todavía no está aprobada: solo puede aparecer como en preparación."
required: []
```

La plantilla trae reglas de ejemplo: reemplázalas por las tuyas.

## 12. Ajustar qué busca JobBot

Los tres archivos de `config\` se editan con el Bloc de notas o cualquier editor de texto. Usa espacios, no tabulaciones. Las expresiones van entre comillas simples.

### `search.yaml`: qué puestos y qué se descarta

Los patrones son expresiones regulares que no distinguen mayúsculas ni tildes ("Técnico" y "tecnico" son iguales).

| Clave | Qué hace |
| :--- | :--- |
| `role_families.<familia>.label` | Nombre que se muestra en el panel y el informe (opcional) |
| `role_families.<familia>.priority` | `primary` o `secondary`. Si un título encaja en dos familias, gana la principal |
| `role_families.<familia>.cv` | Variante de CV de esa familia |
| `role_families.<familia>.include` / `exclude` | El título debe coincidir con algún `include` y con ningún `exclude` |
| `any_role_companies` | Empresas donde te sirve cualquier puesto: sus vacantes pasan sin familia (la seniority y la ubicación siguen aplicando) |
| `title.exclude` | Exclusiones para todas las familias: seniority (Senior, Lead, Manager), nivel 3 o más, ventas |
| `description.exclude` | Requisitos imposibles en la descripción (autorización de seguridad, ciudadanía de EE. UU.) |
| `description.seniority` | Etiqueta de seniority que ponen Get on Board, Jobicy y Himalayas. Descarta la vacante, salvo que se haya publicado hace menos de `fresh_hours` |
| `max_age_days` | Días máximos desde la publicación (o, sin fecha, desde que JobBot la vio). Lo más viejo se descarta al llegar y las pendientes que pasan el límite van a Descartadas. 0 = sin límite |
| `fresh_hours` | Horas para que una vacante cuente como reciente (24): filtro **Últimas 24 h**, sección del informe y búsquedas de LinkedIn |
| `location.local` | Lugares donde aceptas presencial o híbrido |
| `location.local_exclude` | Lugares dentro de esa zona que no aceptas |
| `location.remote_ok` / `remote_reject` | Regiones de remoto elegibles o no para ti |

Después de cambiar los filtros, reaplícalos a lo que ya está guardado. No consulta internet:

```powershell
uv run jobbot rescreen
```

Las vacantes que se reabren se juzgan solo por título y ubicación. En la siguiente búsqueda, JobBot descarga una vez la descripción de las que vienen de sitios de empresas y les aplica `description.exclude`. Lo que marcaste a mano ("No me interesa", "Volver a pendientes") no cambia.

Si un filtro descarta algo que sí querías, mira el motivo con `uv run jobbot jobs --status skipped` y ajusta la regla.

### `settings.yaml`: región y comportamiento

| Clave | Qué hace |
| :--- | :--- |
| `region.country`, `country_code`, `country_slug` | Tu país, como lo escriben los sitios (`Costa Rica`), su código ISO de 3 letras (`CRI`) y su forma para URLs (`costa-rica`) |
| `region.utc_offset`, `region.timezone` | Desfase horario estándar (`-6`) y zona IANA (`America/Costa_Rica`); muchas vacantes remotas filtran por zona horaria |
| `disabled_sources` | Fuentes que las búsquedas saltan, con el nombre que muestra la salida (p. ej. `workday:acme`) |
| `panel.port` | Puerto del panel (por defecto 8765) |
| `http.min_interval_s` | Pausa mínima entre consultas al mismo sitio |
| `notifications.windows_toast` | Notificación de Windows en la corrida diaria |
| `resumes.max_pages` | Máximo de páginas por CV |

Las fuentes toman el país de `region`, salvo que su entrada en `targets.yaml` diga otro. Si no hay país, la fuente se reporta como `sin configurar` en vez de adivinarlo. La entrevista `grill setup-profile` llena `region` por ti.

### `targets.yaml`: empresas y bolsas

Para agregar una empresa:

1. Entra a su página de empleos y abre cualquier vacante.
2. Mira la URL:
   - Contiene `myworkdayjobs.com` → es **Workday**. Pruébala con:
     ```powershell
     uv run python scripts/probe_workday.py https://empresa.wd5.myworkdayjobs.com/NombreDelSitio
     ```
     Si responde, copia la línea que imprime y pégala bajo `workday:`.
   - Contiene `boards.greenhouse.io/<token>` → agrégala bajo `greenhouse:` con ese token.
   - Contiene `jobs.lever.co/<slug>` → agrégala bajo `lever:` con ese slug.
   - Contiene `jobs.ashbyhq.com/<board>` → agrégala bajo `ashby:` con ese board.
   - Contiene `icims.com` → **iCIMS**: filtra el portal por tu país y agrégala bajo `icims:`; ver [`docs/platforms/icims.md`](platforms/icims.md).
   - Si la empresa publica «Remote» sin país y contrata en cualquiera, agrega `remote_scope: "Worldwide"` (ver [`docs/platforms/greenhouse-lever.md`](platforms/greenhouse-lever.md)).
   - URLs tipo `/go/<nombre>/<id>/` → probablemente es **SuccessFactors**; ver [`docs/platforms/successfactors.md`](platforms/successfactors.md).
   - Otro sistema → abre un issue para proponer una fuente nueva.

Los botones **Buscar en LinkedIn** del panel salen de `linkedin_searches`: una lista de `keywords` y el `geo_id` de tu país en LinkedIn. Para encontrar el `geo_id`, busca empleos en LinkedIn, elige tu país en el filtro de ubicación y copia el número que aparece después de `geoId=` en la URL. El de Costa Rica es `101739942`.

Cada grupo acepta dos opciones más (ADR-024):

- `experience`: el filtro de nivel de LinkedIn. Los valores son `internship` (Pasantía), `entry` (Sin experiencia) y `associate` (Algo de responsabilidad).
- `hours`: cuántas horas hacia atrás busca el grupo. Por defecto usa `fresh_hours`. Como salen pocas pasantías por día, `168` (una semana) les va mejor.

```yaml
  - label: "Primer empleo · Costa Rica"
    geo_id: "101739942"
    experience: [internship, entry]
    hours: 168
    keywords: [trainee, pasantía, internship, junior developer]
```

## 13. Linux y macOS

| Tema | Linux / macOS |
| :--- | :--- |
| Instalar uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Instalar Git | Linux: el gestor de paquetes (p. ej. `sudo apt install git`). macOS: `xcode-select --install` |
| Carpeta de datos | `~/JobBot` |
| Cambiar ubicación | Agrega `export JOBBOT_HOME="$HOME/ruta/JobBot"` a `~/.bashrc` o `~/.zshrc` |
| Editar archivos | `nano ~/JobBot/.env` o tu editor preferido |
| Abrir el informe | Linux: `xdg-open ~/JobBot/data/reports/latest.html`. macOS: `open ~/JobBot/data/reports/latest.html` |
| Notificaciones y acceso directo | No hay; usa el informe y `uv run jobbot panel` |

### Corrida diaria con cron

`scripts/run_daily.sh` corre `jobbot daily` y guarda el registro en `data/logs/daily-<fecha>.log` de tu carpeta de datos. Busca uv en las rutas de instalación habituales, porque cron arranca con un `PATH` mínimo.

Abre tu tabla de cron con `crontab -e` y agrega una línea (ajusta la ruta del proyecto):

```
0 7 * * * sh "$HOME/jobbot/scripts/run_daily.sh"
```

- Corre todos los días a las 7:00.
- Si usas otra carpeta de datos, agrega la variable al inicio: `0 7 * * * JOBBOT_HOME="$HOME/ruta/JobBot" sh "$HOME/jobbot/scripts/run_daily.sh"`.
- A diferencia de la tarea de Windows, cron no corre una tarea perdida si la computadora estaba apagada; en ese caso, corre `uv run jobbot daily` a mano o usa `anacron` (Linux) o `launchd` (macOS).

## 14. Actualizar JobBot

```powershell
cd $HOME\Documents\jobbot
git pull
uv sync --extra gmail --extra resumes     # repite los mismos extras que usas
```

- `uv sync` deja instalado exactamente lo que pides: si omites un extra, lo desinstala. Repite siempre los mismos `--extra`.
- Tu carpeta de datos no se toca.
- Si una versión nueva trae plantillas nuevas, `uv run jobbot init --preset <tu-preset>` agrega los archivos que falten sin sobrescribir los tuyos.
- **Sin Git:** descarga el ZIP nuevo, reemplaza la carpeta del código (no la de datos) y corre `uv sync`.

## 15. Respaldo

Todo lo tuyo está en una carpeta, así que el respaldo es copiarla. Cierra antes el panel y no lo hagas mientras corre la búsqueda diaria.

```powershell
Copy-Item -Recurse $HOME\JobBot D:\Respaldos\JobBot-2026-11-03
```

En Linux y macOS:

```bash
cp -a ~/JobBot "/ruta/respaldos/JobBot-$(date +%F)"
```

- El respaldo contiene datos sensibles (contacto, salario, credenciales de Gmail). Guárdalo en un lugar seguro y no lo subas a sitios públicos.
- Para restaurar, copia la carpeta de vuelta a su lugar. Si Gmail pide autorizar de nuevo, corre `uv run jobbot gmail-login`.

## 16. Problemas comunes

| Síntoma | Causa probable | Solución |
| :--- | :--- | :--- |
| `uv` no se reconoce | La terminal no ve la instalación nueva | Cerrar y abrir PowerShell, o reinstalar uv |
| "No encuentro tu configuración en …" | No existe la carpeta de datos o `JOBBOT_HOME` apunta a otro lugar | Correr `uv run jobbot init --preset <preset>` o revisar `JOBBOT_HOME` |
| PowerShell no deja correr un script | Política de ejecución de Windows | Usar `powershell -ExecutionPolicy Bypass -File ...` como en esta guía |
| `sin configurar: falta el país (region.country)` u otro dato de `region` | `settings.yaml: region` está vacío (pasa con `remote-latam`) | `uv run jobbot grill setup-profile` o completar `region` a mano |
| `jobbot jobs` dice "Sin resultados" | Ninguna vacante nueva pasó los filtros (pasa seguido) | Revisar `--status skipped`; agregar empresas |
| `HTTPStatusError 422` o `404` en una fuente Workday | Cambió el nombre del sitio de empleo | Volver a probar la URL con `probe_workday.py` y actualizar `targets.yaml` |
| `429` en una fuente | El sitio pidió bajar el ritmo | Esperar; JobBot ya respeta `Retry-After`. Subir `http.min_interval_s` |
| Una fuente falla todos los días | El sitio cambió o bloquea | Responder la pregunta de la pestaña Decisiones, o agregarla a `disabled_sources` |
| No aparecen líneas `email:...` | Las fuentes de correo están apagadas | `email_alerts.enabled: true` en `targets.yaml` (sección 10.6) |
| `email:...  sin configurar` | Falta el extra `gmail`, la credencial o la autorización de Gmail (el mensaje dice cuál) | Secciones 10.1, 10.4 y 10.5 |
| `token de Gmail vencido` | Pasaron unos 7 días en modo Prueba | `uv run jobbot gmail-login` |
| El panel no abre: puerto en uso | Otro programa usa el 8765 | `uv run jobbot panel --port 8766` o cambiar `panel.port` |
| `jobbot resumes` dice que falta el extra | No instalaste el extra de CV | `uv sync --extra resumes` y `uv run playwright install chromium` |
| "No se generó ningún PDF" | Un CV rompe `checks.yaml` | Corregir la frase que indica el mensaje en el `.yaml` del CV |
