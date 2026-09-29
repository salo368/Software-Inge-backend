"""Genera `metamodelo.drawio` (Diagrama 1 · Metamodelo estructural).

El diagrama se describe aquí de forma declarativa (clases UML, paquetes,
relaciones y notas) para que el layout sea reproducible. Para cambiar el
diagrama se puede editar este script y regenerar, o abrir el `.drawio`
directamente en diagrams.net / draw.io y editarlo a mano.

    python3 docs/arquitectura/gen_metamodelo.py

OJO: regenerar sobrescribe `metamodelo.drawio`. Si ya lo editaste a mano en
draw.io, sigue editándolo allí y exporta PNG/PDF desde Archivo → Exportar.
"""
from __future__ import annotations

import html
from pathlib import Path
from xml.sax.saxutils import quoteattr

OUT = Path(__file__).with_name("metamodelo.drawio")

# --------------------------------------------------------------------------
# Paleta (una familia de color por categoría del metamodelo)
# --------------------------------------------------------------------------
C = {
    "deploy": ("#dae8fc", "#6c8ebf"),   # unidades desplegables
    "lambda": ("#d5e8d4", "#82b366"),   # Lambda y sus tipos
    "file":   ("#fff2cc", "#d6b656"),   # archivos (artefactos)
    "libs":   ("#e1d5e7", "#9673a6"),   # código compartido libs/
    "tool":   ("#f5f5f5", "#666666"),   # tooling / testing transversal
    "aws":    ("#ffe6cc", "#d79b00"),   # recursos / eventos AWS
    "root":   ("#e6e6e6", "#4d4d4d"),   # proyecto / raíz
}
PKG = {  # relleno de los paquetes (más claro que las clases)
    "deploy": ("#f3f7fd", "#6c8ebf"),
    "lambda": ("#f4faf3", "#82b366"),
    "file":   ("#fffbef", "#d6b656"),
    "libs":   ("#f8f4fa", "#9673a6"),
    "tool":   ("#fafafa", "#999999"),
    "aws":    ("#fff8f0", "#d79b00"),
    "backend": ("#ffffff", "#333333"),
}

HEADER = 40
ROW = 20
DIV = 8
PAD = 4

cells: list[str] = []
geo: dict[str, tuple[float, float, float, float]] = {}   # id -> abs (x, y, w, h)
parent_of: dict[str, str] = {}
_seq = [0]


def _nid(prefix: str) -> str:
    _seq[0] += 1
    return f"{prefix}{_seq[0]}"


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def _rel(parent: str, x: float, y: float) -> tuple[float, float]:
    if parent == "1":
        return x, y
    px, py, _, _ = geo[parent]
    return x - px, y - py


def _vertex(cid, value, style, x, y, w, h, parent="1", extra=""):
    rx, ry = _rel(parent, x, y)
    cells.append(
        f'<mxCell id="{cid}" value={quoteattr(value)} style={quoteattr(style)} '
        f'vertex="1" parent="{parent}"{extra}>'
        f'<mxGeometry x="{rx:g}" y="{ry:g}" width="{w:g}" height="{h:g}" as="geometry"/></mxCell>'
    )
    geo[cid] = (x, y, w, h)
    parent_of[cid] = parent


# --------------------------------------------------------------------------
# Primitivas UML
# --------------------------------------------------------------------------
def package(cid, label, x, y, w, h, kind, parent="1", dashed=False, font=13, tab_right=False):
    fill, stroke = PKG[kind]
    tab = min(w - 20, max(90, int(len(label) * font * 0.56) + 24))
    style = (
        "shape=folder;fontStyle=1;tabWidth={tab};tabHeight=26;tabPosition={tp};html=1;"
        "whiteSpace=wrap;verticalAlign=top;align={al};spacingLeft=10;spacingRight=10;spacingTop=3;"
        "container=1;collapsible=0;recursiveResize=0;fontSize={font};"
        "fillColor={fill};strokeColor={stroke};{dash}"
    ).format(tab=tab, font=font, fill=fill, stroke=stroke,
             tp="right" if tab_right else "left", al="right" if tab_right else "left",
             dash="dashed=1;dashPattern=6 4;" if dashed else "")
    _vertex(cid, esc(label), style, x, y, w, h, parent)


