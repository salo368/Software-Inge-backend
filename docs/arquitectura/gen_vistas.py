"""Genera `metamodelo.drawio`: el metamodelo del backend partido en vistas.

Cada vista es una página del mismo archivo draw.io (pestañas abajo en el
editor) y muestra UN solo tema con pocas cajas: la estructura de un servicio,
la de una función, etc.

    python3 docs/arquitectura/gen_vistas.py

OJO: regenerar sobrescribe `metamodelo.drawio`. Si ya lo editaste a mano en
draw.io, sigue editándolo allí y exporta desde Archivo → Exportar.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

OUT = Path(__file__).with_name("metamodelo.drawio")

# Una familia de color por categoría (igual en todas las vistas)
C = {
    "service": ("#dae8fc", "#6c8ebf"),   # servicio / bloque desplegable
    "lambda":  ("#d5e8d4", "#82b366"),   # funciones (Lambdas)
    "file":    ("#fff2cc", "#d6b656"),   # archivos del repo
    "libs":    ("#e1d5e7", "#9673a6"),   # código compartido libs/
    "tool":    ("#f5f5f5", "#666666"),   # tooling / testing
    "aws":     ("#ffe6cc", "#d79b00"),   # AWS
}

HEADER, ROW, DIV, PAD = 42, 22, 8, 4


class Page:
    def __init__(self, pid: str, name: str, width: int, height: int):
        self.pid, self.name, self.width, self.height = pid, name, width, height
        self.cells: list[str] = []
        self.geo: dict[str, tuple[float, float, float, float]] = {}
        self.seq = 0

    # ---------------------------------------------------------------- utils
    def nid(self, prefix: str) -> str:
        self.seq += 1
        return f"{self.pid}_{prefix}{self.seq}"

    def vertex(self, cid, value, style, x, y, w, h, parent="1"):
        self.cells.append(
            f'<mxCell id="{self.pid}_{cid}" value={quoteattr(value)} style={quoteattr(style)} '
            f'vertex="1" parent="{parent}"><mxGeometry x="{x:g}" y="{y:g}" width="{w:g}" '
            f'height="{h:g}" as="geometry"/></mxCell>')
        self.geo[cid] = (x, y, w, h)

    # ----------------------------------------------------------- primitivas
    def title(self, text: str, subtitle: str):
        self.vertex("title", f"<b>{esc(text)}</b>",
                    "text;html=1;align=left;verticalAlign=middle;fontSize=22;", 20, 12, 1200, 32)
        self.vertex("subtitle", subtitle,
                    "text;html=1;align=left;verticalAlign=middle;fontSize=13;fontColor=#444444;"
                    "whiteSpace=wrap;", 20, 46, self.width - 40, 24)

    def uml_class(self, cid, name, x, y, w, kind, stereo=None, rows=(), ops=(), abstract=False):
        fill, stroke = C[kind]
        tags = (["«abstract»"] if abstract else []) + ([f"«{stereo}»"] if stereo else [])
        name_html = f"<i>{esc(name)}</i>" if abstract else esc(name)
        head = (f'<span style="font-weight:normal;font-size:12px">{esc(" ".join(tags))}</span><br>'
                if tags else "")
        start = HEADER if tags else 28
        h = start + PAD + len(rows) * ROW + (DIV if rows and ops else 0) + len(ops) * ROW
        self.vertex(cid, f"{head}<b>{name_html}</b>",
                    "swimlane;fontStyle=0;align=center;verticalAlign=top;childLayout=stackLayout;"
                    f"horizontal=1;startSize={start};horizontalStack=0;resizeParent=1;"
                    "resizeParentMax=0;resizeLast=0;collapsible=0;marginBottom=4;html=1;"
                    f"whiteSpace=wrap;fontSize=14;fillColor={fill};strokeColor={stroke};"
                    "swimlaneFillColor=#ffffff;", x, y, w, h)
        row_style = ("text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
                     "spacingLeft=8;spacingRight=6;overflow=hidden;rotatable=0;"
                     "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;html=1;whiteSpace=wrap;"
                     "fontSize=12;")
        cy = start
        for i, r in enumerate(rows):
            self._child(f"{cid}_r{i}", fmt(r), row_style, cid, cy, w, ROW)
            cy += ROW
        if rows and ops:
            self._child(f"{cid}_div", "", "line;strokeWidth=1;fillColor=none;align=left;"
                        f"verticalAlign=middle;rotatable=0;points=[];strokeColor={stroke};",
                        cid, cy, w, DIV)
            cy += DIV
        for i, o in enumerate(ops):
            self._child(f"{cid}_o{i}", fmt(o), row_style, cid, cy, w, ROW)
            cy += ROW

    def _child(self, cid, value, style, parent, y, w, h):
        self.cells.append(
            f'<mxCell id="{self.pid}_{cid}" value={quoteattr(value)} style={quoteattr(style)} '
            f'vertex="1" parent="{self.pid}_{parent}"><mxGeometry y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/></mxCell>')

    LIGHT = {"libs": "#f7f3f9", "service": "#f3f7fd", "lambda": "#f4faf3", "file": "#fffbef",
             "tool": "#fafafa", "aws": "#fff8f0"}

    def package(self, cid, label, x, y, w, h, kind, body=""):
        fill, stroke = self.LIGHT[kind], C[kind][1]
        tab = int(len(label) * 13 * 0.58) + 26
        value = f"<b>{esc(label)}</b>" + (f"<br><br>{body}" if body else "")
        self.vertex(cid, value,
                    f"shape=folder;tabWidth={tab};tabHeight=26;tabPosition=left;html=1;"
                    "whiteSpace=wrap;verticalAlign=top;align=left;spacingLeft=10;spacingTop=3;"
                    f"fontSize=13;fillColor={fill};strokeColor={stroke};", x, y, w, h)

    def note(self, cid, lines: list[str], x, y, w, h, title=None):
        body = ('<ul style="margin:4px 0 0 0;padding-left:18px">'
                + "".join(f'<li style="margin-bottom:3px">{fmt(l)}</li>' for l in lines) + "</ul>")
        if title:
            body = f"<b>{esc(title)}</b>{body}"
        self.vertex(cid, body,
                    "shape=note;size=14;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                    "spacingLeft=10;spacingRight=12;spacingTop=6;fontSize=12;"
                    "fillColor=#fffde7;strokeColor=#c9b458;", x, y, w, h)

    def tree(self, cid, heading, lines: list[str], x, y, w, h):
        """Árbol de carpetas en monoespaciado (la estructura tal como se ve en disco)."""
        def mono(l):
            # conserva la indentación y pinta en gris lo que va entre ⟨ ⟩
            t = esc(l).replace(" ", "&nbsp;")
            return t.replace("⟨", '<span style="color:#888888">').replace("⟩", "</span>")
        body = "<br>".join(mono(l) for l in lines)
        self.vertex(cid, f'<b style="font-family:Helvetica">{esc(heading)}</b><br><br>'
                         f'<span style="font-family:Courier New">{body}</span>',
                    "rounded=1;arcSize=4;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                    "spacingLeft=14;spacingTop=10;fontSize=13;fillColor=#fbfbfb;"
                    "strokeColor=#bbbbbb;", x, y, w, h)

    def text(self, cid, value, x, y, w, h, size=12, color="#333333", align="left"):
        self.vertex(cid, value, f"text;html=1;whiteSpace=wrap;align={align};"
                    f"verticalAlign=middle;fontSize={size};fontColor={color};", x, y, w, h)

    # ------------------------------------------------------------ relaciones
    KIND = {
        "comp": "startArrow=diamondThin;startFill=1;startSize=16;endArrow=none;",
        "aggr": "startArrow=diamondThin;startFill=0;startSize=16;endArrow=none;",
        "gen":  "endArrow=block;endFill=0;endSize=14;",
        "dep":  "endArrow=open;endFill=0;endSize=10;dashed=1;dashPattern=8 4;",
        "assoc": "endArrow=open;endFill=0;endSize=10;",
    }

    def edge(self, src, tgt, kind, sp, tp, pts=(), label=None, tgt_m=None,
             label_pos=0.0, label_off=(0, 0)):
        """sp/tp = (lado, coordenada absoluta a lo largo del lado)."""
        eid = self.nid("e")
        style = ("html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;fontSize=12;"
                 "labelBackgroundColor=#ffffff;strokeColor=#333333;fontColor=#333333;"
                 + self.KIND[kind])
        for key, cid, (side, at) in (("exit", src, sp), ("entry", tgt, tp)):
            fx, fy = self._frac(cid, side, at)
            style += f"{key}X={fx};{key}Y={fy};{key}Dx=0;{key}Dy=0;{key}Perimeter=0;"
        arr = ""
        if pts:
            arr = '<Array as="points">' + "".join(
                f'<mxPoint x="{px:g}" y="{py:g}"/>' for px, py in pts) + "</Array>"
        self.cells.append(
            f'<mxCell id="{eid}" value={quoteattr(esc(label) if label else "")} '
            f'style={quoteattr(style)} edge="1" parent="1" source="{self.pid}_{src}" '
            f'target="{self.pid}_{tgt}"><mxGeometry x="{label_pos}" relative="1" as="geometry">'
            f'<mxPoint x="{label_off[0]}" y="{label_off[1]}" as="offset"/>{arr}</mxGeometry>'
            f'</mxCell>')
        if tgt_m:
            align, valign, dx, dy = {"T": ("left", "bottom", 5, -3), "B": ("left", "top", 5, 3),
                                     "L": ("right", "bottom", -5, -2),
                                     "R": ("left", "bottom", 5, -2)}[tp[0]]
            self.cells.append(
                f'<mxCell id="{self.nid("m")}" value={quoteattr(esc(tgt_m))} '
                f'style="edgeLabel;resizable=0;html=1;align={align};verticalAlign={valign};'
                f'fontSize=12;fontStyle=1;labelBackgroundColor=none;" vertex="1" '
                f'connectable="0" parent="{eid}"><mxGeometry x="1" relative="1" as="geometry">'
                f'<mxPoint x="{dx}" y="{dy}" as="offset"/></mxGeometry></mxCell>')

    def _frac(self, cid, side, at):
        x, y, w, h = self.geo[cid]
        if side in "TB":
            return round((at - x) / w, 4), (0 if side == "T" else 1)
        return (0 if side == "L" else 1), round((at - y) / h, 4)

    def legend(self, y, items: list[tuple[str, str]]):
        """Leyenda compacta en una línea: solo las relaciones usadas en la vista."""
        x = 20
        self.text("lg_t", "<b>Leyenda</b>", x, y, 70, 22)
        x += 80
        for i, (kind, label) in enumerate(items):
            eid = self.nid("lg")
            style = ("html=1;rounded=0;strokeColor=#333333;" + self.KIND[kind])
            self.cells.append(
                f'<mxCell id="{eid}" value="" style={quoteattr(style)} edge="1" parent="1">'
                f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x}" y="{y + 11}" '
                f'as="sourcePoint"/><mxPoint x="{x + 60}" y="{y + 11}" as="targetPoint"/>'
                f'</mxGeometry></mxCell>')
            self.text(f"lg_{i}", esc(label), x + 70, y, 250, 22)
            x += 70 + 12 + int(len(label) * 6.6)

    def xml(self) -> str:
        return (f'<diagram id="{self.pid}" name={quoteattr(self.name)}>'
                f'<mxGraphModel dx="{self.width}" dy="{self.height}" grid="1" gridSize="10" '
                'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
                f'pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0" '
                'background="#ffffff"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                + "".join(self.cells) + "</root></mxGraphModel></diagram>")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def fmt(s: str) -> str:
    """Escapa HTML; ⟨gris⟩ = aclaración; **negrita**."""
    t = esc(s).replace("⟨", '<span style="color:#888888">').replace("⟩", "</span>")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


# ==========================================================================
# Vista 1 · Estructura de un servicio
# ==========================================================================
def vista_servicio() -> Page:
    p = Page("v1", "1 · Servicio", 1510, 740)
    p.title("Vista 1 · Estructura de un servicio",
            "Qué contiene <b>toda</b> carpeta <b>backend/services/&lt;nombre&gt;/</b>. "
            "Las funciones de <i>src/</i> se detallan en la Vista 2 y <i>libs/</i> en la Vista 3.")

    p.tree("disco", "Así se ve en disco", [
        "services/<nombre>/",
        "├── serverless.yml",
        "├── functions.js",
        "├── requirements.txt",
        "├── utils/      ⟨opcional⟩",
        "├── data/       ⟨opcional⟩",
        "└── src/",
        "    ├── handlers/<función>/",
        "    ├── workers/<función>/",
        "    └── scheduled/<función>/",
    ], 20, 96, 330, 272)

    # --- el servicio y quién lo registra -----------------------------------
    p.uml_class("compose", "Composición", 400, 110, 270, "file", stereo="serverless-compose.yml",
                rows=["registra cada servicio", "dependsOn: migrations, …"])
    p.uml_class("svc", "Servicio", 400, 318, 270, "service", stereo="services/<nombre>/",
                rows=["+ 1 dominio de negocio",
                      "/ stack = cdts-<stage>-<nombre>",
                      "+ su propio API Gateway"])
    p.edge("compose", "svc", "aggr", sp=("B", 535), tp=("T", 535), label="registra", tgt_m="1..*")

    # --- lo que contiene (árbol) --------------------------------------------
    X, W = 780, 380
    kids = [
        ("sls", "ServerlessYml", "file", "serverless.yml", "1",
         ["provider: runtime, stage, stackName", "IAM · variables ⟨rutas SSM⟩ · buckets",
          "functions: ${file(./functions.js):build}"]),
        ("fnjs", "FunctionsJs", "file", "functions.js", "1",
         ["registra solas las funciones de src/", "copia libs/ dentro del servicio"]),
        ("reqs", "Requirements", "file", "requirements.txt", "1",
         ["dependencias Python del servicio"]),
        ("utils", "UtilsDelServicio", "file", "utils/", "0..1",
         ["helpers PRIVADOS del servicio", "from utils.x import y"]),
        ("data", "DataDelServicio", "file", "data/", "0..1",
         ["DTOs · JSON schemas · datos estáticos"]),
        ("fn", "Función (Lambda)", "lambda", "src/<tipo>/<función>/", "1..*",
         ["API · Worker · CronJob", "detalle → **Vista 2**"]),
    ]
    y = 96
    trunk_x = 730
    sx, sy, sw, sh = p.geo["svc"]
    src_y = sy + sh / 2
    for cid, name, kind, stereo, mult, rows in kids:
        p.uml_class(cid, name, X, y, W, kind, stereo=stereo, rows=rows)
        cy = y + p.geo[cid][3] / 2
        p.edge("svc", cid, "comp", sp=("R", src_y), tp=("L", cy),
               pts=[(trunk_x, src_y), (trunk_x, cy)], tgt_m=mult)
        y += p.geo[cid][3] + 16

    # --- libs/ (colapsado) ----------------------------------------------------
    fy = p.geo["fnjs"][1]
    ly0 = fy - 10
    ly1 = p.geo["fn"][1] + p.geo["fn"][3] + 10
    p.package("libs", "backend/libs/", 1290, ly0, 200, ly1 - ly0, "libs",
              body="Código compartido<br>por todos los servicios:<br><br>core · orm · utils<br><br>"
                   "detalle → <b>Vista 3</b>")
    for cid, label in (("fnjs", "«copia»"), ("utils", "«importa»"), ("fn", "«importa»")):
        x, y0, w, h = p.geo[cid]
        cy = y0 + h / 2
        p.edge(cid, "libs", "dep", sp=("R", cy), tp=("L", cy), label=label)

    # --- reglas ---------------------------------------------------------------
    p.note("reglas", [
        "1 servicio = 1 dominio de negocio = 1 stack de CloudFormation.",
        "Un servicio **nunca importa** código de otro: lo llama por lambda_invoke o HTTP.",
        "Lo que usa solo este servicio va en **utils/**; si lo usan 2 o más, va en **libs/**.",
        "Los bloques de platform/ (migrations, assets) usan la misma plantilla: pueden omitir "
        "src/ y suman su carpeta de datos (sql/, files/).",
    ], 20, 470, 690, 132, title="Reglas")

    ly = ly1 + 22
    p.height = int(ly + 40)
    p.legend(ly, [("comp", "composición: el servicio contiene"),
                   ("aggr", "agregación: registra"),
                   ("dep", "dependencia: usa / importa")])
    p.text("lg_mult", "<b>1</b> obligatorio · <b>0..1</b> opcional · <b>1..*</b> uno o más · "
           "<b>«x»</b> ruta real", 1030, ly, 460, 22, align="right")
    return p


PAGES = [vista_servicio()]

OUT.write_text('<mxfile host="drawio" type="device" compressed="false">'
               + "".join(pg.xml() for pg in PAGES) + "</mxfile>\n", encoding="utf-8")
print(f"wrote {OUT} ({len(PAGES)} vista(s))")
