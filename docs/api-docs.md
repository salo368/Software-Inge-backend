# Documentación de API automática (Swagger / OpenAPI)

Cada servicio con rutas HTTP publica, en su misma URL de API Gateway:

| Ruta | Qué es |
|---|---|
| `GET /<prefijo>/docs` | Swagger UI (con botón **Authorize** para pegar un bearer y probar) |
| `GET /<prefijo>/openapi.json` | el documento OpenAPI 3.0 |

`<prefijo>` es el que comparten las rutas del servicio: `/auth`, `/admin-auth`,
`/processes`, `/payments`, `/files`, `/forms`, `/banks`, `/signatures`. La URL
base sale del output `HttpApiUrl` del stack `cdts-<stage>-<servicio>`.

**No hay que mantenerla a mano.** `backend/utils/build-functions.js` ya recorre
el `function.yml` de cada lambda en cada deploy; ahora, además, genera el
documento y registra la lambda que lo sirve. Un endpoint nuevo aparece solo en
el siguiente deploy.

## Qué se deduce solo

| Dato | De dónde sale |
|---|---|
| ruta, método, nombre | `events.httpApi` del `function.yml` |
| descripción | `description` del `function.yml` |
| quién puede llamar | `@require_auth(AuthsTypes.USER / INTERNAL)` o `@require_any_auth` del handler (sin decorador = público) |
| campos de entrada | `body.get("x")`, `body["x"]`, `query_params.get("x")`, `params.get("x")`, `uuid_param(…, "x", …)`, `pagination_params(…)` |
| errores | `HandledError("mensaje", status)` del handler, más los de `uuid_param` / `pagination_params` / `request_params`, y los 401 de la auth |

Con `request_params` un campo puede ir por query string o por body; se muestra
donde el método lo lleva normalmente (query en GET, body en POST/PUT/PATCH/DELETE).

## Qué no se deduce

- **Tipos de los campos** (salvo `page` / `page_size`) y **el payload de éxito**:
  quedan abiertos en vez de adivinados. Para eso siguen las guías `docs/*-api.md`.
- Errores con mensaje dinámico (f-strings, variables) o lanzados por código
  que el handler no contiene.
- Para que un handler quede bien documentado: usar `HandledError("literal", status)`
  y los helpers de `libs/utils/params.py`.

## Dónde está y dónde no

- **dev y staging:** sí. **`pro`: no se crea la lambda** ni el documento (para no
  exponer el mapa de endpoints). Se cambia en `DOCS_DISABLED_STAGES` de
  `utils/build-functions.js`.
- La página `/docs` y el JSON **no piden token** (el botón Authorize es para
  probar los endpoints, no para ver la documentación).
- Un servicio sin rutas HTTP (p. ej. `migrations`) no genera nada.
- Si la generación falla, el deploy **no se rompe**: avisa por consola y el
  servicio se despliega sin docs.

## Piezas

| Archivo | Rol |
|---|---|
| `backend/utils/openapi.js` | arma el documento a partir de las funciones y el código de cada handler |
| `backend/utils/build-functions.js` | lo escribe en `src/_docs/openapi.json` (ignorado por git, se empaqueta con `src/**`) e inyecta la lambda `api_docs` |
| `backend/libs/utils/openapi_docs.py` | la lambda: sirve el HTML de Swagger UI (versión fijada) y el JSON. No importa nada de DB |
| `backend/tests/test_openapi_generation.py` | prueba el generador de punta a punta con un servicio falso |