def uml_class(cid, name, x, y, w, kind, stereo=None, attrs=(), ops=(),
              abstract=False, parent="1"):
    """Clase UML con compartimentos (atributos | operaciones)."""
    fill, stroke = C[kind]
    title = f"<i>{esc(name)}</i>" if abstract else esc(name)
    st = []
    if abstract:
        st.append("«abstract»")
    if stereo:
        st.append(f"«{stereo}»")
    head = ""
    if st:
        head = f'<span style="font-weight:normal;font-size:11px">{esc(" ".join(st))}</span><br>'
    label = f"{head}<b>{title}</b>"
    start = HEADER if st else 26

    h = start + PAD
    h += len(attrs) * ROW
    if attrs and ops:
        h += DIV
    h += len(ops) * ROW
    if not attrs and not ops:
        h = start + 10

    style = (
        f"swimlane;fontStyle=0;align=center;verticalAlign=top;childLayout=stackLayout;"
        f"horizontal=1;startSize={start};horizontalStack=0;resizeParent=1;resizeParentMax=0;"
        f"resizeLast=0;collapsible=0;marginBottom={PAD};html=1;whiteSpace=wrap;fontSize=12;"
        f"fillColor={fill};strokeColor={stroke};swimlaneFillColor=#ffffff;"
    )
    _vertex(cid, label, style, x, y, w, h, parent)

    row_style = (
        "text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=6;"
        "spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];"
        "portConstraint=eastwest;html=1;whiteSpace=wrap;fontSize=11;"
    )
    cy = start
    for i, a in enumerate(attrs):
        rid = f"{cid}_a{i}"
        cells.append(
            f'<mxCell id="{rid}" value={quoteattr(fmt_row(a))} style={quoteattr(row_style)} '
            f'vertex="1" parent="{cid}"><mxGeometry y="{cy}" width="{w}" height="{ROW}" '
            f'as="geometry"/></mxCell>')
        cy += ROW
    if attrs and ops:
        cells.append(
            f'<mxCell id="{cid}_div" value="" style="line;strokeWidth=1;fillColor=none;align=left;'
            f'verticalAlign=middle;spacingTop=-1;spacingLeft=3;spacingRight=3;rotatable=0;'
            f'labelPosition=right;points=[];portConstraint=eastwest;strokeColor={stroke};" '
            f'vertex="1" parent="{cid}"><mxGeometry y="{cy}" width="{w}" height="{DIV}" '
            f'as="geometry"/></mxCell>')
        cy += DIV
    for i, o in enumerate(ops):
        rid = f"{cid}_o{i}"
        cells.append(
            f'<mxCell id="{rid}" value={quoteattr(fmt_row(o))} style={quoteattr(row_style)} '
            f'vertex="1" parent="{cid}"><mxGeometry y="{cy}" width="{w}" height="{ROW}" '
            f'as="geometry"/></mxCell>')
        cy += ROW


def fmt_row(text: str) -> str:
    """Escapa HTML y resalta en gris las anotaciones entre ⟨ ⟩."""
    out = esc(text)
    out = out.replace("⟨", '<span style="color:#777777">').replace("⟩", "</span>")
    return out


def note(cid, text, x, y, w, h, parent="1"):
    style = (
        "shape=note;size=14;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
        "spacingLeft=8;spacingRight=10;spacingTop=4;fontSize=11;"
        "fillColor=#fffde7;strokeColor=#c9b458;"
    )
    body = "<br>".join(_note_line(t) for t in text.split("\n"))
    _vertex(cid, body, style, x, y, w, h, parent)


def _note_line(t: str) -> str:
    t = esc(t)
    # Negrita para el identificador de regla (R1, R2, ...)
    if t.startswith("R") and " " in t and t.split(" ", 1)[0][1:].isdigit():
        rid, rest = t.split(" ", 1)
        return f"<b>{rid}</b> {rest}"
    return t


def text(cid, value, x, y, w, h, size=12, bold=False, color="#000000", align="left", parent="1"):
    style = (f"text;html=1;whiteSpace=wrap;align={align};verticalAlign=middle;fontSize={size};"
             f"fontColor={color};{'fontStyle=1;' if bold else ''}strokeColor=none;fillColor=none;")
    _vertex(cid, value, style, x, y, w, h, parent)


def rect(cid, x, y, w, h, fill, stroke, parent="1", value=""):
    _vertex(cid, value, f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};",
            x, y, w, h, parent)


# --------------------------------------------------------------------------
# Relaciones
# --------------------------------------------------------------------------
EDGE_BASE = ("html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;fontSize=11;"
             "labelBackgroundColor=#ffffff;strokeColor=#333333;fontColor=#333333;")
KIND = {
    "comp":  "startArrow=diamondThin;startFill=1;startSize=16;endArrow=none;",
    "aggr":  "startArrow=diamondThin;startFill=0;startSize=16;endArrow=none;",
    "gen":   "endArrow=block;endFill=0;endSize=14;",
    "dep":   "endArrow=open;endFill=0;endSize=10;dashed=1;dashPattern=8 4;",
    "assoc": "endArrow=open;endFill=0;endSize=10;",
    "link":  "endArrow=none;dashed=1;dashPattern=2 3;strokeColor=#b0a050;",
}


def anchor(cid, side, at=None):
    """Punto absoluto sobre el borde de `cid`. side ∈ T,B,L,R; `at` = coord absoluta
    a lo largo del borde (x para T/B, y para L/R); None = centro."""
    x, y, w, h = geo[cid]
    if side in "TB":
        px = x + w / 2 if at is None else at
        return (px, y if side == "T" else y + h)
    py = y + h / 2 if at is None else at
    return (x if side == "L" else x + w, py)


def _frac(cid, pt):
    x, y, w, h = geo[cid]
    return (round((pt[0] - x) / w, 4), round((pt[1] - y) / h, 4))


