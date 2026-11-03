# Estrategia de búsqueda

Este documento explica el **por qué** de la búsqueda que traen los presets: soporte TI en Costa Rica y trabajo remoto en Latinoamérica. Los valores que usa JobBot (palabras clave, exclusiones, empresas, sitios) viven en `config/search.yaml` y `config/targets.yaml` de tu carpeta de datos; sus plantillas, en `src/jobbot/templates/presets/`.

## Roles objetivo (familias, ADR-009)

| Familia | Prioridad | Roles | CV |
| :--- | :--- | :--- | :--- |
| `it_support` | principal | Soporte TI L1/L2, Help Desk, Service Desk, Technical Support, Desktop Support, técnico de centro de datos, Cloud Support Associate, pasantías y trainee de TI. **Puestos cercanos:** soporte en sitio y de campo, gestión de activos TI, ITSM (ServiceNow y similares), identidades y accesos, monitoreo y NOC. **Siguiente escalón:** administración de sistemas, Microsoft 365, endpoints y redes | `it-support` |
| `data_ai` | secundaria | Analista de datos, reportes y BI, gestión y calidad de datos, master data, ETL y operaciones de datos, RPA, anotación de datos; ciencia o ingeniería de datos **solo** con marca de nivel de entrada (junior, associate, intern); soporte y administración de bases de datos | `data-ai` |

- **Por qué los puestos cercanos:** quien empieza en help desk suele tener experiencia que también sirve en soporte de campo, inventario de equipos, gestión de tickets, altas de usuarios o monitoreo. Son puertas de entrada parecidas con menos competencia.
- **Por qué el siguiente escalón:** algunos puestos de sistemas, redes o bases de datos aceptan perfiles junior. Como no se filtra por años pedidos, conviene leer los requisitos de cada uno.
- **Homónimos:** cada familia excluye títulos de otras áreas que usan las mismas palabras (redes sociales, monitoreo transaccional, *market access*, control de accesos físico, cámaras).
- **Familias y CV:** cada familia apunta a una variante de CV. Puedes renombrarlas con `label`, cambiar sus patrones o agregar familias nuevas.

### Seniority

- Se excluyen títulos con seniority (Senior, Lead, Manager, Architect, Principal, Supervisor) y de nivel 3 en adelante.
- **El nivel 2 pasa** (II, Tier 2, L2, Mid, Semi Senior): muchas personas con poca experiencia compiten bien por ellos.
- **No se filtra por años de experiencia pedidos:** las empresas suelen exagerarlos. La decisión queda en manos del usuario al leer el anuncio.
- Se excluyen **requisitos imposibles** de cumplir desde Latinoamérica: autorización de seguridad (*security clearance*) o ciudadanía de EE. UU.

## Prioridad de plataformas (ADR-007)

| # | Fuente | Por qué | Modo en JobBot |
| :---: | :--- | :--- | :--- |
| 1 | **Sitios de empleo de multinacionales** (Workday, SuccessFactors, amazon.jobs) | Concentran los roles L1/L2 y Service Desk de las zonas francas y parques empresariales | Descubrimiento directo |
| 2 | **Agencias de staffing TI** | Colocan mucho soporte L1/L2 y son puerta de entrada a multinacionales | Manual: muchas reciben CV por su propio canal |
| 3 | **LinkedIn** | El mayor volumen de vacantes TI y donde buscan los reclutadores; sus términos prohíben automatizar (ADR-005) | Alertas por correo (extra `gmail`) |
| 4 | **CompuTrabajo** | Mucho volumen de help desk, soporte y BPO; bloquea bots (ADR-011) | Alertas por correo |
| 5 | **BPO de soporte bilingüe** | Encaje directo con Technical Support Representative; contratan seguido | Según su ATS (p. ej. SuccessFactors); varios sin endpoint público |
| 6 | **elempleo** | Empresas locales y bancos | Listado público (máx. cada 12 h) + alertas por correo (ADR-013) |
| 7 | **Get on Board, Remotive, Jobicy, Himalayas** | Remoto con foco en Latinoamérica o abierto a cualquier país (ADR-017) | APIs públicas, con los límites de cada una |
| 8 | **Greenhouse / Lever / Ashby** | Fáciles de consultar, pero sobre todo roles de EE. UU. con seniority | Descubrimiento directo de las empresas que agregues |
| 9 | **Indeed** | Mucho volumen; Cloudflare y sus términos impiden leerlo directo | Alertas por correo |

Descartadas:

