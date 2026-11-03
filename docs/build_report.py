"""
Builds docs/WASTEX_Project_Report.docx following the department template:
Times New Roman 12 body, 16 pt bold chapter titles, 14 pt bold sub-titles, page
border on every page, header from the Introduction onwards (project title at
top-left, 2026-2027 at top-right), footer "Department of AIML, RVCE" at
bottom-left with the page number at bottom-right, a preamble for every chapter
and captioned figures/tables referred to in the text.

    python docs/build_report.py
"""
import inspect
import json
import os
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DOCS = os.path.join(ROOT, "docs")
FIG = os.path.join(DOCS, "figures")
SHOT = os.path.join(DOCS, "screenshots")

import make_figures  # noqa: E402  (same folder)
from backend import config  # noqa: E402
from backend.agents import fleet_agent, jev_orchestrator, route_agent, waste_agent  # noqa: E402
from backend import bus as busmod  # noqa: E402
from backend import routing  # noqa: E402
from backend.data import bengaluru as data  # noqa: E402
from backend.streaming import processor  # noqa: E402

TITLE = "WASTEX: Intelligent Multi-Agent Waste Collection Optimization System using Kafka Stream Processing"
SHORT_TITLE = "WASTEX: Multi-Agent Waste Collection Optimization"
STUDENTS = [("Ibrahim Bagwan", "1RV24AI404"), ("Monil Palak Mehta", "1RV23AI058"), ("Joseph Rejo Mathew", "1RV23AI040")]
FONT = "Times New Roman"


# =============================================================== low-level helpers
def set_cell_shading(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def add_field(run, instr, cached=""):
    """Insert a complex field (PAGE, SEQ, TOC ...) into a run."""
    r = run._r
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin"); r.append(b)
    t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = f" {instr} "; r.append(t)
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate"); r.append(s)
    txt = OxmlElement("w:t"); txt.set(qn("xml:space"), "preserve"); txt.text = cached; r.append(txt)
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end"); r.append(e)


def clear_default_tabs(p):
    """Header/Footer styles carry centre (8.25 cm) and right (16.5 cm) tabs; clear them."""
    from docx.shared import Twips
    for pos in (4680, 9360):
        p.paragraph_format.tab_stops.add_tab_stop(Twips(pos), WD_TAB_ALIGNMENT.CLEAR)


def page_border(section):
    sectPr = section._sectPr
    pb = OxmlElement("w:pgBorders")
    pb.set(qn("w:offsetFrom"), "page")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "12")
        el.set(qn("w:space"), "24")
        el.set(qn("w:color"), "000000")
        pb.append(el)
    sectPr.append(pb)


def font(run, size=12, bold=False, italic=False, color=None, name=FONT):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