def edge(src, tgt, kind, sp=None, tp=None, pts=(), label=None, src_m=None, tgt_m=None,
         label_pos=0.0, label_off=(0, 0), style_extra=""):
    """`sp`/`tp`: (side, at) para fijar el punto de salida/entrada."""
    eid = _nid("e")
    style = EDGE_BASE + KIND[kind] + style_extra
    if sp:
        fx, fy = _frac(src, anchor(src, *sp))
        style += f"exitX={fx};exitY={fy};exitDx=0;exitDy=0;exitPerimeter=0;"
    if tp:
        fx, fy = _frac(tgt, anchor(tgt, *tp))
        style += f"entryX={fx};entryY={fy};entryDx=0;entryDy=0;entryPerimeter=0;"
    points = "".join(f'<mxPoint x="{px:g}" y="{py:g}"/>' for px, py in pts)
    arr = f'<Array as="points">{points}</Array>' if pts else ""
    cells.append(
        f'<mxCell id="{eid}" value={quoteattr(esc(label) if label else "")} '
        f'style={quoteattr(style)} edge="1" parent="1" source="{src}" target="{tgt}">'
        f'<mxGeometry x="{label_pos}" relative="1" as="geometry">'
        f'<mxPoint x="{label_off[0]}" y="{label_off[1]}" as="offset"/>{arr}</mxGeometry></mxCell>'
    )
    # Multiplicidades: en el extremo exacto de la relación, del lado por el que
    # la línea toca la clase (T/B/L/R), para que no se confundan entre ramas.
    place = {"T": ("left", "bottom", 5, -3), "B": ("left", "top", 5, 3),
             "L": ("right", "bottom", -4, -2), "R": ("left", "bottom", 4, -2)}
    for mult, pos, side in ((src_m, -1, sp[0] if sp else "B"), (tgt_m, 1, tp[0] if tp else "T")):
        if not mult:
            continue
        align, valign, dx, dy = place[side]
        cells.append(
            f'<mxCell id="{_nid("m")}" value={quoteattr(esc(mult))} '
            f'style="edgeLabel;resizable=0;html=1;align={align};verticalAlign={valign};fontSize=11;'
            f'fontStyle=1;labelBackgroundColor=none;" vertex="1" connectable="0" parent="{eid}">'
            f'<mxGeometry x="{pos}" relative="1" as="geometry">'
            f'<mxPoint x="{dx}" y="{dy}" as="offset"/></mxGeometry></mxCell>'
        )
    return eid


# ==========================================================================
#                                CONTENIDO
# ==========================================================================
W_TOTAL = 2580

# ---- Título ---------------------------------------------------------------
text("title", "<b>Diagrama 1 · Metamodelo estructural del backend CDTS</b>",
     20, 8, 1500, 34, size=24)
text("subtitle",
     "UML — diagrama de clases usado como <b>metamodelo</b>: cada clase es un <i>tipo</i> de "
     "elemento del repositorio (servicio, Lambda, archivo, librería…). Los servicios y Lambdas "
     "reales son <i>instancias</i> de estas clases.",
     20, 44, 1500, 36, size=13, color="#333333")

# ---- Proyecto (raíz) ----------------------------------------------------------
uml_class("proyecto", "Proyecto CDTS", 40, 110, 320, "root", stereo="repositorio",
          attrs=["+ stages: {dev, pro}",
                 "+ runtime: AWS Lambda + API Gateway HTTP API",
                 "+ framework: Serverless Framework v3 · python3.12"])
uml_class("infra", "InfraDeProyecto", 470, 110, 360, "root", stereo="carpetas de la raíz",
          attrs=[".github/workflows/  ⟨CI/CD por bloque⟩",
                 "scripts/ci/  ⟨plan-deploy.sh, lint-migrations.py⟩",
                 "scripts/iam/  ⟨IAM bootstrap⟩",
                 "docs/ · .cursor/rules/"],
          ops=["cambio aquí ⇒ 0 deploys"])
note("n_global",
     "R12 Solo existen dos stages: dev y pro (nunca prod, staging, qa…).\n"
     "R13 API Gateway HTTP API v2 (- httpApi:); CORS una sola vez en provider.httpApi.\n"
     "Todo recurso AWS se nombra cdts-<stage>-<servicio>-<función>.",
     900, 110, 560, 76)

# ---- Leyenda -------------------------------------------------------------------
package("legend", "Leyenda", 1560, 20, 1000, 250, "tool", font=12)
lx, ly = 1580, 62
items = [("deploy", "Unidad desplegable"), ("lambda", "Lambda"), ("file", "Archivo / artefacto"),
         ("libs", "Código compartido libs/"), ("tool", "Tooling / testing"),
         ("aws", "AWS (runtime / eventos)")]
for i, (k, lbl) in enumerate(items):
    yy = ly + i * 30
    rect(f"lg_sw{i}", lx, yy, 34, 20, C[k][0], C[k][1], parent="legend")
    text(f"lg_t{i}", lbl, lx + 44, yy - 2, 170, 24, size=11, parent="legend")