| Fuente | Motivo |
| :--- | :--- |
| Wellfound | Startups que buscan ingenieros con experiencia; protección anti-bot |
| Encuentra24 | Clasificados con poco volumen de TI; contacto por WhatsApp |
| RemoteOK, We Work Remotely | Pocos roles junior de soporte elegibles desde Latinoamérica; se puede reevaluar |
| Jobgether | Sus términos prohíben extraer y guardar sus datos sin autorización escrita; además actúa de intermediario al postular. Se puede usar a mano |
| FlexJobs, Underdog.io, BuiltIn, Remote.co, Jobright, Sprout, Handshake | De pago o con vacantes sobre todo para EE. UU. |

## Otras fuentes útiles (manuales)

| Fuente | Por qué | Cómo usarla |
| :--- | :--- | :--- |
| **ANE** (ane.cr) | Plataforma pública y gratuita de intermediación de empleo de Costa Rica | Registrarse y subir el CV; poco esfuerzo |
| **Perfil de LinkedIn** | Los reclutadores buscan perfiles, no solo reciben postulaciones | Mantener el perfil al día y las alertas activas. Cuando se pueda, postular en el sitio de la empresa en vez de Easy Apply |
| **Preferencias de CompuTrabajo** | Si el área de interés del perfil no es Informática/Soporte, las alertas traen puestos ajenos | Ajustar el área de interés o darse de baja de las promociones |
| **Programas de formación de empresas de servicios TI** | Algunas empresas abren cohortes de soporte para quienes inician | Seguir sus sitios de empleo; si usan un ATS soportado, agregarlas a `targets.yaml` |
| Agregadores (Jooble y similares) | Repiten vacantes de otras fuentes | Baja prioridad |

## Trabajo remoto (ADR-017)

| Tipo | Qué significa | Valoración |
| :--- | :--- | :--- |
| **Planilla local** | Una empresa con entidad en tu país te contrata como empleado y te deja trabajar 100 % desde casa | La mejor opción: seguridad social, aguinaldo y vacaciones como cualquier empleado |
| **Empleador de registro** (*employer of record*: Deel, Remote, Oyster y similares) | Una empresa extranjera te contrata a través de un tercero que sí tiene entidad en tu país | Buena: quedas como empleado local |
| **Contratista independiente** | Facturas tus servicios; tú pagas impuestos y seguridad social | Con cuidado: sin aguinaldo ni vacaciones pagadas. Compara el monto neto y confirma los impuestos con un contador |

En Costa Rica, un contratista independiente se inscribe en Hacienda y en la CCSS como trabajador independiente.

**Estafas:** nadie legítimo cobra por postular, pide comprar equipo por adelantado ni hace toda la entrevista solo por chat.

En el panel, cada vacante dice "100 % remoto", "Nacional" (presencial o híbrido dentro de `location.local`) u "Otro país", y se puede filtrar por las dos primeras. Los híbridos cuentan como nacionales.

## Perfil de nivel inicial

Los presets están pensados para quien empieza o tiene poca experiencia:

- **Pasantías, trainee y programas early career sí entran**, pero solo de TI, soporte, infraestructura o cloud. Conviene priorizar las que tienen pago y posibilidad de contratación.
- **Ubicación:** `location.local` define dónde aceptas presencial o híbrido, y `location.local_exclude` lo que queda fuera aunque esté en tu país. El preset de Costa Rica acepta por defecto cualquier ubicación del país; `search.yaml` trae comentado un ejemplo de `local_exclude` para quien solo trabaja en el Gran Área Metropolitana. `jobbot grill setup-profile` puede dejar `local` vacío (solo remoto) o agregar tus ciudades.

## Principios

- **Calidad sobre volumen.** En mercados pequeños los reclutadores se conocen, y las postulaciones irrelevantes dañan la marca personal. Mejor pocas postulaciones bien elegidas.
- **Idioma por vacante:** vacante en inglés → CV y respuestas en inglés; en español → español. JobBot lo sugiere en cada vacante.
- **No repetir postulaciones:** el aviso "Ya postulaste: #N" y las confirmaciones por correo evitan postular dos veces a la misma vacante desde otra fuente.
- **Cómo agregar una empresa:** buscar su página de empleos, identificar el ATS por la URL (tabla en [`architecture.md`](architecture.md#detección-de-ats-por-url)) y agregarla a `targets.yaml`. Para Workday, verificarla antes con `uv run python scripts/probe_workday.py <url>`.