class Report:
    def __init__(self):
        self.doc = Document()
        self.chapter = 0
        self.fig_no = 0
        self.tab_no = 0
        self.figures = []
        self.tables = []
        self._styles()

    # ------------------------------------------------------------ styles
    def _styles(self):
        st = self.doc.styles
        n = st["Normal"]
        n.font.name = FONT
        n.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        n.font.size = Pt(12)
        n.paragraph_format.line_spacing = 1.5
        n.paragraph_format.space_after = Pt(6)
        for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12)):
            h = st[name]
            h.font.name = FONT
            h.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
            h.font.size = Pt(size)
            h.font.bold = True
            h.font.color.rgb = RGBColor(0, 0, 0)
            h.paragraph_format.space_before = Pt(12 if size < 16 else 0)
            h.paragraph_format.space_after = Pt(8)
            h.paragraph_format.line_spacing = 1.15
        from docx.enum.style import WD_STYLE_TYPE
        for nm in ("Figure Caption", "Table Caption"):  # separate styles feed the two TOC lists
            cs = st.add_style(nm, WD_STYLE_TYPE.PARAGRAPH)
            cs.base_style = st["Caption"]
            cs.font.name = FONT
            cs.font.size = Pt(11)
            cs.font.bold = True
            cs.font.italic = False
            cs.font.color.rgb = RGBColor(0, 0, 0)
        cap = st["Caption"]
        cap.font.name = FONT
        cap.font.size = Pt(11)
        cap.font.bold = True
        cap.font.italic = False
        cap.font.color.rgb = RGBColor(0, 0, 0)
        sec = self.doc.sections[0]
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        for side in ("left_margin", "right_margin"):
            setattr(sec, side, Cm(2.7))
        sec.top_margin, sec.bottom_margin = Cm(2.5), Cm(2.3)
        page_border(sec)
        # TOC / list fields are filled by docs/finalize_report.ps1 (MS Word) or by pressing F9 in Word

    # ------------------------------------------------------------ text blocks
    def para(self, text="", size=12, bold=False, italic=False, align="justify", space_after=6, line=1.5):
        p = self.doc.add_paragraph()
        p.alignment = {"justify": WD_ALIGN_PARAGRAPH.JUSTIFY, "center": WD_ALIGN_PARAGRAPH.CENTER,
                       "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = line
        if text:
            self._rich(p, text, size, bold, italic)
        return p

    @staticmethod
    def _rich(p, text, size=12, bold=False, italic=False):
        """**bold** segments inside text."""
        parts = text.split("**")
        for i, part in enumerate(parts):
            if part:
                font(p.add_run(part), size, bold or i % 2 == 1, italic)

    def bullets(self, items, style="List Bullet"):
        for it in items:
            p = self.doc.add_paragraph(style=style)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.line_spacing = 1.5
            p.paragraph_format.space_after = Pt(2)
            self._rich(p, it)

    def chapter_title(self, title, preamble):
        self.chapter += 1
        h = self.doc.add_heading(level=1)
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        h.paragraph_format.page_break_before = self.chapter > 1  # chapter 1 already follows a section break
        font(h.add_run(f"Chapter {self.chapter}"), 16, True)
        h.add_run().add_break()
        font(h.add_run(title), 16, True)
        self.para(preamble, italic=True)
        self.sub_no = 0

    def h2(self, text):
        self.sub_no += 1
        h = self.doc.add_heading(level=2)
        font(h.add_run(f"{self.chapter}.{self.sub_no} {text}"), 14, True)
        self.sub3 = 0

    def h3(self, text):
        self.sub3 += 1
        h = self.doc.add_heading(level=3)
        font(h.add_run(f"{self.chapter}.{self.sub_no}.{self.sub3} {text}"), 12, True)

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ------------------------------------------------------------ figures & tables
    def next_fig(self):
        return f"{self.chapter}.{sum(1 for f in self.figures if f[0].startswith(str(self.chapter) + '.')) + 1}"

    def figure(self, path, caption, width_cm=15.5):
        num = self.next_fig()
        self.figures.append((num, caption))
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(path, width=Cm(width_cm))
        c = self.doc.add_paragraph(style="Figure Caption")
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        font(c.add_run(f"Figure {num}: {caption}"), 11, True)
        return num

    def table(self, headers, rows, caption, widths=None, size=10):
        num = f"{self.chapter}.{sum(1 for t in self.tables if t[0].startswith(str(self.chapter) + '.')) + 1}"
        self.tables.append((num, caption))
        c = self.doc.add_paragraph(style="Table Caption")
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraph_format.keep_with_next = True
        font(c.add_run(f"Table {num}: {caption}"), 11, True)
        t = self.doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(headers):
            cell = t.rows[0].cells[i]
            cell.text = ""
            font(cell.paragraphs[0].add_run(str(h)), size, True)
            set_cell_shading(cell, "D9E2F3")
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                pp = cells[i].paragraphs[0]
                pp.paragraph_format.line_spacing = 1.0
                font(pp.add_run(str(v)), size)
        for r in t.rows:
            for cell in r.cells:
                for pp in cell.paragraphs:
                    pp.paragraph_format.space_after = Pt(1)
                    pp.paragraph_format.line_spacing = 1.0
        if widths:
            for r in t.rows:
                for i, w in enumerate(widths):
                    r.cells[i].width = Cm(w)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return num

    def code(self, src, caption=None):
        if caption:
            p = self.para(caption, size=11, bold=True, align="left", space_after=2, line=1.0)
            p.paragraph_format.keep_with_next = True
        t = self.doc.add_table(rows=1, cols=1)
        t.style = "Table Grid"
        cell = t.rows[0].cells[0]
        set_cell_shading(cell, "F3F5F8")
        cell.text = ""
        lines = src.rstrip().split("\n")
        p = cell.paragraphs[0]
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(0)
        for i, ln in enumerate(lines):
            r = font(p.add_run(ln), 8.5, name="Consolas")
            if i < len(lines) - 1:
                r.add_break()
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ------------------------------------------------------------ header / footer
    def start_main_section(self):
        sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        page_border(sec)
        sec.header.is_linked_to_previous = False
        sec.footer.is_linked_to_previous = False
        width = sec.page_width - sec.left_margin - sec.right_margin
        hp = sec.header.paragraphs[0]
        clear_default_tabs(hp)
        hp.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
        font(hp.add_run(SHORT_TITLE), 11)
        font(hp.add_run("\t2026-2027"), 11)
        fp = sec.footer.paragraphs[0]
        clear_default_tabs(fp)
        fp.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
        font(fp.add_run("Department of AIML, RVCE"), 11)
        font(fp.add_run("\t"), 11)
        add_field(font(fp.add_run(""), 11), "PAGE", "1")
        pg = OxmlElement("w:pgNumType")
        pg.set(qn("w:start"), "1")
        sec._sectPr.append(pg)
        # front-matter section keeps an empty header/footer
        first = self.doc.sections[0]
        first.header.is_linked_to_previous = False
        first.footer.is_linked_to_previous = False


def src_of(obj, start=None, end=None, max_lines=60):
    lines = inspect.getsource(obj).split("\n")
    if start is not None:
        lines = lines[start:end]
    return "\n".join(lines[:max_lines])


# =============================================================== content
def build():
    bench = make_figures.main()
    live = json.load(open(os.path.join(FIG, "live_metrics.json"))) if os.path.exists(os.path.join(FIG, "live_metrics.json")) else None
    f, f4, w = bench["fixed"], bench["fixed4"], bench["wastex"]
    im, i4 = bench["improvement"], bench["improvement_vs_fixed4"]
    R = Report()
    d = R.doc

    # ---------------------------------------------------------- title page
    R.para("RV College of Engineering®", 16, True, align="center", space_after=0)
    R.para("(Autonomous Institution Affiliated to Visvesvaraya Technological University, Belagavi)", 11, align="center", space_after=0)
    R.para("Department of", 14, True, align="center", space_after=0)
    R.para("ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING", 14, True, align="center", space_after=18)
    R.para(TITLE, 18, True, align="center", space_after=18)
    R.para("Project Report", 14, True, align="center", space_after=4)
    R.para("Submitted by", 12, italic=True, align="center", space_after=4)
    for name, usn in STUDENTS:
        R.para(f"{name}          {usn}", 14, True, align="center", space_after=0)
    R.para("", space_after=8)
    R.para("in partial fulfilment for the requirement of 7th Semester", 12, align="center", space_after=0)
    R.para("Stream Processing and Analytics (AI372IA)", 13, True, align="center", space_after=14)
    R.para("Under the Guidance of", 12, italic=True, align="center", space_after=4)
    g = d.add_table(rows=1, cols=2)
    for i, lines in enumerate([["Dr. S. Anupama Kumar", "Associate Professor", "Department of AIML", "RV College of Engineering", "Bengaluru-59"],
                               ["Dr. Vijayalakshmi M. N.", "Associate Professor", "Department of AIML", "RV College of Engineering", "Bengaluru-59"]]):
        cell = g.rows[0].cells[i]
        cell.text = ""
        for j, ln in enumerate(lines):
            p = cell.paragraphs[0] if j == 0 else cell.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            font(p.add_run(ln), 12, j == 0)
    R.para("", space_after=14)
    R.para("Academic Year", 12, True, align="center", space_after=0)
    R.para("2026 - 2027", 12, True, align="center", space_after=0)
    R.page_break()

    # ---------------------------------------------------------- certificate
    R.para("RV College of Engineering®", 16, True, align="center", space_after=0)
    R.para("(Autonomous Institution Affiliated to Visvesvaraya Technological University, Belagavi)", 11, align="center", space_after=0)
    R.para("Department of ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING", 13, True, align="center", space_after=0)
    R.para("Bengaluru – 560059", 12, align="center", space_after=24)
    R.para("CERTIFICATE", 16, True, align="center", space_after=18)
    names = ", ".join(f"{n} ({u})" for n, u in STUDENTS[:-1]) + f" and {STUDENTS[-1][0]} ({STUDENTS[-1][1]})"
    R.para(f"This is to certify that the work entitled “{TITLE}” submitted in partial fulfillment of Stream Processing "
           f"and Analytics (AI372IA) of VII Semester BE is a result of the bonafide work carried out by {names} during the "
           f"Academic year 2026-27.", line=2.0)
    R.para("", space_after=60)
    sig = d.add_table(rows=1, cols=2)
    for i, txt in enumerate(["Faculty In charge", "Head of the Department"]):
        p = sig.rows[0].cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        font(p.add_run(txt), 12, True)
    R.para("", space_after=40)
    R.para("External Examination", 13, True, align="center")
    ex = d.add_table(rows=3, cols=2)
    for i, txt in enumerate(["Name of Examiners", "Signature with date"]):
        font(ex.rows[0].cells[i].paragraphs[0].add_run(txt), 12, True)
    for r_, n in ((1, "1."), (2, "2.")):
        font(ex.rows[r_].cells[0].paragraphs[0].add_run(n), 12)
    R.page_break()

    # ---------------------------------------------------------- abstract
    R.para("ABSTRACT", 16, True, align="center", space_after=12)
    R.para("Municipal solid-waste collection in Bengaluru still follows fixed schedules (07:30–09:00 and 18:00–19:30) even though "
           "every bin fills at a different and changing rate. The result is a reactive system: some bins overflow long before the "
           "truck arrives while others are emptied half-full, wasting fuel and crew time. BBMP complaint records confirm the "
           "pattern; the most frequent grievance is that waste is cleared but comes back.")
    R.para("This project presents WASTEX, an end-to-end event-driven system that turns live smart-bin telemetry into collection "
           f"decisions in real time. A scenario-driven IoT simulator emits fill level, weight, temperature and battery readings "
           f"for {bench['bins']} bins placed on 14 real Bengaluru wards. The readings flow through Apache Kafka (8 topics, "
           "28 partitions, 5 consumer groups) into a stateful stream processor. The processor computes sliding-window fill rates "
           "with least squares and EWMA, forecasts the time to overflow, detects sensor spikes, tampering, fire and low battery "
           "through a stream–stream join with collection events, and emits 5-minute tumbling-window zone aggregates. "
           "A multi-agent decision layer, the JEV Orchestrator, then coordinates three specialised agents. The Waste "
           "Intelligence Agent decides WHAT needs collection. The Route Planner Agent decides HOW, using capacity-constrained "
           "clustering, batching, nearest-neighbour with 2-opt, and utilisation-aware plant selection. The Fleet Manager Agent "
           "decides WHO, by best-fit assignment with dynamic insertion. JEV re-plans adaptively whenever a constraint makes a plan "
           "infeasible. A fleet simulator executes the plans and closes the loop by emitting collection events.")
    R.para(f"On an identical 24-hour simulation, WASTEX reduced overflow bin-minutes by {im['overflow_bin_minutes_pct']}% and "
           f"overflow events by {im['overflow_events_pct']}% compared with the current twice-daily BBMP schedule. At a comparable "
           f"distance to a 4×/day schedule ({fmt(f4['km'])} km vs {fmt(w['km'])} km), it cut overflow by "
           f"{i4['overflow_bin_minutes_pct']}%, needed {i4['collections_pct']}% fewer bin lifts, and collected bins at "
           f"{w['avg_fill_at_collection']}% average fill instead of {f4['avg_fill_at_collection']}%. "
           + (f"On the live Kafka deployment, every consumer group kept up with the stream with zero lag. The JEV orchestrator "
              f"reached a decision in {live['jev']['avg_decision_ms']} ms on average." if live else "")
           + " An interactive web dashboard, a Route Optimizer that routes operator-selected bins on real Bengaluru roads, "
             "live waste-hotspot analytics and a Kafka internals laboratory make every stage of the pipeline observable.")
    R.para("Keywords: Apache Kafka, stream processing, multi-agent systems, smart waste management, IoT, vehicle routing, Bengaluru.",
           italic=True)
    R.page_break()

    # ---------------------------------------------------------- TOC & lists
    R.para("Table of Contents", 16, True, align="center", space_after=10)
    p = d.add_paragraph()
    add_field(p.add_run(), 'TOC \\o "1-2" \\h \\z \\u', "Open in MS Word and press F9 (or accept 'update fields') to build the table of contents.")
    R.page_break()
    R.para("List of Tables", 16, True, align="center", space_after=10)
    p = d.add_paragraph()
    add_field(p.add_run(), 'TOC \\h \\z \\t "Table Caption,1"', "Update field to build the list of tables.")
    R.page_break()
    R.para("List of Figures", 16, True, align="center", space_after=10)
    p = d.add_paragraph()
    add_field(p.add_run(), 'TOC \\h \\z \\t "Figure Caption,1"', "Update field to build the list of figures.")

    # ================================================================ MAIN BODY
    R.start_main_section()

    # ---------------------------------------------------------- 1 Introduction
    R.chapter_title("Introduction",
                    "This chapter introduces the WASTEX project. It describes the operational problem of urban waste collection that motivated it, "
                    "outlines the solution at a high level, and explains how the rest of the report is organised.")
    R.h2("Project Description")
    R.para("Bengaluru generates several thousand tonnes of municipal solid waste every day. Collection is planned around fixed "
           "time windows. On weekdays and weekends alike, trucks visit their beats between 07:30 and 09:00 and again between "
           "18:00 and 19:30 (Table 1.1). Waste generation, however, is highly dynamic. A commercial street in Indiranagar fills far "
           "faster than a residential lane in Yelahanka. Festivals, cricket matches and weekend markets cause sudden surges, and "
           "the same bin fills at different rates at different hours of the day.")
    R.table(["Days", "Collection window"], [[s["days"], s["window"]] for s in data.FIXED_SCHEDULE],
            "Current fixed BBMP collection schedule (baseline)", [6, 6])
    R.para("WASTEX (Intelligent Multi-Agent Waste Collection Optimization System) replaces the fixed schedule with data-driven "
           "decisions. Each smart bin streams telemetry to an Apache Kafka cluster. A stream processor turns the raw readings "
           "into actionable signals: how full the bin is, how fast it is filling, when it will overflow and whether the sensor is "
           "behaving abnormally. A multi-agent decision layer, the JEV Orchestrator with its Waste, Route and Fleet agents, then "
           "decides which bins to collect, in what order, and with which truck. The plans are executed by a fleet simulator, and "
           "every pickup is fed back into the stream, so the system continuously closes the loop between data and action.")
    R.para("The complete system runs locally on a laptop. It consists of a Dockerised Apache Kafka 3.7 broker in KRaft mode, a "
           "Python backend, and a browser dashboard with eight pages. The pages cover a live city map, the live Kafka pipeline, "
           "an interactive Kafka internals laboratory, the agents' reasoning traces, stream analytics, the fleet, and the "
           "evaluation results.")
    R.h2("Motivation")
    R.para("The motivation is summarised in the SPA Lab presentation: **the challenge is not collecting data, it is turning data "
           "into timely decisions.** Three observations from the exploratory data analysis drive the design.")
    R.bullets([
        "**Growth rate matters, not level alone.** A bin rising from 78% to 84% in ten minutes (0.6%/min) overflows in about "
        "27 minutes, sooner than a slow-filling bin that is already at 92%. Fixed schedules and simple threshold rules both miss this.",
        "**Averages hide bins.** Koramangala's average fill was 67.2% while one of its bins was at 91%. Decisions must be made "
        "per bin, on the stream, not on daily averages.",
        "**Capacity is unevenly used.** Bengaluru's processing plants have 2,900 TPD of mixed-waste capacity but receive only "
        "1,150 TPD (40%). MSGP (83%) and Doddabidarakallu (75%) are near saturation while Kannahalli (8%) is mostly idle, so "
        "the choice of disposal site matters.",
    ])
    R.h2("Report Organization")
    R.para("Chapter 2 defines the problem and reviews 25 related works. Chapter 3 lists the objectives. Chapter 4 describes the "
           "tools, the datasets and the techniques used. Chapter 5 presents the implementation of every component with code "
           "snippets. Chapter 6 reports the results of the live system and of the comparative evaluation and discusses them. "
           "Chapter 7 concludes, Chapter 8 lists future enhancements, and the Appendix documents how to run the system and the "
           "message schemas.")

    # ---------------------------------------------------------- 2 Problem definition
    R.chapter_title("Problem Definition",
                    "This chapter states the problem WASTEX addresses and why it matters. It then surveys the existing literature on smart "
                    "waste management, streaming architectures and agentic routing to identify the research gap this project fills.")
    R.h2("Problem Statement")
    R.para("Given thousands of geographically distributed smart bins that continuously report their state, and a limited "
           "heterogeneous fleet of collection trucks, **how do we make the right collection decision in real time?** Each decision "
           "has four parts: **what** (which bins need attention before they overflow), **when** (now, or can it wait for a better "
           "batch), **where** (in which order, and to which processing plant), and **how** (which truck, given its capacity, "
           "current load, location and availability).")
    R.para("The problem is relevant because overflowing bins cause littering, disease vectors, garbage burning and repeated "
           "citizen complaints. Collecting half-empty bins on a timetable, meanwhile, wastes diesel, crew hours and road capacity. "
           "The data volume (one reading per bin per minute, i.e. hundreds of events per second for a single city zone), the need "
           "for sub-second reaction to events such as fires, and the coupling between routing and fleet constraints make this a "
           "stream-processing and decision-making problem rather than a batch analytics one.")
    R.h2("Background Information (Literature Review)")
    R.para("Table 2.1 summarises the 25 studies reviewed. They fall into four groups. The first group is IoT monitoring "
           "systems and reviews [4, 7, 9, 13, 24]. The second covers forecasting and classification models [5, 6, 12, 18, 19, 22, 23]. "
           "The third covers routing and optimisation [8, 10, 14, 21, 25]. The fourth covers LLM or agentic approaches to routing "
           "and operations research [1, 2, 3, 15, 16]. Only a few works use a streaming backbone. Miletić et al. [17] built an "
           "MQTT-to-Kafka architecture, but for air quality, and Vonitsanos et al. [20] used Spark Streaming for bin levels, but "
           "without routing or fleet allocation.")
    lit = [
        ("1", "Zhu et al., 2025", "Edge LLM agent fusing dual-YOLO vision, policy data and bin state", "Bin-level only; no city-wide streaming, routing or truck allocation"),
        ("2", "Li et al., 2025 (ARS)", "LLM agents generate constraint-aware VRP heuristics; RoutBench", "Generic benchmarks, no live bin data"),
        ("3", "Zhang & Cao, 2025", "Four cooperating LLM agents for complex VRPs", "Offline, not event-driven, no Kafka"),
        ("4", "Alaoui, Belhiah & Ziti, 2025", "Systematic review of IoT smart-waste approaches", "Review only, no implemented pipeline"),
        ("5", "Ishaque & Florence, 2025", "Deep-learning waste classification + vehicle routing", "Model-centric; no stream processing"),
        ("6", "Reji et al., 2025", "Swin Transformer + ant colony optimisation", "Offline; no Kafka ingestion or windowing"),
        ("7", "Gatti, Barbierato & Pozzi, 2024", "Review of RL/GA/GNN smart-bin routing", "Theoretical; no operational system"),
        ("8", "Ali et al., 2024", "TOPSIS route selection; 14% shorter distance", "Static scoring; no streaming or agents"),
        ("9", "Addas, Khan & Naseer, 2024", "IoT + cloud dynamic routing; 32% better efficiency", "No LLM agents or Kafka backbone"),
        ("10", "Belhiah, El Aboudi & Ziti, 2024", "GIS + contraction hierarchies for unplanned waste", "Routing only; no fleet agent"),
        ("11", "Hussain et al., 2024", "Agent-based simulation: sensor vs periodic collection", "Rule-based agents; no real-time pipeline"),
        ("12", "Kona & Subramoniam, 2024", "DCNN predicts visit period + shortest path", "No windowing, explainability or allocation"),
        ("13", "Sankar & Fathima, 2024", "IoTBinCap scheduling from sensor data", "Simulation-level; no distributed streaming"),
        ("14", "Çil et al., 2024", "K-means container placement (Yalova)", "Planning stage only"),
        ("15", "Huang, Shi & Sukhatme, 2024", "LLMs generate routing programs", "General VRP; no live data"),
        ("16", "Xiao et al., 2024 (Chain-of-Experts)", "Multi-agent LLMs for OR problems", "Not domain-specific; no streaming"),
        ("17", "Miletić et al., 2023", "MQTT-to-Kafka architecture for air quality", "No waste analytics or agents"),
        ("18", "Mishra, 2023", "Five time-series models for bin fill (MAE 0.24)", "Batch forecasting only"),
        ("19", "Ahmed et al., 2022", "CNN-LSTM/GRU bin fullness forecast", "Forecast only; not linked to routing"),
        ("20", "Vonitsanos et al., 2022", "Apache Spark framework for waste-level streams", "No Kafka topic design, agents or routing"),
        ("21", "Salehi-Amiri et al., 2022", "Two-stage sustainable IoT waste system", "Optimisation model; not real time"),
        ("22", "Anjum, Shahab & Umar, 2022", "IoT sensing + forecasting models", "No event streaming or routing"),
        ("23", "Al Duhayyim et al., 2022", "DRL recycling object classification", "Classification task only"),
        ("24", "Vishnu et al., 2021", "LoRaWAN/Wi-Fi smart-bin monitoring", "Monitoring only"),
        ("25", "Aktemur, Erensoy & Kocyigit, 2020", "Evolutionary algorithms for collection routes", "Offline; no telemetry"),
    ]
    R.table(["#", "Author / Year", "Main contribution", "Gap w.r.t. WASTEX"], lit, "Summary of the literature survey", [0.8, 3.6, 5.6, 5.6], size=9)
    R.para("**Research gap.** No reviewed work combines all of the following in one operational loop: (i) a partitioned, "
           "replayable event backbone (Kafka) with explicit topic and consumer-group design; (ii) stateful windowed stream "
           "operators that forecast overflow and detect sensor faults; (iii) separate, explainable agents for prioritisation, "
           "routing and fleet allocation, coordinated adaptively with re-planning; and (iv) feedback of execution events into the "
           "stream. WASTEX is designed to fill exactly this gap.")

    # ---------------------------------------------------------- 3 Objectives
    R.chapter_title("Objectives",
                    "This chapter lists the objectives that guided the design of WASTEX and the measurable outcomes used to judge whether "
                    "they were met.")
    R.h2("Primary Objectives")
    R.para("The SPA Lab presentation framed the goals as four verbs: Predict, Optimize, Respond and Scale. They translate into "
           "the following objectives.")
    R.bullets([
        "**PREDICT** – Identify bins needing collection before they overflow, by estimating each bin's fill rate on the live "
        "stream and forecasting its time to overflow, combined with fill level, ward complaint history and anomalies into a priority score.",
        "**OPTIMIZE** – Generate efficient collection routes that respect vehicle capacity, batch nearby bins, sequence stops "
        "to minimise distance under time-of-day traffic, and choose processing plants with spare capacity.",
        "**RESPOND** – React to changing conditions within seconds. This covers demand spikes, event surges, fires, sensor "
        "faults and truck breakdowns, with adaptive re-planning when a plan becomes infeasible.",
        "**SCALE** – Handle increasing IoT workload through a partitioned Kafka backbone, keyed by bin, so that processing "
        "can be parallelised by adding consumers to a group without losing per-bin ordering.",
        "**EXPLAIN** – Make every decision transparent through an ordered decision log with each agent's inputs, scores and "
        "verdicts, and make the whole pipeline observable on a dashboard.",
    ])
    R.h2("Expected Outcomes")
    R.bullets([
        "A working local end-to-end system with a real Apache Kafka broker, plus an embedded Kafka-compatible fallback.",
        "Fewer overflow events and overflow minutes than the fixed BBMP schedule on the same simulated city.",
        "Higher average bin fill at collection (fewer wasted lifts) at a comparable distance.",
        "Low-latency processing (zero consumer lag at steady state; decisions in milliseconds).",
        "An educational Kafka laboratory that demonstrates partitioning, consumer groups, lag, replication and failover.",
    ])

    # ---------------------------------------------------------- 4 Tools & techniques
    R.chapter_title("Tools and Techniques",
                    "This chapter describes the software stack, the datasets (both real and synthetic), and the stream-processing, "
                    "optimisation and multi-agent techniques used in WASTEX, together with the reasons each was chosen.")
    R.h2("Tools")
    tools = [
        ("Apache Kafka 3.7.1 (KRaft)", "Distributed event log; durable, partitioned, replayable transport between all components"),
        ("Docker Desktop + Compose", "Runs the Kafka broker and Kafka UI locally with one command"),
        ("Kafka UI (provectus 0.7.2)", "Independent web view of topics, partitions and consumer groups (port 8080)"),
        ("Python 3.10", "Implementation language of the simulators, stream processor and agents"),
        ("kafka-python 3.0", "Kafka client: producers, consumer groups, admin client and offset queries"),
        ("FastAPI + Uvicorn", "REST API, WebSocket push (1 Hz snapshots) and control endpoints"),
        ("Leaflet 1.9 + Esri basemap", "Interactive Bengaluru map with bins, trucks, routes, plants, DWCCs and landfills"),
        ("Chart.js 4.4", "Dashboard charts (zone windows, trends, scenario mix, alerts, benchmark)"),
        ("OSRM (OpenStreetMap router)", "Real-road route geometry and distances on the Route Optimizer page"),
        ("HTML5 Canvas", "Real-time animation of the Kafka Lab simulator"),
        ("Matplotlib, python-docx", "Report figures and generation of this document"),
        ("Hardware", "Single Windows 11 laptop; no cloud deployment"),
    ]
    R.table(["Tool", "Purpose in WASTEX"], tools, "Tools and their purpose", [5, 10.5])
    R.h2("Datasets")
    R.para("The data strategy mixes real reference data, used for geographic realism, with synthetic telemetry, used to "
           "simulate IoT sensors (Table 4.2). Real coordinates for the Dry Waste Collection Centres (Table 4.3), processing "
           "plants with capacities (Table 4.4) and landfills come from BBMP data published on OpenCity. They are embedded in "
           "backend/data/bengaluru.py.")
    R.table(["Data", "Real / Synthetic", "Purpose"], [
        ("Bengaluru bin / ward locations", "Real", "Geographic realism"), ("Bengaluru road / network data", "Real (modelled)", "Route optimization"),
        ("Historical waste generation & complaints", "Real where available", "EDA + realistic patterns"),
        ("Live bin fill levels", "Synthetic", "Simulate IoT sensors"), ("Waste weight", "Synthetic", "Streaming"),
        ("Temperature / battery", "Synthetic", "IoT telemetry"), ("Overflow events", "Synthetic / derived", "Alerts"),
        ("Collection events", "Synthetic", "Kafka events")], "Data sources used by WASTEX", [6, 4, 5.5])
    R.table(["Location", "Latitude", "Longitude"], [(x["name"], x["lat"], x["lon"]) for x in data.DRY_WASTE_CENTRES],
            "Dry Waste Collection Centres in Bengaluru (four also act as truck depots)", [6, 4, 4])
    R.table(["Plant", "Area", "Mixed TPD", "Wet TPD", "Intake TPD", "Utilisation"],
            [(p["name"].replace(" Waste Processing", "").replace(" Plant", "").replace(" Unit", ""), p["area"], p["mixed_tpd"], p["wet_tpd"], p["intake_tpd"],
              f"{100 * p['intake_tpd'] / p['mixed_tpd']:.0f}%" if p["mixed_tpd"] else "closed") for p in data.PROCESSING_PLANTS]
            + [("MSGP", "–", 600, "–", 500, "83%")], "Waste processing plants: capacity and intake", [4.6, 3.2, 1.8, 1.6, 1.8, 2], size=9)
    R.para("Landfill sites (Outside BBMP, village 15317, and two Jakkur sites in ward 5) are also plotted on the map. The ward "
           "complaint EDA (Figure 4.1) shows Bellandur (ward 150, 152 records) and Banaswadi (ward 27, 128 records) as the "
           "worst-affected wards. These counts feed the Waste Agent's history term. The plant capacity EDA (Figure 4.2) "
           "motivates utilisation-aware plant selection.")
    R.figure(os.path.join(FIG, "fig_ward_complaints.png"), "Ward-level garbage complaint records used as the history signal")
    R.figure(os.path.join(FIG, "fig_plant_capacity.png"), "Capacity versus current intake of Bengaluru's waste processing plants")
    R.h2("Techniques")
    R.h3("Event-driven architecture on Kafka")
    R.para("All components communicate only through Kafka topics, never by direct calls. Producers and consumers are "
           "therefore decoupled in time and in scale, and every event is persisted and can be replayed. Records are keyed "
           "by bin_id, zone_id or truck_id. Kafka's default partitioner (murmur2(key) mod N) routes all events of one bin to one "
           "partition, which guarantees per-bin ordering, the property that fill-rate computation depends on. Consumer groups "
           "give each downstream service its own independent position (offset) in the log, and lag (log-end offset minus "
           "committed offset) measures whether a service keeps up.")
    R.h3("Stateful stream processing")
    R.bullets([
        "**Sliding count window + least squares:** the last 10 validated readings of a bin are fitted with a line. Its slope "
        "is the fill rate in %/min, smoothed with an EWMA (α = 0.6).",
        "**Forecasting:** time to overflow ETA = (100 − fill) / rate.",
        "**Anomaly detection:** jumps above +15% per reading are physically implausible and are quarantined as sensor "
        "spikes. Drops below −15% without a matching collection event are flagged as tampering or scavenging. Temperatures "
        "≥ 60 °C are flagged as fire (garbage burning), and battery below 15% raises a maintenance alert.",
        "**Stream–stream join:** telemetry is joined with collection-events, so a drop that follows a truck visit resets "
        "the window instead of raising a false tamper alarm.",
        "**Tumbling windows:** 5-minute, non-overlapping event-time windows per zone produce average and maximum fill, "
        "the number of bins above 90%, total kilograms and anomaly counts.",
        "**Alert de-duplication with hysteresis:** an alert fires once per bin and type and re-arms only after the condition "
        "has clearly cleared (fill < 90%, or ETA > 60 min).",
    ])
    R.h3("Multi-agent decision making")
    R.para("Decision making is decomposed into three questions, each answered by a specialised agent, and coordinated by the "
           "JEV Orchestrator (Figure 5.3).")
    R.bullets([
        "**Waste Intelligence Agent (WHAT):** score = 0.35·fill + 0.35·urgency + 0.15·rate + 0.15·history (+ fire override). "
        "Urgency is 1 when the bin will overflow within 60 minutes, the time a truck needs to reach it, and falls linearly "
        "to 0 at 240 minutes (Figure 4.3). Scores of 0.65 or more are HIGH (collect), 0.45 or more are MEDIUM (monitor), and "
        "the rest are LOW (ignore).",
        "**Route Planner Agent (HOW):** capacity-constrained greedy clustering seeded by the most urgent bin. Opportunistic "
        "pickup adds MEDIUM bins, and LOW bins that are already at least 55% full, within 3 km. A batching rule dispatches a "
        "route only with 4 or more stops or an imminent bin. Stops are sequenced by nearest neighbour and improved with 2-opt. "
        "Road distance is modelled as great-circle distance × 1.35 circuity, with a time-of-day traffic speed (Figure 4.4). "
        "A truck unloads only when at least 75% full, at the plant with the lowest distance × (1 + 0.6·utilisation), skipping "
        "plants that are closed or more than 90% utilised.",
        "**Fleet Manager Agent (WHO):** every truck is classed as unavailable, insufficient or feasible. Feasible trucks are "
        "ranked by dead-head distance + 6·capacity slack (best fit), with a penalty of 4 for appending to a running route "
        "(dynamic insertion).",
        "**JEV Orchestrator:** runs on events (overflow, critical fill, predicted overflow, fire, breakdown) and every 5 "
        "simulated minutes. If no bin is HIGH it stops early (No Action). If no truck can serve a route it detects the "
        "constraint and re-plans by splitting the route geographically, up to 3 attempts, before deferring.",
    ])
    R.figure(os.path.join(FIG, "fig_urgency.png"), "Urgency as a function of predicted time to overflow", 11)
    R.figure(os.path.join(FIG, "fig_demand_model.png"), "Daily waste-generation profile and time-of-day truck speed model")
    R.h3("Simulation and evaluation methodology")
    R.para("Because a city-wide sensor network is not available, both the physical world and the fleet are simulated. "
           "Every bin has a type (240 L, 1100 L or 3200 L community bin), a ward-specific base rate, a per-bin log-normal "
           "factor, Gaussian noise and the daily demand curve in Figure 4.4. Scenarios inject demand spikes (×1.8), event surges "
           "(×4 in one ward for 60 minutes) and anomalies. All randomness comes from a fixed seed (42), so experiments are "
           "reproducible. The offline benchmark replays the same city for 24 hours under three policies: BBMP 2×/day, 4×/day "
           "and WASTEX. The WASTEX run reuses the live agent code.")

    # ---------------------------------------------------------- 5 Implementation
    R.chapter_title("Implementation",
                    "This chapter explains how WASTEX is built: the overall architecture, the Kafka topic design, each processing "
                    "component and agent, the dashboard and the Kafka laboratory. Representative code snippets are taken directly "
                    "from the source.")
    R.h2("System Architecture")
    R.para("Figure 5.1 shows the five layers. The data layer (IoT simulator, real Bengaluru reference data and the scenario "
           "engine) publishes to Kafka. The stream-processing layer enriches and aggregates the readings. The JEV multi-agent "
           "layer turns them into plans. The action layer (fleet simulator and dashboard) executes and visualises them. "
           "collection-events and fleet-status close the feedback loop.")
    R.figure(os.path.join(SHOT, "about.png"), "WASTEX layered architecture (Architecture page of the dashboard)")
    R.h2("Kafka Topic and Consumer-Group Design")
    topic_rows = [
        ("bin-telemetry", 6, "bin_id", "IoT simulator", "stream processor, dashboard"),
        ("bin-analytics", 6, "bin_id", "stream processor", "JEV, dashboard"),
        ("bin-alerts", 3, "bin_id / truck_id", "stream processor, fleet", "JEV, dashboard"),
        ("zone-aggregates", 3, "zone_id", "stream processor", "dashboard"),
        ("agent-decisions", 1, "'jev' (total order)", "JEV", "dashboard"),
        ("collection-plans", 3, "truck_id", "JEV", "fleet simulator, dashboard"),
        ("fleet-status", 3, "truck_id", "fleet simulator", "JEV, dashboard"),
        ("collection-events", 3, "bin_id", "fleet simulator", "IoT gateway, stream processor, dashboard"),
    ]
    R.table(["Topic", "Partitions", "Key", "Producer", "Consumer(s)"], topic_rows, "Kafka topics, keys and data flow", [3.6, 1.8, 3, 3.3, 4.2], size=9.5)
    R.para("Five consumer groups are used: wastex-stream-processor, wastex-jev-orchestrator, wastex-fleet-simulator, "
           "wastex-iot-gateway and wastex-dashboard-bridge. At startup, every consumer first joins its group and receives a "
           "partition assignment. Only then do the producers start, so no early event is lost. agent-decisions has one partition "
           "on purpose, which gives the decision log a total order. The bus abstraction (backend/bus.py) has two "
           "implementations. KafkaBus talks to the real broker. EmbeddedBus follows the same semantics: append-only "
           "partition logs, the murmur2 partitioner, range-assigned consumer groups, committed offsets, lag and retention. "
           "This lets the project run even without Docker.")
    R.code(src_of(busmod.murmur2), "Snippet 5.1 – Kafka's murmur2 partitioner (backend/bus.py)")
    R.h2("IoT Smart-Bin Simulator")
    R.para(f"The simulator creates {config.BINS_PER_ZONE} bins in each of 14 wards ({config.BINS_PER_ZONE * 14} bins), spread "
           "around the real ward centroids. Every simulated minute it publishes one record per bin to bin-telemetry. Each "
           "record carries the bin id, zone, coordinates, bin type, fill level, weight, temperature, battery, timestamp and "
           "scenario label. It also consumes collection-events and empties a bin when a truck visits it. A sample record is "
           "listed in Appendix B.")
    R.h2("Stream Processor")
    R.para("The stream processor is the only consumer of raw telemetry. Snippet 5.2 shows the least-squares slope used for "
           "the fill rate, and Snippet 5.3 shows the anomaly logic with the collection join.")
    R.code(src_of(processor.slope), "Snippet 5.2 – Sliding-window fill-rate regression (backend/streaming/processor.py)")
    src = inspect.getsource(processor.StreamProcessor._on_telemetry).split("\n")
    R.code("\n".join(src[0:34]), "Snippet 5.3 – Anomaly detection and stream–stream join")
    R.h2("JEV Multi-Agent Decision Layer")
    R.para("Snippets 5.4 to 5.6 show the core of each agent. The orchestrator in Snippet 5.7 implements the feasibility / "
           "re-plan loop of the adaptive workflow. The live trace of a decision is shown in Figure 5.3.")
    R.code(src_of(waste_agent.WasteIntelligenceAgent.score, 0, 30), "Snippet 5.4 – Waste Intelligence Agent priority score")
    R.code(src_of(route_agent.RoutePlannerAgent.optimise_order), "Snippet 5.5 – Route Planner: nearest neighbour + 2-opt")
    R.code(src_of(fleet_agent.FleetManagerAgent.assign), "Snippet 5.6 – Fleet Manager: best-fit assignment and constraint detection")
    cyc = inspect.getsource(jev_orchestrator.JEVOrchestrator.cycle).split("\n")
    start = next(i for i, l in enumerate(cyc) if "queue = deque" in l)
    R.code("\n".join(cyc[start:start + 46]), "Snippet 5.7 – JEV feasibility check and re-plan / retry loop")
    R.h2("Fleet Simulator")
    R.para("Each of the eight trucks (Table 5.2) is a state machine: idle → en_route → collecting → … → to_plant → unloading → "
           "returning, plus breakdown. Trucks move along the road model at the time-of-day speed. They emit fleet-status "
           "heartbeats every simulated minute and a collection-event at every pickup. A breakdown releases the truck's stops "
           "and raises a TRUCK_BREAKDOWN alert, which triggers immediate re-planning.")
    R.table(["Truck", "Type", "Capacity (kg)", "Home depot"],
            [(t["id"], t["type"], t["capacity_kg"], next(x["name"] for x in data.DEPOTS if x["id"] == t["depot"])) for t in data.FLEET],
            "Simulated fleet", [3, 3.5, 3, 5])
    R.h2("Dashboard and Kafka Laboratory")
    R.para("A dashboard bridge consumer group materialises every topic into views that the FastAPI server pushes over a "
           "WebSocket once per second. The Command Center (Figure 5.2) shows the live map of Bengaluru with bins coloured by "
           "fill, trucks with their remaining routes, depots, DWCCs, plants and landfills, together with KPIs and the alert "
           "feed. The JEV Agents page (Figure 5.3) animates the slide-13 workflow for each decision and lists the full "
           "reasoning trace. The Kafka Pipeline page (Figure 5.4) shows the live topology, partition offsets and consumer lag. "
           "The Kafka Lab (Figure 5.5) is an interactive simulation of producers, a partitioned topic replicated on three "
           "brokers, and a consumer group. It demonstrates key partitioning, rebalancing, lag, leader election from the ISR and "
           "acks semantics.")
    R.figure(os.path.join(SHOT, "command.png"), "Command Center: live Bengaluru bin and fleet map, KPIs and alerts")
    R.figure(os.path.join(SHOT, "agents.png"), "JEV Agents page: adaptive workflow and reasoning trace of a decision")
    R.figure(os.path.join(SHOT, "pipeline.png"), "Kafka Pipeline page: topology, partitions and consumer-group lag on the real broker")
    R.figure(os.path.join(SHOT, "lab.png"), "Kafka Lab: broker B1 killed, leaders re-elected from the ISR, zero data loss")
    R.h2("Route Optimizer and Real-Road Routing")
    R.para("Inside every route, collection is a travelling-salesman path problem: start (depot or truck) → all selected bins → "
           "destination (processing plant or standby). The problem is NP-hard. backend/routing.py therefore implements four "
           "strategies: the order the bins were picked (no optimisation), nearest neighbour (greedy, O(n²)), nearest neighbour "
           "improved by 2-opt (segment reversal until no improving move remains), and the exact Held-Karp dynamic programme "
           "(O(n²·2ⁿ)), which serves as the optimality reference for up to 11 stops (Snippet 5.8). Plain 2-opt can still leave a "
           "single stop badly placed, so the live Route Planner Agent adds Or-opt moves (relocating chains of 1–3 stops) and "
           "runs this local search from two construction tours, nearest neighbour and cheapest insertion, keeping the shorter "
           "(multi-start). A distance cache keeps it fast, at about 100 ms for 15 stops.")
    R.code(src_of(routing.held_karp), "Snippet 5.8 – Held-Karp exact solver used as the optimality reference (backend/routing.py)")
    R.para("The Route Optimizer page (Figure 5.6) lets the operator choose the places. The start can be any depot or "
           "truck. Bins can be added by ward with a fill threshold, as the ten most urgent unscheduled bins, or by clicking "
           "them on the map. The destination can be the automatically chosen plant, a specific plant, or standby. The page "
           "compares all algorithms on the same stops and destination, ranks the processing plants by distance × "
           "(1 + 0.6·utilisation), checks every truck's free capacity, and draws both the unoptimised and the optimised "
           "route on real roads using the OSRM router (OpenStreetMap data). It also reports the real-road distance next to "
           "the modelled distance. With **Dispatch**, the optimised route is published to the collection-plans topic, so the "
           "chosen truck drives it live and the JEV decision log records the operator decision. Bins already scheduled on "
           "another truck are refused, to prevent double collection.")
    R.figure(os.path.join(SHOT, "route.png"), "Route Optimizer: selected bins routed on real roads, algorithm and plant comparison")
    R.h2("Waste Hotspot Analytics")
    R.para("To show where waste is increasing, each 5-minute zone window carries the zone's waste-generation rate in kg/h, "
           "computed as Σ(fill rate × bin capacity). The dashboard bridge compares each zone's live generation rate with its "
           "own previous ~45 minutes of windows. It labels zones SURGE (more than +40%), RISING (more than +10%), STABLE or "
           "FALLING, and ranks them with a one-hour sparkline. The same signal is drawn as heat circles on the Command Center "
           "map. In a test, an event surge in Yelahanka (normally the lowest-rate ward) moved it to rank 1 at +106%, labelled "
           "SURGE, within about four simulated minutes. The Waste Agent then started dispatching trucks there.")

    # ---------------------------------------------------------- 6 Results
    R.chapter_title("Results and Discussion",
                    "This chapter presents the measured behaviour of the live Kafka pipeline and the comparative evaluation of WASTEX "
                    "against the fixed BBMP schedule. It then interprets the results against the objectives, including the unexpected "
                    "findings and the limitations.")
    R.h2("Final Results")
    R.h3("Live pipeline on Apache Kafka")
    if live:
        rows = [
            ("Broker", live["bus"]),
            ("Simulated time covered", f"{live['sim_min'] / 60:.1f} h (run at {live['speed']}× speed)"),
            ("Messages produced", fmt(live["produced"])),
            ("Telemetry records processed", fmt(live["stream"]["processed"])),
            ("Peak telemetry throughput", f"{live['rates']['bin-telemetry']:.0f} msg/s (bin-telemetry) + {live['rates']['bin-analytics']:.0f} msg/s (bin-analytics)"),
            ("Produce → processed latency p50 / p95", f"{live['stream']['latency_p50_ms']} ms / {live['stream']['latency_p95_ms']} ms"),
            ("Consumer lag (all 5 groups)", ", ".join(f"{k.replace('wastex-', '')}: {v}" for k, v in live["lag"].items())),
            ("JEV decisions / plans / re-plans", f"{live['jev']['cycles']} / {live['jev']['plans']} / {live['jev']['replans']}"),
            ("No-action cycles (work skipped)", f"{live['jev']['no_action']} ({100 * live['jev']['no_action'] / max(1, live['jev']['cycles']):.0f}%)"),
            ("Average JEV decision time", f"{live['jev']['avg_decision_ms']} ms"),
            ("Bins collected / waste delivered", f"{live['fleet']['collections']} / {live['fleet']['kg_delivered'] / 1000:.1f} t"),
            ("Average fill at collection", f"{live['avg_fill_at_collection']}%"),
        ]
        R.table(["Metric", "Value"], rows, "Measured metrics of the live Kafka deployment", [6.5, 9])
        R.para("Table 6.1 shows that every consumer group kept up with the stream: committed offsets equalled the log-end "
               "offsets, so lag was zero. The JEV orchestrator needed only milliseconds per decision, and most periodic cycles "
               "ended early with No Action, which is the adaptive behaviour the design intended. The 85–100 ms produce-to-process "
               "latency is dominated by the client batching (linger.ms) and fetch intervals of the Kafka client, not by computation.")
    R.h3("Comparative evaluation")
    rows = [
        ("Distance driven (km)", f["km"], f4["km"], w["km"]), ("CO2 emitted (kg)", f["co2_kg"], f4["co2_kg"], w["co2_kg"]),
        ("Operating cost (Rs.)", f["cost_inr"], f4["cost_inr"], w["cost_inr"]), ("Bin lifts", f["collections"], f4["collections"], w["collections"]),
        ("Average fill at collection (%)", f["avg_fill_at_collection"], f4["avg_fill_at_collection"], w["avg_fill_at_collection"]),
        ("Overflow bin-minutes", f["overflow_bin_minutes"], f4["overflow_bin_minutes"], w["overflow_bin_minutes"]),
        ("Overflow events", f["overflow_events"], f4["overflow_events"], w["overflow_events"]),
        ("Trips / avg stops per trip", f"{f['trips']} / {f['avg_stops_per_trip']}", f"{f4['trips']} / {f4['avg_stops_per_trip']}", f"{w['trips']} / {w['avg_stops_per_trip']}"),
    ]
    R.table(["Metric (24 h, 140 bins, 8 trucks)", "Fixed 2×/day (BBMP)", "Fixed 4×/day", "WASTEX"],
            [(a, fmt(b), fmt(c), fmt(e)) for a, b, c, e in rows], "Fixed schedules versus WASTEX on the identical simulated city", [6, 3.2, 3, 3.2])
    R.para(f"Table 6.2 and Figures 6.1 and 6.2 compare the policies. Compared with the current BBMP schedule, WASTEX reduces "
           f"overflow bin-minutes by **{im['overflow_bin_minutes_pct']}%** and overflow events by **{im['overflow_events_pct']}%**. "
           f"Simply collecting twice as often (4×/day) costs about as much distance as WASTEX ({fmt(f4['km'])} km vs {fmt(w['km'])} km) "
           f"but still leaves **{i4['overflow_bin_minutes_pct']}% more overflow** than WASTEX. It also performs "
           f"{fmt(f4['collections'])} lifts against WASTEX's {fmt(w['collections'])} ({i4['collections_pct']}% fewer for WASTEX), "
           f"because it empties bins at only {f4['avg_fill_at_collection']}% fill on average versus {w['avg_fill_at_collection']}%.")
    R.figure(os.path.join(FIG, "fig_overflow_series.png"), "Number of overflowing bins over the simulated day for each policy")
    R.figure(os.path.join(FIG, "fig_strategy_bars.png"), "Key metrics of the three policies (scaled for comparison)")
    R.figure(os.path.join(SHOT, "insights.png"), "Insights & Results page of the dashboard")
    R.figure(os.path.join(SHOT, "analytics.png"), "Stream Analytics page: tumbling windows, scenario mix, overflow forecast and alerts")
    R.h3("Route optimisation study")
    study = json.load(open(os.path.join(FIG, "routing_study.json")))
    R.para("Each algorithm was run on 20 random bin sets per route size, starting from a random depot (Table 6.3, Figure 6.5). "
           "Optimisation saves 35–67% of the distance of an unoptimised visiting order. Plain nearest neighbour is 3–15% longer "
           "than the optimum. 2-opt closes most of that gap on average but can be 20% or more off on individual routes. Adding "
           "Or-opt with two starting tours (the live algorithm) reaches the exact optimum in almost every case. The exact "
           "solver's runtime grows exponentially (about 2.5–3× per extra stop), while the heuristic stays fast even for 20 stops. "
           "This is why the live system uses the heuristic and keeps Held-Karp as the reference.")
    R.table(["Stops", "NN gap", "2-opt gap", "Live saving", "Live gap", "Live ms", "Exact ms"],
            [(r["n"], f"{r['nn']['gap']}%" if "exact" in r else "–", f"{r['nn2opt']['gap']}%" if "exact" in r else "–",
              f"{r['ls']['saving']}%", f"{r['ls']['gap']}%" if "exact" in r else "–", r["ls"]["ms"],
              r["exact"]["ms"] if "exact" in r else "–") for r in study],
            "Routing algorithms on random bin sets (gap vs exact optimum; live = multi-start 2-opt + Or-opt; saving vs unoptimised order)",
            [1.4, 1.9, 1.9, 2.2, 1.9, 2, 2], size=9.5)
    R.figure(os.path.join(FIG, "fig_routing_runtime.png"), "Runtime of the live heuristic versus the exact Held-Karp solver", 13)
    R.h3("Scenario tests")
    R.table(["Scenario", "Observed system behaviour"], [
        ("Slide-13 example event", "Bins forced to 96% and nearest truck at 20% spare capacity. JEV logged “Constraint detected: nearest truck can take only 400 kg but the route needs 935 kg” and assigned another truck."),
        ("Fire injection", "FIRE alert at 65 °C within one reading; the Waste Agent forces the bin to HIGH and an event-triggered cycle dispatches a truck."),
        ("Sensor spike", "+37% jump quarantined as SENSOR_SPIKE; the bin is not dispatched on false data."),
        ("Tamper", "−42% drop with no collection event raised a TAMPER alert; real pickups never raised one, thanks to the stream–stream join."),
        ("Truck breakdown", "TRUCK_BREAKDOWN alert released 6 stops; the next event-triggered cycle re-assigned them to other trucks."),
        ("Demand spike / surge", "Telemetry rate unchanged, fill rates ×1.8 / ×4; more HIGH bins, more routes, lag still 0."),
        ("Kafka Lab broker kill", "Leaders of affected partitions re-elected from the ISR; with acks=all and min.insync=2 no data was lost."),
        ("Ward event surge", "Yelahanka rose to rank 1 in the hotspot table (+106%, SURGE) and turned red on the heat map; JEV routed trucks there."),
        ("Operator route dispatch", "10 urgent bins chosen on the Route Optimizer: the live heuristic matched the exact optimum, about 50% shorter than the selection order; the dispatched plan was driven by the truck."),
    ], "Behaviour under the scenario tests", [4, 11.5], size=9.5)
    R.h2("Discussion")
    R.para("**Were the objectives met?** PREDICT is met: bins are prioritised by forecast ETA, and the EDA example of a "
           "fast-filling 78% bin outranking a slow 92% bin is reproduced by the score. OPTIMIZE is met: at a comparable distance (within 3%), WASTEX "
           "delivers far fewer overflows and lifts. RESPOND is met: alerts trigger decisions within one simulated minute, and "
           "breakdowns and capacity constraints are re-planned automatically. SCALE is met: per-bin keyed partitioning lets the "
           "stream processor scale out by adding consumers, as demonstrated in the Kafka Lab, and lag stayed at zero during "
           "surges. EXPLAIN is met: each decision is an ordered, inspectable trace.")
    R.para("**Significance.** The results show that the value of streaming comes from acting on rates and forecasts rather "
           "than on levels. A fixed schedule must over-collect to avoid overflow, because it cannot know which bins will fill "
           "first. A data-driven policy spends the same kilometres where they matter.")
    R.para("**Unexpected outcomes.** (i) The first tuning sent trucks to the periphery plants after every small route, which "
           "made WASTEX drive twice as far as the baseline. Introducing a 75% disposal threshold and a batching rule fixed this. "
           "(ii) The anomaly detector initially quarantined the demonstration's own forced 96% readings as sensor spikes. "
           "This confirms the detector works, and a controlled operator override was added for the demo. "
           "(iii) Alerts sometimes overtook their bin-analytics record because they travel on another topic. JEV now folds "
           "the alert's facts into its bin table before deciding. (iv) Utilisation-aware plant choice still concentrated "
           "deliveries on KCDC, the plant closest to the eastern wards, which stays well within its capacity.")
    R.para("**Limitations.** Road distance uses a circuity factor instead of a full OpenStreetMap graph. Telemetry is "
           "synthetic, although it is calibrated to the EDA. The fleet does not model crew shifts or fuel. Kafka runs as a "
           "single broker in Docker, while replication is demonstrated in the Kafka Lab.")

    # ---------------------------------------------------------- 7 Conclusion
    R.chapter_title("Conclusion",
                    "This chapter summarises what was built and what the evaluation shows.")
    R.para("WASTEX demonstrates a complete, working stream-processing system for smart waste collection in Bengaluru. "
           "Synthetic but realistic IoT telemetry, anchored to real ward, DWCC, plant and landfill data, is streamed through "
           "Apache Kafka with a deliberate topic, key and consumer-group design. Stateful operators turn the raw readings into "
           "fill rates, overflow forecasts, anomaly alerts and windowed zone statistics. A multi-agent layer then answers what "
           "to collect, how and with which truck, re-planning adaptively when constraints such as a nearly full truck or a "
           "breakdown make a plan infeasible. Collection events feed back into the stream, closing the loop.")
    R.para(f"Compared with the current fixed schedule on an identical simulated city, WASTEX cut overflow bin-minutes by "
           f"{im['overflow_bin_minutes_pct']}% and overflow events by {im['overflow_events_pct']}%. At a comparable distance to "
           f"doubling the schedule, it still produced {i4['overflow_bin_minutes_pct']}% less overflow with "
           f"{i4['collections_pct']}% fewer bin lifts. On the live Kafka deployment all consumer groups ran with zero lag and "
           "decisions took milliseconds. The dashboard and the Kafka Lab make every stage observable and explainable, which "
           "turns the project into a practical decision tool as well as a teaching aid for stream processing concepts.")

    # ---------------------------------------------------------- 8 Future
    R.chapter_title("Future Enhancements",
                    "This chapter lists extensions that would take WASTEX from a laboratory system towards a city deployment.")
    R.bullets([
        "**Road-graph planning:** use the OSRM / OpenStreetMap distances (today used for display on the Route Optimizer) inside the planner itself, with live traffic feeds.",
        "**Learned forecasting:** LSTM or GRU models trained on historical fill data, served as a stream operator, to forecast beyond linear trends.",
        "**LLM-assisted orchestration:** a language model in JEV that explains plans in natural language and negotiates "
        "trade-offs, while routing and feasibility stay in the deterministic tools, as recommended by [2, 3, 15, 16].",
        "**Kafka Streams / Flink** deployment of the processor with exactly-once semantics and a multi-broker cluster (RF = 3).",
        "**Real sensors over MQTT** bridged to Kafka (MQTT source connector), with edge pre-filtering on the bin.",
        "**Crew, shift and fuel constraints**, multi-depot VRP with time windows, and electric-vehicle charging.",
        "**Citizen feedback loop:** complaints from the BBMP app streamed as events that raise a ward's priority in real time.",
        "**Waste segregation analytics** (wet/dry/recyclable) to route loads to the right processing facility.",
    ])

    # ---------------------------------------------------------- Appendix
    h = d.add_heading(level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h.paragraph_format.page_break_before = True
    font(h.add_run("Appendix"), 16, True)
    R.para("Appendix A – Running the project", 14, True, align="left")
    R.bullets([
        "Install Python 3.10+ and (optionally) Docker Desktop.",
        "Double-click start.bat. It installs dependencies, starts Kafka and Kafka UI in Docker, waits for the broker to be "
        "healthy and launches WASTEX at http://127.0.0.1:8000 (Kafka UI at http://localhost:8080).",
        "Without Docker, run start-embedded.bat; the embedded Kafka-compatible broker is used.",
        "python -m backend.benchmark reproduces Table 6.2; python docs/build_report.py regenerates this report.",
    ])
    R.para("A companion document, docs/VIVA_QUESTIONS.md, answers 45 likely examiner questions on Kafka, stream processing, "
           "the agents, route optimisation and the evaluation, each linked to the part of the dashboard that demonstrates it.")
    R.para("Appendix B – Sample messages", 14, True, align="left")
    R.code(json.dumps({"bin_id": "BIN-0104", "zone_id": "Z01", "zone": "Indiranagar", "lat": 12.97412, "lon": 77.64561,
                       "bin_type": "SMART-1100", "capacity_l": 1100, "max_kg": 260, "fill_level": 94.12, "weight_kg": 231.7,
                       "temperature_c": 31.4, "battery_pct": 74.6, "ts": "2026-11-03T08:41:00", "sim_min": 101.0,
                       "scenario": "normal", "seq": 101}, indent=1), "bin-telemetry record")
    R.code(json.dumps({"plan_id": "PLAN-00008", "decision_id": "JEV-00007", "truck_id": "TRUCK-08", "truck_type": "Mini Tipper",
                       "mode": "new", "stops": [{"bin_id": "BIN-0201", "priority": "HIGH", "fill_level": 96.0, "est_kg": 274.6},
                                                {"bin_id": "BIN-0202", "priority": "HIGH", "fill_level": 97.0, "est_kg": 660.4}],
                       "dispose": True, "plant": {"id": "PLT6", "name": "KCDC"}, "distance_km": 14.33, "duration_min": 52.0,
                       "load_kg": 935.0}, indent=1), "collection-plans record (abridged)")
    R.para("Appendix C – Key configuration parameters", 14, True, align="left")
    R.chapter = "A"  # appendix tables are numbered A.x
    R.table(["Parameter", "Value"], [
        ("Planning interval", f"{config.PLANNING_INTERVAL_MIN} simulated minutes + event triggers"),
        ("Fill-rate window", f"{config.FILL_RATE_WINDOW} readings, EWMA α = 0.6"),
        ("Zone window", f"{config.ZONE_WINDOW_MINUTES}-minute tumbling"),
        ("Priority thresholds", f"HIGH ≥ {config.HIGH_THRESHOLD}, MEDIUM ≥ {config.MEDIUM_THRESHOLD}"),
        ("Critical fill", f"{config.CRITICAL_FILL}%"), ("Max re-plan attempts", config.MAX_REPLAN_ATTEMPTS),
        ("Road circuity / service / unload", f"{config.ROAD_CIRCUITY} / {config.SERVICE_MIN_PER_BIN} min / {config.UNLOAD_MIN} min"),
        ("Disposal threshold", f"{int(config.DISPOSE_AT * 100)}% of truck capacity"),
        ("CO2 factor", f"{config.DIESEL_KG_CO2_PER_KM} kg/km"), ("Random seed", config.SEED),
    ], "Configuration parameters", [6, 9.5])

    # ---------------------------------------------------------- Bibliography
    h = d.add_heading(level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h.paragraph_format.page_break_before = True
    font(h.add_run("Bibliography"), 16, True)
    refs = [
        "Zhu et al., “Edge AI Agent Design for Policy-Aware Urban Waste Management,” AIAS 2025, EPiC Series in Computing, 2025.",
        "Li et al., “ARS: Automatic Routing Solver with Large Language Models,” arXiv:2502.15359, 2025.",
        "Zhang and Cao, “An Agentic Framework with LLMs for Solving Complex Vehicle Routing Problems,” arXiv:2510.16701, 2025.",
        "Alaoui, Belhiah and Ziti, “IoT-Enabled Waste Management in Smart Cities: A Systematic Literature Review,” IJACSA, vol. 16, no. 4, 2025.",
        "Ishaque and Florence, “Intelligent Deep Learning-Based Classification with Vehicle Routing for MSW Management,” J. Hazardous Materials Advances, vol. 18, 2025.",
        "Reji et al., “Solid Waste Management System Based on IoT Using Swin Transformer with Ant Colony Optimization,” Global NEST Journal, vol. 27, no. 3, 2025.",
        "Gatti, Barbierato and Pozzi, “Toward Greener Smart Cities: A Critical Review of Classic and ML-Based Algorithms for Smart Bin Collection,” Electronics, vol. 13, no. 5, 2024.",
        "Ali et al., “IoT-Assisted Vehicle Route Optimization for Municipal Solid Waste Collection,” Applied Sciences, vol. 14, no. 1, 2024.",
        "Addas, Khan and Naseer, “Waste Management 2.0: Leveraging IoT for an Efficient and Eco-Friendly Smart City Solution,” PLoS ONE, vol. 19, 2024.",
        "Belhiah, El Aboudi and Ziti, “Optimising Unplanned Waste Collection: An IoT System in Tangier,” IET Smart Cities, vol. 6, no. 1, 2024.",
        "Hussain et al., “Comparative Analysis of Waste Management Models in IoT-Enabled Environments Using Multiagent Simulation,” Sustainable Cities and Society, vol. 103, 2024.",
        "Kona and Subramoniam, “Smart IoT-Based Waste Management with Shortest-Path Routing and DCNN Visit Decisions,” Peer-to-Peer Networking and Applications, vol. 17, no. 3, 2024.",
        "Sankar and Fathima, “IoT-Enabled Smart Waste Management: Sensor Technologies and Implementation Strategies,” Proc. ICICT, 2024.",
        "Çil et al., “Enhancing MSW Management Efficiency Through Clustering: A Case Study,” Taylor & Francis, 2024.",
        "Huang, Shi and Sukhatme, “From Words to Routes: Applying Large Language Models to Vehicle Routing,” arXiv:2403.10795, 2024.",
        "Xiao et al., “Chain-of-Experts: When LLMs Meet Complex Operations Research Problems,” ICLR, 2024.",
        "Miletić et al., “A Data Streaming Architecture for Air Quality Monitoring in Smart Cities,” 2023.",
        "Mishra, “Cloud-Based Smart Waste Management Using IoT and Predictive Analysis,” MSc thesis, National College of Ireland, 2023.",
        "Ahmed et al., “Forecasting the Status of Municipal Waste in Smart Bins Using Deep Learning,” IJERPH, vol. 19, no. 24, 2022.",
        "Vonitsanos et al., “An Apache Spark Framework for IoT-Enabled Waste Management in Smart Cities,” ACM, 2022.",
        "Salehi-Amiri et al., “Designing an Effective Two-Stage, Sustainable, and IoT-Based Waste Management System,” Renewable and Sustainable Energy Reviews, vol. 157, 2022.",
        "Anjum, Shahab and Umar, “Smart Waste Management Paradigm in Perspective of IoT and Forecasting Models,” Int. J. Environment and Waste Management, vol. 29, no. 1, 2022.",
        "Al Duhayyim et al., “Deep Reinforcement Learning Enabled Smart City Recycling Waste Object Classification,” CMC, vol. 71, no. 3, 2022.",
        "Vishnu et al., “IoT-Enabled Solid Waste Management in Smart Cities,” Smart Cities, vol. 4, no. 3, 2021.",
        "Aktemur, Erensoy and Kocyigit, “Optimization of Waste Collection in Smart Cities with Evolutionary Algorithms,” HORA, 2020.",
        "Apache Software Foundation, “Apache Kafka Documentation 3.7,” https://kafka.apache.org/documentation/.",
        "J. Kreps, N. Narkhede and J. Rao, “Kafka: A Distributed Messaging System for Log Processing,” NetDB Workshop, 2011.",
        "OpenCity / BBMP, “Bengaluru Solid Waste Management datasets (DWCC, processing plants, landfills, ward complaints),” https://opencity.in.",
    ]
    for i, r_ in enumerate(refs, 1):
        p = R.para(f"[{i}] {r_}", 11, align="left", space_after=3, line=1.15)
        p.paragraph_format.left_indent = Cm(0.9)
        p.paragraph_format.first_line_indent = Cm(-0.9)

    out = os.path.join(DOCS, "WASTEX_Project_Report.docx")
    d.save(out)
    print("report written:", out, "| figures:", len(R.figures), "| tables:", len(R.tables))


def fmt(v):
    if isinstance(v, (int, float)):
        return f"{v:,.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"
    return str(v)


if __name__ == "__main__":
    sys.path.insert(0, DOCS)
    build()