rel_items = [
    ("comp", "Composición — «está hecho de» (rombo en el todo)"),
    ("aggr", "Agregación — «registra / agrupa»"),
    ("gen", "Generalización — «es un tipo de»"),
    ("dep", "Dependencia — «usa / importa»"),
    ("assoc", "Asociación — «disparada por / invoca»"),
    ("link", "Anclaje de una nota (regla Rn)"),
]
for i, (k, lbl) in enumerate(rel_items):
    yy = ly + 10 + i * 30
    eid = _nid("lg_e")
    st = EDGE_BASE.replace("edgeStyle=orthogonalEdgeStyle;", "") + KIND[k]
    cells.append(
        f'<mxCell id="{eid}" value="" style={quoteattr(st)} edge="1" parent="legend">'
        f'<mxGeometry relative="1" as="geometry">'
        f'<mxPoint x="{1800 - 1560}" y="{yy - 20}" as="sourcePoint"/>'
        f'<mxPoint x="{1890 - 1560}" y="{yy - 20}" as="targetPoint"/></mxGeometry></mxCell>')
    text(f"lg_r{i}", esc(lbl), 1900, yy - 12, 330, 24, size=11, parent="legend")
notation = [
    "<b>«x»</b> estereotipo = ruta o archivo real",
    "<i><b>Cursiva</b></i> + «abstract» = clase abstracta",
    "<b>/ atributo</b> = derivado por convención",
    "<b>+ op()</b> = operación / función expuesta",
    '<span style="color:#777777">texto gris</span> = aclaración',
    "<b>Rn</b> = regla (ver metamodelo.md §4)",
]
for i, t in enumerate(notation):
    text(f"lg_n{i}", t, 2250, ly - 2 + i * 30, 300, 24, size=11, parent="legend")

# ---- backend/ -----------------------------------------------------------------
BK = (20, 300, W_TOTAL - 20, 1560 + 500 + 20 - 300)
package("backend", "backend/  —  runtime serverless: todo lo que se empaqueta y despliega en AWS",
        *BK, "backend", font=14)

# ============ Z1-izq · Unidades desplegables =====================================
package("p_deploy", "Unidades desplegables", 40, 345, 1160, 665, "deploy", parent="backend")

uml_class("compose", "Composición", 60, 405, 250, "deploy", stereo="serverless-compose.yml",
          attrs=["+ services: {nombre → path}", "+ dependsOn: [bloque]"], parent="p_deploy")
uml_class("bloque", "BloqueDesplegable", 440, 400, 360, "deploy", abstract=True,
          attrs=["+ nombre: str",
                 "/ stackName = cdts-<stage>-<nombre>",
                 "+ runtime = python3.12",
                 "+ iam · environment ⟨rutas SSM⟩"],
          ops=["= 1 stack CloudFormation independiente"], parent="p_deploy")
uml_class("plataforma", "BloqueDePlataforma", 330, 640, 300, "deploy", stereo="platform/<name>/",
          attrs=["+ responsabilidad técnica transversal",
                 "+ se despliega ANTES que los servicios",
                 "+ un cambio ⇒ redeploy de todos"], parent="p_deploy")
uml_class("servicio", "ServicioDeDominio", 680, 640, 330, "deploy", stereo="services/<name>/",
          attrs=["+ dominio: 1 bounded context",
                 "+ pipeline: validate → test → deploy → integration"], parent="p_deploy")
uml_class("carpeta", "CarpetaDeContenido", 60, 648, 225, "deploy", stereo="sql/ · files/",
          attrs=["+ ruta: str"], parent="p_deploy")
uml_class("archivo_c", "ArchivoDeContenido", 60, 760, 225, "deploy", abstract=True,
          attrs=["cambio ⇒ deploy del bloque"], parent="p_deploy")
uml_class("migracion", "MigraciónSQL", 325, 875, 250, "deploy",
          stereo="YYYYMMDDHHMMSS_desc.sql",
          attrs=["+ up: SQL  ⟨obligatorio⟩", "+ down: SQL  ⟨opcional⟩",
                 "+ inmutable una vez mergeado"], parent="p_deploy")
uml_class("asset", "AssetEstático", 60, 875, 245, "deploy", stereo="files/**",
          attrs=["+ key relativa ⟨la BD guarda la key⟩", "+ sync → bucket S3 público"],
          parent="p_deploy")
note("n_r1",
     "R1 Un servicio NUNCA importa código de otro servicio: se comunica por "
     "lambda_invoke (sync/async), webhook HTTP o presigned URL.\n"
     "R2 Ningún servicio importa código de platform/.",
     680, 760, 330, 84, parent="p_deploy")
note("n_r11",
     "R11 Las migraciones nunca califican schema (dev./pro.), ni hacen SET search_path "
     "ni CREATE/DROP SCHEMA. Un .sql mergeado no se edita (lint-migrations.py).",
     600, 890, 400, 66, parent="p_deploy")

# ============ Z1-der · Archivos del bloque ========================================
package("p_bfiles", "Archivos de un bloque", 1240, 345, 1300, 285, "file", parent="backend")
uml_class("sls", "ServerlessYml", 1255, 440, 290, "file", stereo="serverless.yml",
          attrs=["+ provider ⟨runtime, stage, stackName⟩",
                 "+ environment ⟨rutas SSM, buckets⟩",
                 "+ iam.role.statements",
                 "+ package.patterns ⟨excluye tests⟩",
                 "+ resources ⟨buckets, permisos⟩",
                 "+ functions: ${file(./functions.js):build}"], parent="p_bfiles")
uml_class("fnjs", "FunctionsJs", 1560, 440, 290, "file", stereo="functions.js",
          ops=["+ mirror: copia backend/libs/ → ./libs/",
               "+ build = build-functions(__dirname)"], parent="p_bfiles")
uml_class("reqs", "Requirements", 1865, 440, 195, "file", stereo="requirements.txt",
          attrs=["sqlalchemy · pg8000 · deps"], parent="p_bfiles")
uml_class("data_s", "DataDeServicio", 2075, 440, 195, "file", stereo="data/",
          attrs=["DTOs · schemas · estáticos"], parent="p_bfiles")
uml_class("utils_s", "UtilsDeServicio", 2285, 440, 240, "file", stereo="utils/",
          attrs=["helpers PRIVADOS del bloque", "from utils.x import y"], parent="p_bfiles")

# ============ Z1-der-inf · Tooling, testing y config transversal ===================
package("p_tool", "Tooling, testing y config", 1240, 650, 1135, 360, "tool",
        parent="backend")
uml_class("buildfn", "GeneradorDeFunciones", 1255, 700, 290, "tool",
          stereo="utils/build-functions.js",
          ops=["+ escanear src/{handlers,workers,scheduled}/*",
               "+ validar carpeta snake_case",
               "+ derivar name y handler",
               "+ merge con function.yml"], parent="p_tool")
uml_class("conftest", "Conftest", 1565, 700, 285, "tool", stereo="conftest.py · pytest.ini",
          attrs=["+ stub de boto3 ⟨sin AWS real⟩",
                 "+ flag --integration",
                 "+ fixture load_handler(__file__)",
                 "+ descubre test.py / integration.py"], parent="p_tool")
uml_class("helpers", "IntegrationHelpers", 1865, 700, 280, "tool",
          stereo="tests/integration_helpers.py",
          ops=["+ api_base(service)", "+ query_one(sql, **params)",
               "+ create_test_user_directly()", "+ cleanup_*()  ⟨solo itest-*⟩"], parent="p_tool")
uml_class("tests_x", "TestsTransversales", 1255, 870, 290, "tool", stereo="tests/test_*.py",
          attrs=["parser de migraciones · generador", "utils de servicio"], parent="p_tool")
uml_class("configdata", "ConfigDataGlobales", 2160, 700, 205, "tool", stereo="config/ · data/",
          attrs=["declarativos compartidos", "sin lógica ⟨reservado⟩"], parent="p_tool")

# ============ Z2 · Lambdas ========================================================
package("p_src", "src/<tipo>/<carpeta>/  —  Lambdas", 40, 1045, 2500, 470, "lambda",
        parent="backend")
package("p_trig", "events (function.yml) · AWS", 55, 1085, 250, 320, "aws", parent="p_src",
        dashed=True, font=11)
uml_class("ev_http", "EventoHTTP", 68, 1120, 210, "aws", stereo="API Gateway HTTP API",
          attrs=["+ method, path"], parent="p_trig")
uml_class("ev_async", "EventoAsíncrono", 68, 1215, 210, "aws", stereo="S3 · SQS · SNS · invoke",
          attrs=["+ fuente, payload"], parent="p_trig")
uml_class("ev_sched", "Schedule", 68, 1310, 210, "aws", stereo="EventBridge",
          attrs=["+ rate(...) | cron(...)"], parent="p_trig")

uml_class("l_api", "LambdaAPI", 445, 1110, 285, "lambda", stereo="src/handlers/",
          attrs=["+ endpoint REST ⟨frontend / M2M⟩"], parent="p_src")
uml_class("l_worker", "LambdaWorker", 445, 1205, 285, "lambda", stereo="src/workers/",
          attrs=["+ procesamiento en segundo plano"], parent="p_src")
uml_class("l_cron", "LambdaCronJob", 445, 1300, 285, "lambda", stereo="src/scheduled/",
          attrs=["+ tarea periódica"], parent="p_src")
uml_class("lambda", "Lambda", 810, 1115, 380, "lambda", abstract=True,
          attrs=["+ carpeta: snake_case",
                 "/ nombreAWS = cdts-<stage>-<servicio>-<carpeta-kebab>",
                 "/ handlerPath = src/<tipo>/<carpeta>/handler.handler"],
          ops=["= 1 carpeta = 1 función AWS Lambda"], parent="p_src")
uml_class("aux", "ArchivoAuxiliar", 850, 1315, 300, "file", stereo="*.py",
          attrs=["helpers locales de esa Lambda"], parent="p_src")
note("n_r5",
     "R5 Una carpeta = una Lambda. El tipo lo define la subcarpeta: nada de HTTP en workers/ "
     "ni cron en handlers/.\n"
     "R6 Carpeta en snake_case; name y handler NO se escriben: los deriva build-functions.js.",
     55, 1420, 690, 50, parent="p_src")

uml_class("fnyml", "FunctionConfig", 1270, 1115, 270, "file", stereo="function.yml",
          attrs=["+ description", "+ events", "+ timeout · memorySize", "+ environment",
                 "✗ name · handler ⟨autogenerados⟩"], parent="p_src")
uml_class("testpy", "TestUnitario", 1560, 1115, 290, "file", stereo="test.py",
          attrs=["mocks con monkeypatch · sin AWS/BD", "bloquea el deploy si falla"],
          ops=["+ test_happy_path()", "+ test_validacion_400()", "+ test_falla_de_dominio()"],
          parent="p_src")
uml_class("integpy", "TestIntegración", 1870, 1115, 270, "file", stereo="integration.py",
          attrs=["pytestmark = integration", "solo dev · después del deploy",
                 "block-local · datos itest-*", "no bloquea el deploy"], parent="p_src")
uml_class("handler", "Handler", 2160, 1115, 330, "file", stereo="handler.py",
          attrs=["@handle_exceptions", "[@require_auth | decorador del servicio]"],
          ops=["+ handler(event, context): dict"], parent="p_src")
note("n_r7",
     "R7 test.py obligatorio con ≥ 3 casos: happy path · validación (400) · falla de dominio.\n"
     "R8 integration.py es block-local (no llama APIs de otro bloque), solo en dev, "
     "con datos itest-* y limpieza en finally.\n"
     "R14 test.py e integration.py se excluyen del zip.",
     1560, 1315, 580, 70, parent="p_src")

# ============ Z3 · libs/ ===========================================================
Y3 = 1560          # borde superior del paquete libs/
S = Y3 + 45        # borde superior de los subpaquetes
package("p_libs", "backend/libs/  —  código compartido (utils a nivel general)",
        40, Y3, 2500, 500, "libs", parent="backend")

package("p_core", "libs/core  —  infraestructura técnica", 60, S, 960, 330, "libs",
        parent="p_libs", font=12)
uml_class("logger", "Logger", 80, S + 50, 200, "libs", stereo="logger.py",
          ops=["+ log(level, msg)"], parent="p_core")
uml_class("mailer", "Mailer", 80, S + 140, 200, "libs", stereo="mailer.py",
          ops=["+ send_email(to, subject, html)"], parent="p_core")
uml_class("responses", "Responses", 300, S + 50, 320, "libs", stereo="responses.py",
          attrs=["HandledError(message, status)"],
          ops=["+ generate_response(body, status): dict", "+ @handle_exceptions(handler)"],
          parent="p_core")
uml_class("s3", "S3", 300, S + 195, 320, "libs", stereo="s3.py",
          ops=["+ presign_upload() · presign_download()",
               "+ upload_from_bytes() · head_object()"], parent="p_core")
uml_class("db", "DB", 680, S + 50, 310, "libs", stereo="db.py",
          attrs=["+ engine: SQLAlchemy ⟨pg8000⟩",
                 "+ search_path = <stage>",
                 "+ db_session: DBSession «singleton»"],
          ops=["+ commit() · rollback() · close()"], parent="p_core")

note("n_libs",
     "libs/ NO es una Lambda Layer: functions.js lo copia a ./libs/ (gitignored) dentro "
     "de cada bloque al empaquetar.\n"
     "Por eso un cambio en libs/ es transversal: redespliega TODOS los servicios.",
     60, S + 342, 365, 96, parent="p_libs")

package("p_orm", "libs/orm  —  capa de abstracción de la BD", 1040, S, 690, 440, "libs",
        parent="p_libs", font=12)
uml_class("base", "Base", 1070, S + 50, 290, "libs", stereo="base.py · DeclarativeBase",
          ops=["+ to_dict(): dict"], parent="p_orm")
uml_class("orminit", "RegistroDeModelos", 1410, S + 50, 300, "libs", stereo="__init__.py",
          attrs=["importa TODOS los modelos", "⟨resuelve FKs cruzadas⟩"], parent="p_orm")
uml_class("modelo", "ModeloORM", 1070, S + 170, 350, "libs", stereo="<tabla>.py · 1 por tabla",
          attrs=["+ __tablename__: str", "+ columnas: Mapped[...]"],
          ops=["+ get_by_id(id)  «classmethod»",
               "+ get_by_<campo>(v)  «classmethod»",
               "+ list_by_<campo>(v)  «classmethod»",
               "+ create(**campos)  «classmethod» → flush",
               "+ public_dict(): dict",
               "+ <transición>()  ⟨advance_to, mark_signed_at…⟩"], parent="p_orm")
note("n_r9",
     "R9 Acceso a la BD SOLO vía ORM (ningún handler escribe SQL).\n"
     "El modelo hace flush; @handle_exceptions hace commit / rollback / close: "
     "1 invocación = 1 transacción.\n"
     "El esquema lo define MigraciónSQL; el modelo lo refleja.",
     1450, S + 225, 265, 150, parent="p_orm")

package("p_lutils", "libs/utils  —  utilidades generales", 1750, S, 775, 380, "libs",
        parent="p_libs", font=12)
uml_class("auth", "Auth", 2150, S + 50, 360, "libs", stereo="auth.py",
          ops=["+ issue_token(user_id)", "+ verify_token(token)", "+ @require_auth(handler)"],
          parent="p_lutils")
uml_class("linvoke", "LambdaInvoke", 1770, S + 50, 360, "libs", stereo="lambda_invoke.py",
          ops=["+ invoke_sync(fn, payload): dict", "+ invoke_async(fn, payload)",
               "+ resolve_function_name(svc, fn)"], parent="p_lutils")
uml_class("passwords", "Passwords", 2150, S + 185, 360, "libs", stereo="passwords.py",
          ops=["+ hash_password() · verify_password()"], parent="p_lutils")
uml_class("validators", "Validators", 1770, S + 185, 360, "libs", stereo="validators.py",
          ops=["+ valid_email() · password_reason()"], parent="p_lutils")
note("n_r3",
     "R3 libs/ nunca importa de services/ ni platform/.\n"
     "R4 Lo que usa 1 bloque va en su utils/; lo que usan ≥ 2 bloques va en libs/. "
     "Prohibido common/, shared/ o helpers/ dentro de src/.",
     1770, S + 280, 740, 64, parent="p_lutils")

# ============ AWS runtime ==========================================================
YA = Y3 + 500 + 70     # debajo del paquete backend/
package("p_aws", "Recursos AWS de runtime (fuera del código)", 20, YA, W_TOTAL - 20, 170, "aws",
        tab_right=True)
uml_class("bucket", "S3Bucket", 300, YA + 45, 320, "aws", stereo="cdts-<stage>-<nombre>",
          attrs=["declarado en resources del bloque dueño"], parent="p_aws")
uml_class("pg", "PostgreSQL", 680, YA + 45, 310, "aws", stereo="instancia única",
          attrs=["+ schemas: dev | pro", "+ tabla schema_migrations"], parent="p_aws")
uml_class("ssm", "SSMParameterStore", 1070, YA + 45, 350, "aws", stereo="/cdts/<stage>/…",
          attrs=["db/* · smtp/* · frontend/url · llaves", "R10 secretos SOLO aquí"],
          parent="p_aws")

# ==========================================================================
#                               RELACIONES
# ==========================================================================
# Proyecto
edge("proyecto", "infra", "comp", sp=("R", 160), tp=("L", 160), tgt_m="1")
edge("proyecto", "backend", "comp", sp=("B", 200), tp=("T", 200), tgt_m="1")

# Composición / bloques
edge("compose", "bloque", "aggr", sp=("R", 447), tp=("L", 447), label="registra", tgt_m="1..*")
edge("bloque", "bloque", "assoc", sp=("T", 480), tp=("T", 600),
     pts=[(480, 376), (600, 376)], label="dependsOn", label_pos=0,
     label_off=(0, -9), tgt_m="0..*")
gen_y = 600
edge("plataforma", "bloque", "gen", sp=("T", 480), tp=("B", 620), pts=[(480, gen_y), (620, gen_y)])
edge("servicio", "bloque", "gen", sp=("T", 845), tp=("B", 620), pts=[(845, gen_y), (620, gen_y)])
edge("servicio", "servicio", "assoc", sp=("R", 660), tp=("R", 710),
     pts=[(1060, 660), (1060, 710)], label="invoca\n(sin import)", label_pos=0,
     label_off=(38, 0), tgt_m="0..*")
edge("plataforma", "carpeta", "comp", sp=("L", 682), tp=("R", 682), tgt_m="0..1")
edge("carpeta", "archivo_c", "comp", sp=("B", 170), tp=("T", 170), tgt_m="0..*")
arch_y = 848
edge("asset", "archivo_c", "gen", sp=("T", 172), tp=("B", 172))
edge("migracion", "archivo_c", "gen", sp=("T", 450), tp=("B", 172), pts=[(450, arch_y), (172, arch_y)])
edge("n_r1", "servicio", "link", sp=("T", 845), tp=("B", 845))
edge("n_r11", "migracion", "link", sp=("L", 928), tp=("R", 928))

# Bloque ◆ archivos del bloque (árbol por arriba)
trunk_y = 420
for tgt, mult in (("sls", "1"), ("fnjs", "1"), ("reqs", "1"), ("data_s", "0..1"),
                  ("utils_s", "0..1")):
    x, y, w, h = geo[tgt]
    edge("bloque", tgt, "comp", sp=("R", trunk_y), tp=("T", x + 40),
         pts=[(x + 40, trunk_y)], tgt_m=mult)
edge("fnjs", "buildfn", "dep", sp=("B", 1705), tp=("T", 1505), pts=[(1705, 640), (1505, 640)],
     label="«delega el registro»", label_pos=-0.55, label_off=(58, 0))

# Bloque ◆ Lambda
edge("bloque", "lambda", "comp", sp=("R", 520), tp=("T", 1150), pts=[(1150, 520)],
     tgt_m="0..*", label="src/", label_pos=0.55, label_off=(-18, 0))

# Tipos de Lambda
tri_x = 772
for t in ("l_api", "l_worker", "l_cron"):
    x, y, w, h = geo[t]
    cy = y + h / 2
    edge(t, "lambda", "gen", sp=("R", cy), tp=("L", 1181), pts=[(tri_x, cy), (tri_x, 1181)])
for t, ev in (("l_api", "ev_http"), ("l_worker", "ev_async"), ("l_cron", "ev_sched")):
    x, y, w, h = geo[t]
    cy = y + h / 2
    edge(t, ev, "assoc", sp=("L", cy), tp=("R", cy), label="disparada por", tgt_m="1..*",
         label_pos=0.1, label_off=(0, 11))
edge("lambda", "aux", "comp", sp=("B", 1000), tp=("T", 1000), tgt_m="0..*")
edge("n_r5", "lambda", "link", sp=("R", 1452), tp=("B", 830), pts=[(830, 1452)])

# Lambda ◆ sus archivos (árbol por arriba)
ltrunk = 1090
for tgt, mult in (("fnyml", "1"), ("testpy", "1"), ("integpy", "0..1"), ("handler", "1")):
    x, y, w, h = geo[tgt]
    edge("lambda", tgt, "comp", sp=("R", 1135), tp=("T", x + 40),
         pts=[(1230, 1135), (1230, ltrunk), (x + 40, ltrunk)], tgt_m=mult)
edge("testpy", "conftest", "dep", sp=("T", 1760), tp=("B", 1760), label="«usa»", label_pos=-0.35)
edge("integpy", "helpers", "dep", sp=("T", 2050), tp=("B", 2050), label="«usa»", label_pos=-0.35)
edge("n_r7", "testpy", "link", sp=("T", 1705), tp=("B", 1705))
edge("n_r7", "integpy", "link", sp=("T", 2005), tp=("B", 2005))

# Handler → utils de servicio / libs
hx, hy, hw, hh = geo["handler"]
c1, c2 = Y3 - 30, Y3 - 16      # carriles horizontales entre src/ y libs/
edge("handler", "utils_s", "dep", sp=("T", 2430), tp=("B", 2430), label="«importa»",
     label_pos=0.62)
edge("utils_s", "p_lutils", "dep", sp=("R", 470), tp=("R", S + 40), pts=[(2530, 470), (2530, S + 40)],
     label="«importa»", label_pos=-0.1)
edge("handler", "responses", "dep", sp=("B", 2200), tp=("T", 570),
     pts=[(2200, c1), (570, c1)], label="«@handle_exceptions»", label_pos=0.3)
edge("handler", "modelo", "dep", sp=("B", 2250), tp=("T", 1385),
     pts=[(2250, c2), (1385, c2)], label="«accede a datos»", label_pos=0.05,
     label_off=(0, 12))
edge("handler", "auth", "dep", sp=("B", 2330), tp=("T", 2330), label="«@require_auth»",
     label_pos=-0.35)

# Capa ORM
bx, by, bw, bh = geo["base"]
edge("modelo", "base", "gen", sp=("T", 1215), tp=("B", 1215))
ox, oy, ow, oh = geo["orminit"]
mx, my, mw, mh = geo["modelo"]
edge("orminit", "modelo", "dep", sp=("B", 1440), tp=("R", my + 40), pts=[(1440, my + 40)],
     label="«registra»", label_pos=-0.3, label_off=(34, 0))
dx_, dy_, dw_, dh_ = geo["db"]
edge("modelo", "db", "dep", sp=("L", my + 20), tp=("R", my + 20), label="«usa»",
     label_pos=0, label_off=(0, -10))
edge("responses", "db", "dep", sp=("R", dy_ + 50), tp=("L", dy_ + 50), label="«usa»",
     label_pos=0, label_off=(0, -10))
edge("n_r9", "modelo", "link", sp=("L", my + 150), tp=("R", my + 150))

# libs → AWS
edge("db", "pg", "dep", sp=("B", 760), tp=("T", 760), label="«conecta»", label_pos=0.75)
edge("db", "ssm", "dep", sp=("B", 930), tp=("T", 1150), pts=[(930, YA - 20), (1150, YA - 20)],
     label="«credenciales»", label_pos=0.35)
edge("s3", "bucket", "dep", sp=("B", 440), tp=("T", 440), label="«presign / put»", label_pos=0.55)
px_, py_, pw_, ph_ = geo["pg"]
mgx, mgy, mgw, mgh = geo["migracion"]
edge("migracion", "pg", "dep", sp=("B", 520), tp=("B", 835),
     pts=[(520, 995), (30, 995), (30, py_ + ph_ + 18), (835, py_ + ph_ + 18)],
     label="«define el esquema de»", label_pos=0.62)


# ==========================================================================
xml = (
    '<mxfile host="drawio" type="device" compressed="false">'
    '<diagram id="metamodelo" name="Metamodelo estructural">'
    f'<mxGraphModel dx="2600" dy="2460" grid="1" gridSize="10" guides="1" tooltips="1" '
    f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{W_TOTAL + 40}" '
    f'pageHeight="2340" math="0" shadow="0" background="#ffffff">'
    '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    + "".join(cells)
    + "</root></mxGraphModel></diagram></mxfile>\n"
)
OUT.write_text(xml, encoding="utf-8")
print(f"wrote {OUT} ({len(cells)} cells)")
