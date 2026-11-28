"""Build the IEEE conference paper (.docx) on the STEI ITB template.

Run with an environment that has python-docx, lxml and latex2mathml:
    python build_paper.py <template.docx> <output.docx>
Equations are native Word equations (LaTeX -> MathML -> OMML through Office's MML2OMML.XSL).
Tables are computed from campaigns/PoU-TA-Proteksi-Adaptif/results.jsonl.
"""
import copy
import json
import os
import re
import sys

import latex2mathml.converter as l2m
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIG = os.path.join(HERE, "figures")
XSL = etree.XSLT(etree.parse(r"C:/Program Files/Microsoft Office/root/Office16/MML2OMML.XSL"))
FONT = "Book Antiqua"
COLW = 5040            # one column, twips
FULLW = 10368          # full text width, twips

# ------------------------------------------------------------------ data for the tables
R = {}
with open(os.path.join(ROOT, "campaigns", "PoU-TA-Proteksi-Adaptif", "results.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        R[r["key"]] = r
R = list(R.values())
CODES = ["F-1", "F-2", "F-3", "F-4", "F-5", "F-6", "NT"]


def failed(r, ex=()):
    return any(r["counts"].get(c, 0) for c in CODES if c not in ex)


def pct(S, ex=()):
    return 100.0 * sum(failed(r, ex) for r in S) / max(len(S), 1)


# ------------------------------------------------------------------ low-level helpers
def set_font(run, size=10, bold=None, italic=None, color=None, smallcaps=False):
    run.font.name = FONT
    rpr = run._r.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), FONT)
    run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if smallcaps:
        run.font.small_caps = True
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def omml(latex):
    mml = l2m.convert(latex)
    return copy.deepcopy(XSL(etree.fromstring(mml)).getroot())


def pfmt(p, align="both", first=0.17, before=0, after=0, line=1.0, keep=False):
    pf = p.paragraph_format
    pf.alignment = {"both": WD_ALIGN_PARAGRAPH.JUSTIFY, "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "left": WD_ALIGN_PARAGRAPH.LEFT}[align]
    pf.first_line_indent = Inches(first) if first else None
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    pf.keep_with_next = keep
    pf.widow_control = True


class Paper:
    def __init__(self, template):
        self.doc = Document(template)
        body = self.doc.element.body
        sects = body.findall(".//" + qn("w:sectPr"))
        self.sect_first = copy.deepcopy(sects[0])          # first page: logo header, title page
        self.sect_two = copy.deepcopy(sects[1])            # two columns, continuous
        for pn in self.sect_two.findall(qn("w:pgNumType")):
            self.sect_two.remove(pn)
        for c in list(body):
            body.remove(c)
        final = copy.deepcopy(self.sect_two)
        body.append(final)
        self.body = body
        self.eq_no = 0
        self.fig_no = 0
        self.tab_no = 0

    # paragraphs -------------------------------------------------
    def p(self, text="", size=10, align="both", first=0.17, italic=False, bold=False, before=0, after=0, keep=False):
        if text[:1].islower():
            first = 0
        p = self.doc.add_paragraph()
        pfmt(p, align, first, before, after, keep=keep)
        self.rich(p, text, size, italic, bold)
        return p

    def rich(self, p, text, size=10, italic=False, bold=False):
        """$...$ inline math, **bold**, *italic* in body text."""
        for part in re.split(r"(\$[^$]+\$)", text):
            if not part:
                continue
            if part.startswith("$"):
                p._p.append(omml(part[1:-1]))
                continue
            for seg in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", part):
                if not seg:
                    continue
                if seg.startswith("**"):
                    set_font(p.add_run(seg[2:-2]), size, bold=True, italic=italic)
                elif seg.startswith("*"):
                    set_font(p.add_run(seg[1:-1]), size, bold=bold, italic=True)
                else:
                    set_font(p.add_run(seg), size, bold=bold, italic=italic)

    def h1(self, num, text):
        p = self.doc.add_paragraph()
        pfmt(p, "left", 0, before=9, after=4, keep=True)
        set_font(p.add_run(f"{num}.\u2002{text}" if num else text), 11, bold=True)

    def h2(self, num, text):
        p = self.doc.add_paragraph()
        pfmt(p, "left", 0, before=5, after=2, keep=True)
        set_font(p.add_run(f"{num}.\u2002{text}"), 10, bold=True, italic=True)

    def eq(self, latex, width=COLW):
        self.eq_no += 1
        p = self.doc.add_paragraph()
        pfmt(p, "left", 0, before=7, after=7)
        ts = p.paragraph_format.tab_stops
        ts.add_tab_stop(Pt(width / 20 / 2), WD_TAB_ALIGNMENT.CENTER)
        ts.add_tab_stop(Pt(width / 20), WD_TAB_ALIGNMENT.RIGHT)
        set_font(p.add_run("\t"), 10)
        p._p.append(omml(latex))
        set_font(p.add_run(f"\t({self.eq_no})"), 10)
        return self.eq_no

    def bullet(self, text, size=10):
        p = self.doc.add_paragraph()
        pfmt(p, "both", 0, after=2)
        p.paragraph_format.left_indent = Inches(0.2)
        p.paragraph_format.first_line_indent = Inches(-0.15)
        p.paragraph_format.tab_stops.add_tab_stop(Inches(0.2))
        set_font(p.add_run("•	"), size)
        self.rich(p, text, size)
        return p

    # sections ---------------------------------------------------
    def section_break(self, two_cols, first=False):
        p = self.doc.add_paragraph()
        pfmt(p, "left", 0, line=1.0)
        p.paragraph_format.space_after = Pt(0)
        sp = copy.deepcopy(self.sect_first if first else self.sect_two)
        if not first and not two_cols:
            cols = sp.find(qn("w:cols"))
            if cols is not None:
                sp.remove(cols)
        pPr = p._p.get_or_add_pPr()
        pPr.append(sp)
        # the break paragraph itself is tiny so it adds no visible gap
        set_font(p.add_run(""), 2)
        p.paragraph_format.line_spacing = Pt(2)

    # figures ----------------------------------------------------
    def fig(self, name, caption, double=False, width=None):
        self.fig_no += 1
        if double:
            self.section_break(two_cols=True)
        p = self.doc.add_paragraph()
        pfmt(p, "center", 0, before=4, after=2, keep=True)
        p.add_run().add_picture(os.path.join(FIG, name + ".png"), width=Inches(width or (7.1 if double else 3.45)))
        c = self.doc.add_paragraph()
        pfmt(c, "both" if not double else "center", 0, before=0, after=6)
        set_font(c.add_run(f"Fig. {self.fig_no}.\u2002"), 8, bold=True)
        self.rich(c, caption, 8)
        if double:
            self.section_break(two_cols=False)
        return self.fig_no

    # tables -----------------------------------------------------
    def table(self, title, header, rows, widths, double=False, notes=None, bold_last=False):
        self.tab_no += 1
        roman = ["I", "II", "III", "IV", "V", "VI", "VII"][self.tab_no - 1]
        if double:
            self.section_break(two_cols=True)
        c1 = self.doc.add_paragraph()
        pfmt(c1, "center", 0, before=6, after=0, keep=True)
        set_font(c1.add_run(f"TABLE {roman}"), 8)
        c2 = self.doc.add_paragraph()
        pfmt(c2, "center", 0, before=0, after=3, keep=True)
        set_font(c2.add_run(title), 8, smallcaps=True)
        t = self.doc.add_table(rows=1 + len(rows), cols=len(header))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        tw = sum(widths)
        tblPr = t._tbl.tblPr
        for tag in ("w:tblW",):
            e = tblPr.find(qn(tag))
            if e is None:
                e = OxmlElement(tag); tblPr.append(e)
            e.set(qn("w:w"), str(tw)); e.set(qn("w:type"), "dxa")
        lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
        borders = OxmlElement("w:tblBorders")
        for edge, sz in (("top", 10), ("bottom", 10), ("left", 0), ("right", 0), ("insideH", 0), ("insideV", 0)):
            b = OxmlElement(f"w:{edge}")
            b.set(qn("w:val"), "single" if sz else "nil")
            if sz:
                b.set(qn("w:sz"), str(sz)); b.set(qn("w:color"), "333333"); b.set(qn("w:space"), "0")
            borders.append(b)
        tblPr.append(borders)
        mar = OxmlElement("w:tblCellMar")
        for side, v in (("left", 90), ("right", 90), ("top", 40), ("bottom", 40)):
            m = OxmlElement(f"w:{side}"); m.set(qn("w:w"), str(v)); m.set(qn("w:type"), "dxa"); mar.append(m)
        tblPr.append(mar)
        grid = t._tbl.tblGrid
        for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
            gc.set(qn("w:w"), str(w))
        for i, row in enumerate([header] + rows):
            tr = t.rows[i]
            for j, val in enumerate(row):
                cell = tr.cells[j]
                cell.width = Pt(widths[j] / 20)
                tcPr = cell._tc.get_or_add_tcPr()
                tcw = tcPr.find(qn("w:tcW"))
                if tcw is None:
                    tcw = OxmlElement("w:tcW"); tcPr.append(tcw)
                tcw.set(qn("w:w"), str(widths[j])); tcw.set(qn("w:type"), "dxa")
                if i == 0:
                    tb = OxmlElement("w:tcBorders"); bb = OxmlElement("w:bottom")
                    bb.set(qn("w:val"), "single"); bb.set(qn("w:sz"), "6"); bb.set(qn("w:color"), "333333")
                    tb.append(bb); tcPr.append(tb)
                if bold_last and i == len(rows):
                    tb = OxmlElement("w:tcBorders"); bb = OxmlElement("w:top")
                    bb.set(qn("w:val"), "single"); bb.set(qn("w:sz"), "4"); bb.set(qn("w:color"), "333333")
                    tb.append(bb); tcPr.append(tb)
                para = cell.paragraphs[0]
                pfmt(para, "left" if j == 0 else "center", 0, line=1.0)
                self.rich(para, str(val), 7.5, bold=(i == 0) or (bold_last and i == len(rows)))
                para.paragraph_format.keep_with_next = i < len(rows)
            trPr = tr._tr.get_or_add_trPr()
            cs = OxmlElement("w:cantSplit"); trPr.append(cs)
        if notes:
            n = self.doc.add_paragraph()
            pfmt(n, "both", 0, before=2, after=6)
            self.rich(n, notes, 7)
        else:
            sp = self.doc.add_paragraph(); pfmt(sp, "left", 0, after=4)
            sp.paragraph_format.line_spacing = Pt(4)
        if double:
            self.section_break(two_cols=False)

    def finish(self, out, running_title):
        # running header (pages 2 and later)
        for part in self.doc.part.package.parts:
            pn = str(part.partname)
            if pn.startswith("/word/header") or pn.startswith("/word/footer"):
                xml = part.blob.decode("utf-8") if hasattr(part, "blob") else None
        for rel in list(self.doc.part.rels.values()):
            if "header" in rel.reltype:
                hdr = rel.target_part
                el = hdr.element
                for t in el.iter(qn("w:t")):
                    if t.text and t.text.startswith("Thyristor"):
                        t.text = running_title
                    elif t.text and t.text.startswith("Program Studi"):
                        t.text = "Electrical Power Engineering, School of Electrical Engineering and Informatics, ITB"
        # drop template images that the new body no longer uses
        used = set(re.findall(r'r:embed="([^"]+)"', etree.tostring(self.body).decode()))
        for rid, rel in list(self.doc.part.rels.items()):
            if rel.reltype.endswith("/image") and rid not in used:
                del self.doc.part.rels[rid]
        self.doc.save(out)


# ------------------------------------------------------------------ content
TITLE = ("Numerical Study of Conventional Protection Failure in Radial Distribution Systems under "
         "Distributed Energy Resource Penetration: A Case Study of the IEEE 34-Bus Test Feeder")
RUNNING = "Conventional Protection Failure under DER Penetration: IEEE 34-Bus Test Feeder Case Study"


def build(template, out):
    P = Paper(template)
    d = P.doc

    # ---------------- header block (one column)
    a = d.add_paragraph(); pfmt(a, "left", 0)
    set_font(a.add_run("Electrical Power Engineering Study Program, School of Electrical Engineering and Informatics, "
                       "Institut Teknologi Bandung, West Java, Indonesia."), 8)
    a2 = d.add_paragraph(); pfmt(a2, "left", 0, after=10)
    set_font(a2.add_run("Jl. Ganesa No. 10, Lb. Siliwangi, Coblong, Bandung, West Java 40132."), 8, italic=True)
    t = d.add_paragraph(); pfmt(t, "center", 0, before=4, after=10, line=1.0)
    set_font(t.add_run(TITLE), 16, bold=True)
    authors = [("Della Cyntia Putri Sibagariang", "18023040@std.stei.itb.ac.id"),
               ("Yusuf Aji Nugraha", "18023047@std.stei.itb.ac.id")]
    at = d.add_table(rows=1, cols=2); at.alignment = WD_TABLE_ALIGNMENT.CENTER
    for j, (name, mail) in enumerate(authors):
        cell = at.rows[0].cells[j]
        cell.width = Inches(3.0)
        q = cell.paragraphs[0]; pfmt(q, "center", 0)
        set_font(q.add_run(name), 9.5)
        q2 = cell.add_paragraph(); pfmt(q2, "center", 0)
        set_font(q2.add_run("Institut Teknologi Bandung"), 9)
        q3 = cell.add_paragraph(); pfmt(q3, "center", 0)
        set_font(q3.add_run(mail or "Bandung, Indonesia"), 9, color="1F1F1F" if not mail else "8A3F33")
    ab = d.add_paragraph(); pfmt(ab, "center", 0, before=12, after=4)
    set_font(ab.add_run("Abstract"), 10, bold=True)
    P.p("Protection of radial medium-voltage feeders rests on two premises: power flows from a single upstream source, "
        "and the fault current available at each relay is fixed by that source and the feeder impedance. Distributed "
        "energy resources (DER) violate both premises, yet the resulting misoperation of fixed-setting protection is "
        "usually argued from a few hand-picked cases rather than measured across the operating space. A full-factorial "
        "campaign of 5,247 phasor-domain simulations of the IEEE 34-bus test feeder, extended with an adjacent feeder, "
        "quantifies that misoperation. Overcurrent, directional overcurrent, distance and line differential relays are set "
        "once at zero DER and peak load and then held fixed while synchronous and grid-following inverter DER rated 20% to "
        "120% of the feeder peak load are connected at five sites, under three load levels, four fault resistances and "
        "eleven fault cases. A rule-based classifier compares every relay decision with a radial ground truth and with the "
        "same fault simulated without DER. Apart from one coordination defect of the base settings, the 99 DER-free "
        "reference cases operate correctly, whereas 49.6% of the 5,148 DER cases contain at least one misoperation. "
        "Excluding sustained DER backfeed into unintentional islands, the rate still grows from 8.6% at 20% penetration "
        "to 32.2% at 120%, while dependability falls from 99.0% to 95.5% and security from 100% to 96.5%. The "
        "zero-sequence path of the DER interconnection transformer, rather than the generator technology, emerges as "
        "the dominant cause of blinding, sympathetic tripping and instantaneous overreach.",
        size=9, italic=True, first=0)
    it = d.add_paragraph(); pfmt(it, "both", 0, before=4, after=8)
    set_font(it.add_run("Index Terms: "), 9, bold=True, italic=True)
    set_font(it.add_run("distributed energy resources, protection blinding, sympathetic tripping, protection "
                        "coordination, inverter-based resources, IEEE 34-bus test feeder, phasor simulation, "
                        "adaptive protection."), 9, italic=True)
    P.section_break(two_cols=False, first=True)

    # ---------------- I. Introduction
    P.h1("I", "Introduction")
    P.p("Medium-voltage distribution feeders are protected by overcurrent relays, reclosers and fuses that are "
        "coordinated by time grading. Their settings are computed once from a short-circuit study under two premises: "
        "power flows in one direction from the substation to the loads, and the fault current seen by every device is "
        "fixed by the substation source and the series impedance of the feeder [3], [8], [22]. Under these premises a "
        "relay that sees more current than its pickup is facing a fault in front of it, and a relay closer to the fault "
        "always sees at least as much current as the relays upstream of it.")
    P.p("Distributed energy resources (DER) remove both premises. The share of DER on distribution networks is "
        "growing worldwide and, in Indonesia, is driven by the renewable targets of the national electricity supply "
        "plan [23]. A synchronous generator contributes several times its rated current during a fault [10], whereas "
        "an inverter-based resource (IBR) limits its contribution to about 1.1 to 1.5 per unit and shapes it by its "
        "control loops [16]. The interconnection transformer adds a further source: a winding grounded on the "
        "network side creates a zero-sequence path that did not exist when the settings were made [11]. The "
        "literature names the resulting failure modes: protection blinding, sympathetic tripping of healthy feeders, "
        "loss of coordination, false directional decisions, impedance under-reach, failed reclosing and unintentional "
        "islanding [11], [12], [14], [15], [24].")
    P.p("Each of these failures has a direct operational cost. A blinded relay leaves a fault energized for "
        "hundreds of milliseconds or longer, so the voltage dip at every customer lasts longer and the fault energy "
        "at the arc and in the equipment grows. A sympathetic or miscoordinated trip disconnects customers who were "
        "not affected by the fault and misleads the operator about its location. A DER that keeps feeding a fault "
        "after the feeder breaker has opened turns an automatic reclose into a reclose onto a live fault and exposes "
        "line crews to an energized circuit. At the bulk-system level, disturbance reports have already shown that "
        "the fault response of inverter-based plants can propagate a local fault into a large loss of generation [20], [21].")
    P.p("Adaptive protection schemes [13], [18], [19] and the reviews of protection for networks with high DER shares "
        "[17], [26] take the failure of fixed settings as their starting point. The evidence for that failure is, "
        "however, mostly built from a small number of selected scenarios, typically one DER technology, one relay "
        "principle and one or two fault positions. How often fixed settings fail across the operating space, how the "
        "failure scales with penetration, load and fault resistance, which relay principles are most exposed, and "
        "which physical mechanism is responsible are rarely quantified on a standard benchmark with reproducible "
        "setting rules. Without that quantification the urgency of replacing fixed settings remains a qualitative argument.")
    P.p("The contribution of the work reported here is a numerical proof of that urgency on the IEEE 34-bus test "
        "feeder [1], [2]: (i) a reproducible phasor-domain model of the feeder with explicit DER, relay and setting "
        "models; (ii) a formal taxonomy of seven misoperation codes, each defined as a predicate against a radial "
        "ground truth and against the same fault without DER; (iii) a full-factorial campaign of 5,247 cases that "
        "measures failure rates, dependability and security against penetration, load, fault resistance, relay "
        "principle, DER technology and DER location; and (iv) the identification of the physical mechanisms behind "
        "the failures. Section II describes the models, Section III the campaign and the classification, Section IV "
        "the results, and Section V concludes.")

    # ---------------- II. System modeling
    P.h1("II", "System Modeling and Architecture")
    P.h2("A", "Test Feeder")
    P.p("Feeder A is the IEEE 34-bus test feeder [1], [2], a long and lightly loaded 24.9 kV, 60 Hz radial feeder "
        "with unbalanced spot and distributed loads totalling 1,769 kW at peak, two step-voltage regulators "
        "(814 to 850 and 852 to 832), an in-line 24.9/4.16 kV, 500 kVA transformer (832 to 888), and shunt capacitor "
        "banks at buses 844 and 848. The substation is a 69/24.9 kV, 2.5 MVA transformer with an impedance of "
        "1 + j8% on its rating. An equivalent three-phase Feeder B (buses B01 to B05, 465 kW) is supplied from the "
        "same bus 800 so that a healthy adjacent feeder exists for every fault on Feeder A and vice versa. Fig. 1 shows "
        "the network as modeled, with the five candidate DER sites, the grid-forming site of the islanded campaign, "
        "the six fault locations and the five protection points.")
    P.fig("fig1_network", "Single-line diagram of the studied network: IEEE 34-bus test feeder (Feeder A) and an "
          "equivalent adjacent Feeder B supplied from bus 800. Dashed circles mark the candidate DER sites, the "
          "grid-forming site and the candidate fault locations with their fault types; each case places one DER at one "
          "site and one fault at one location.",
          double=True)
    P.p("Every line section is represented by its phase-impedance matrix, obtained from the published conductor "
        "configurations 300 to 304 after Kron reduction and multiplied by the section length [3]. The voltage drop "
        "across a section is therefore")
    P.eq(r"\mathbf{V}_{abc}^{(i)}-\mathbf{V}_{abc}^{(j)}=\mathbf{z}_{abc}\,\ell_{ij}\,\mathbf{I}_{abc}^{(ij)}")
    P.p("in which the phase voltages at the sending and receiving buses, the per-length impedance matrix, the section "
        "length and the phase currents of the section appear from left to right. Shunt line capacitance is neglected, "
        "since its charging current is below 0.1 A at 24.9 kV. Loads are represented as constant admittances "
        "evaluated at nominal voltage, the usual choice for fault studies, and distributed loads are lumped equally at "
        "both ends of their section:", first=0)
    P.eq(r"Y_{L}=\frac{S_{L}^{*}}{\left|V_{n}\right|^{2}}")
    P.p("so that the load admittance equals the conjugate of the rated complex power divided by the square of the "
        "nominal voltage magnitude. The regulators are ideal per-phase transformers held at the published tap "
        "positions. At every time step the network is solved as a nodal phasor problem,", first=0)
    P.eq(r"\mathbf{Y}\left(t_{k}\right)\mathbf{V}\left(t_{k}\right)=\mathbf{I}_{s}\left(t_{k}\right)")
    P.p("where the admittance matrix contains the line, load, transformer and breaker admittances and the injection "
        "vector holds the DER currents, updated from the voltages of the previous step. Breakers open 50 ms after a "
        "trip command.", first=0)

    P.h2("B", "Distributed Energy Resource Models")
    P.p("The apparent power rating of a DER unit equals its penetration level multiplied by the Feeder A peak load of "
        "1,769 kW, with the penetration level ranging from 0.2 to 1.2, that is from 354 kVA to 2,123 kVA. Every unit is "
        "connected through a transformer grounded wye on the network side and delta on the DER side, with a "
        "zero-sequence impedance of 0.01 + j0.06 pu on the DER rating. This winding offers the feeder a "
        "zero-sequence path regardless of the generator technology.")
    P.p("The synchronous generator (SG) is a constant internal voltage behind a reactance that decays from the "
        "subtransient to the synchronous value after fault inception, following the AC decrement of IEC 60909 [10]:")
    P.eq(r"X\left(\tau\right)=X_{d}+\left(X_{d}^{\prime}-X_{d}\right)e^{-\tau/T_{d}^{\prime}}+\left(X_{d}^{\prime\prime}-X_{d}^{\prime}\right)e^{-\tau/T_{d}^{\prime\prime}}")
    P.p("where the subtransient, transient and synchronous reactances are 0.15, 0.25 and 1.0 pu, the subtransient and "
        "transient time constants are 0.03 s and 0.6 s, the time is counted from fault inception, and the excitation "
        "is constant. The grid-following inverter (GFL) is a positive-sequence current source synchronized to the "
        "measured voltage. Its reference follows the active-power setpoint in normal operation and the reactive-current "
        "priority of fault ride-through [5] when the positive-sequence voltage drops below 0.9 pu:", first=0)
    P.eq(r"i_{q}=k_{q}\left(0.9-v_{1}\right),\qquad \left|i_{d}+j\,i_{q}\right|\le I_{max}")
    P.p("The reactive current thus grows with a gain of 2 per unit of voltage depression, and the total output current "
        "is limited to 1.2 pu with a first-order response of one cycle; no negative-sequence current is injected. The "
        "grid-forming unit (GFM), used only in the islanded campaign, is a voltage source behind a virtual impedance "
        "with a current limit of 1.3 pu. Every unit applies the Category III ride-through of IEEE 1547-2018 and ceases "
        "to energize an unintentional island within 2 s [4], so the DER remains connected during the 1.3 s that "
        "follow the fault in every case, as the standard permits.", first=0)

    P.h2("C", "Relay Models and Frozen Settings")
    P.p("Five intelligent electronic devices are placed at the feeder head A1 (800 to 802), the midline recloser A2 "
        "(828 to 830), the downstream recloser A3 (858 to 834), the single-phase lateral recloser L1 (816 to 818) "
        "and the head of Feeder B, B1. Each device can operate as non-directional overcurrent (OCR: 50/51P, 50/51N), "
        "directional overcurrent (DOCR: 67P with quadrature polarization and a maximum torque angle of 45 degrees, "
        "67N with negative-sequence polarization and zero-sequence fallback), three-zone mho distance (DIST: 21P/21G "
        "with residual compensation [9]), or two-ended percentage-restraint line differential (DIFF: 87L between A1 "
        "and A2 and between A2 and A3 with a 5 ms channel). Every element operates on the phasor obtained with a "
        "one-cycle moving window, equivalent in response to a full-cycle discrete Fourier transform:")
    P.eq(r"\bar{I}\left[k\right]=\frac{1}{N}\sum_{n=0}^{N-1}I\left[k-n\right],\qquad N=\frac{f_{s}}{f_{0}}=16")
    P.p("with sixteen samples per cycle. The time-overcurrent elements follow the IEC standard inverse "
        "characteristic [6], [7]:", first=0)
    P.eq(r"t_{op}=\mathrm{TMS}\,\frac{0.14}{\left(I/I_{p}\right)^{0.02}-1}")
    P.p("where the operating time is the time multiplier setting times a function of the ratio between the measured "
        "current and the pickup current. The settings are computed once for the base condition (no DER, peak load, "
        "capacitors in service, published taps) and then frozen for the whole campaign, which is the defining "
        "property of conventional protection. The 51P pickup is 1.5 times the maximum load current through the relay; "
        "the 51N pickup is the largest of twice the residual current due to load unbalance, 0.3 times the 51P pickup "
        "and 6 A. Time multipliers are graded from downstream to upstream with a design coordination time interval "
        "(CTI) of 0.3 s, evaluated at the maximum fault current at the location of the downstream relay:", first=0)
    P.eq(r"t_{u}\left(I_{f,max}^{(d)}\right)\ge t_{d}\left(I_{f,max}^{(d)}\right)+\mathrm{CTI}")
    P.p("Instantaneous elements 50P/50N exist only on relays that have a downstream relay and are set to 1.25 times "
        "the maximum fault current at the downstream relay location, so that they cannot overreach it in the base "
        "condition. The distance zones reach 80% and 120% of the protected section impedance (0 s and 0.3 s) and "
        "the following section (0.8 s). A measured loop impedance is inside a zone when it lies within the mho "
        "circle whose diameter is the zone reach along the line angle:", first=0)
    P.eq(r"\left|Z_{m}-\frac{Z_{r}}{2}\right|\le\frac{\left|Z_{r}\right|}{2},\qquad Z_{m}=\frac{V_{\phi}}{I_{\phi}+k_{0}\,3I_{0}}")
    P.p("where the loop impedance is the phase voltage divided by the phase current compensated by the residual "
        "current, and the residual compensation factor is the difference between the zero- and positive-sequence line "
        "impedances divided by three times the positive-sequence impedance. The 87L element operates on a phase when "
        "the differential current exceeds both a fixed threshold and 30% of the mean through current:", first=0)
    P.eq(r"\left|I_{L}+I_{R}\right|>\max\left(I_{87},\;0.3\,\frac{\left|I_{L}\right|+\left|I_{R}\right|}{2}\right)")
    P.p("The fixed threshold is the largest of 1.5 times the base differential current from tapped loads, 0.2 times "
        "the 51P pickup and 5 A. Table I summarizes the model parameters and Table II the resulting settings.", first=0)
    P.table("Model Parameters",
            ["Item", "Value"],
            [["Feeder A", "IEEE 34-bus, 24.9 kV, 60 Hz, peak 1,769 kW"],
             ["Substation", "69/24.9 kV, 2.5 MVA, 1 + j8%, 1.075 pu"],
             ["Feeder B", "B01 to B05, 24.9 kV, 465 kW"],
             ["Interface", "YgD, Z0T = 0.01 + j0.06 pu"],
             ["SG", "X''d 0.15, X'd 0.25, Xd 1.0 pu; T''d 0.03 s, T'd 0.6 s"],
             ["GFL", "Imax 1.2 pu, kq 2, lag 1 cycle, no I2"],
             ["GFM (islanded)", "Imax 1.3 pu"],
             ["DER protection", "IEEE 1547 Cat. III; island trip 2 s"],
             ["Solution", "phasor; dt = 1/960 s; breaker 50 ms"],
             ["Time line", "fault 0.3 s; end 1.6 s"]],
            [1450, 3550])
    S = json.load(open(os.path.join(ROOT, "campaigns", "PoU-TA-Proteksi-Adaptif", "campaign.json")))["relay_settings"]

    def fmt(v, nd=0):
        return "n/a" if v is None else (f"{v:.{nd}f}")
    rows = []
    for iid in ("A1", "A2", "A3", "L1", "B1"):
        s = S[iid]
        rows.append([iid, f"{fmt(s['51P_pu'])} / {s['51P_tms']:.2f}",
                     f"{fmt(s['51N_pu'])} / {s['51N_tms']:.2f}" if s["51N_pu"] else "n/a",
                     f"{fmt(s['50P_pu'])} / {fmt(s['50N_pu'])}" if s["50P_pu"] else "n/a",
                     f"{s['zreach'][0]:.2f}", fmt(s["87_pu"])])
    P.table("Frozen Relay Settings (Primary Amperes and Ohms)",
            ["IED", "51P pickup / TMS", "51N pickup / TMS", "50P / 50N", "Z1 reach", "87L pickup"],
            rows, [500, 1000, 1000, 850, 750, 900],
            notes="Curve IEC standard inverse; Z2 = 1.5 Z1 at 0.3 s and Z3 at 0.8 s; 87L slope 30%. L1 protects a "
                  "single-phase lateral and has no 51N element; A3, L1 and B1 have no downstream relay and therefore "
                  "no instantaneous element.")

    P.h2("D", "Simulation Engine")
    P.p("The network, DER and breakers are built as a Simscape Electrical model [25] solved in phasor mode at the "
        "fundamental frequency with a step of 1/960 s, and the relay elements act on the resulting phasors. The model "
        "is not an electromagnetic transient (EMT) model. The choice is justified because every relay decision "
        "examined here is taken on fundamental-frequency phasors from a one-cycle filter, because short-circuit and "
        "coordination practice is itself phasor based [8], [10], and because a campaign of several thousand cases is "
        "tractable in the phasor domain but not in EMT [27]. Inverter switching, sub-cycle control dynamics, current "
        "transformer saturation and negative-sequence inverter control are therefore outside the scope. A separately "
        "implemented nodal phasor solver with identical component models agrees with the engine within 1.6% in bus "
        "voltages and branch currents and gives identical classifications on a pilot of 121 cases, and all cases "
        "are deterministic and individually reproducible.")

    # ---------------- III. Scenarios and studies
    P.h1("III", "Scenarios and Studies")
    P.h2("A", "Scenario Space and Campaign Design")
    P.p("A case is defined by seven factors: the DER technology (SG or GFL), the DER bus (806, 828, 840, 848 or B03), "
        "the penetration level, the load level (40%, 70% or 100% of peak), the fault resistance (0, 5, 20 or 50 Ω), the "
        "fault case and the relay class. The eleven fault cases are single line-to-ground (SLG) and three-phase (3PH) "
        "faults at buses 812, 830, 834, 848 and B04 and an SLG fault on the single-phase lateral at 822. Each case "
        "contains one permanent fault applied at 0.3 s and is simulated to 1.6 s. Four campaigns vary one pair of "
        "factors around a common base (Table III), and each contains its own DER-free cases. Fig. 2 summarizes the flow from scenario to classification.")
    def n(c):
        return f"{sum(r['campaign'] == c for r in R):,}"
    camp_rows = [["H1", "0 to 120", "40, 70, 100", "0", "OCR", n("H1")],
                 ["H2", "0 to 120", "100", "5, 20, 50", "OCR", n("H2")],
                 ["E", "0, 40, 80, 120", "100", "0", "DOCR, DIST, DIFF", n("E")],
                 ["I", "60, 90, 120", "40", "0", "OCR, DOCR", n("I")],
                 ["Total", "", "", "", "", f"{len(R):,}"]]
    P.table("Campaign Design", ["Set", "Pen. (%)", "Load (%)", "Rf (Ω)", "Relay class", "Cases"], camp_rows,
            [600, 900, 950, 700, 1100, 750],
            notes="Pen.: DER rating in % of Feeder A peak load, steps of 20% in H1 and H2. DER buses 806, 828, 840, 848, "
                  "B03 (SG, GFL); set I: GFM at 824 with GFL at 806, 840, 848. Eleven fault cases per level.",
            bold_last=True)
    P.fig("fig2_method", "Campaign and classification flow. Each case is simulated once; the relay decisions are "
          "judged against the radial ground truth and against the DER-free anchor of the same case.")
    P.h2("B", "Ground Truth and Anchor")
    P.p("For every fault, the relays on the radial path from bus 800 to the faulted bus are ordered from the source. "
        "The last relay on that path is the primary relay, the one before it is the backup relay, and every relay "
        "outside the path must not trip. The ground truth is therefore the one that the base settings were designed "
        "for. Every DER case also has an anchor: the same load, fault resistance, fault case and relay class without "
        "DER, simulated in the same campaign. Comparing a case with its anchor separates the effect of DER from the "
        "behaviour of the frozen settings themselves.")
    P.h2("C", "Misoperation Predicates")
    P.p("The Fault Hunter classifier evaluates every relay decision from fault inception to 50 ms after the fault ends. "
        "The trip delay of a relay is its trip time measured from fault inception, and the minimum acceptable "
        "coordination margin is 0.2 s. A case can carry several codes. Table IV lists the quantity tested for each code; "
        "the three threshold tests are written out below.")
    P.table("Fault Hunter Misoperation Codes",
            ["Code", "Name", "Tested quantity", "Flag when"],
            [["F-1", "blinding", "primary trip delay", "none or (11)"],
             ["F-2", "sympathetic", "trips outside fault path", "1 or more"],
             ["F-3", "coordination", "upstream minus primary time", "below 0.2 s (12)"],
             ["F-4", "directional", "direction off / on path", "forward / reverse"],
             ["F-5", "under-reach", "zone 1 trip, Z inside Z1", "none"],
             ["F-6", "backfeed", "fault current after cut", "above 1 A (13)"],
             ["NT", "nuisance", "trips on load or late", "1 or more"]],
            [600, 1050, 2100, 1250])
    P.p("**F-1, delayed clearing.** A primary relay that clears the fault is still counted as blinded when its trip "
        "delay exceeds both twice the anchor delay and the anchor delay plus the 0.2 s margin:", first=0)
    P.eq(r"d_{p}>\max\left(2\,d_{p}^{0},\;d_{p}^{0}+0.2\ \mathrm{s}\right)")
    P.p("Doubling alone would flag harmless changes of a few milliseconds in instantaneous trips, and the margin alone "
        "would miss slow trips that double; both conditions together isolate a material loss of speed.", first=0)
    P.p("**F-3, loss of coordination.** An upstream relay on the fault path violates coordination when it trips less "
        "than the margin after the primary relay, or before it:", first=0)
    P.eq(r"t_{u}-t_{p}<0.2\ \mathrm{s}")
    P.p("The test also covers a backup relay whose remaining operating time, projected from its timer progress at the "
        "moment the primary trips, is shorter than the margin.", first=0)
    P.p("**F-6, sustained backfeed.** After the first breaker on the fault path opens, the fault is checked for current "
        "from 0.1 s later to the end of the run:", first=0)
    P.eq(r"\left|I_{f}\left(t\right)\right|>1\ \mathrm{A},\qquad t_{cut}+0.1\ \mathrm{s}\le t\le t_{end}")
    P.p("F-6 reflects the coordination between DER interface protection and feeder protection rather than a relay "
        "error, so the rates below are reported both with and without it.", first=0)
    P.p("Each relay decision is also scored in a confusion matrix, the relays that should trip being the primary and, "
        "if the primary fails, the backup. The failure rate of a set of cases is the share of cases carrying at least "
        "one code, and the dependability and security follow from the matrix:")
    P.eq(r"D=\frac{TP}{TP+FN},\qquad S=\frac{TN}{TN+FP}")
    P.p("that is, dependability is the share of required trips that occur and security the share of trips that are "
        "correctly withheld.", first=0)

    # ---------------- IV. Results
    P.h1("IV", "Results and Discussion")
    P.h2("A", "Reference Behaviour and Aggregate Results")
    P.p("Without DER, the frozen settings operate correctly in 98 of the 99 anchor cases (Fig. 3a). The single "
        "exception is the SLG fault on the lateral at 822 with 87L protection, where A1 trips before L1 because the "
        "lateral lies inside the A1 to A2 differential zone; this zone-design defect is excluded from the DER effect "
        "by the anchor comparison. With DER, 685 relay decisions become wrong (Fig. 3b), and 49.6% of the 5,148 DER "
        "cases carry at least one code, 20.6% when F-6 is excluded (Table V).")
    P.fig("fig9_conf", "Confusion matrices of relay decisions in the grid-connected campaigns: (a) DER-free anchors; "
          "(b) DER cases. Percentages are per row.")
    rows = []
    for camp in ("H1", "H2", "E", "I"):
        Sd = [r for r in R if r["campaign"] == camp and r["fleet"] != "none"]
        rows.append([camp, f"{len(Sd):,}", f"{pct(Sd):.1f}", f"{pct(Sd, ('F-6',)):.1f}"] +
                    [str(sum(1 for r in Sd if r['counts'].get(c, 0))) for c in CODES])
    Sd = [r for r in R if r["fleet"] != "none"]
    rows.append(["All", f"{len(Sd):,}", f"{pct(Sd):.1f}", f"{pct(Sd, ('F-6',)):.1f}"] +
                [f"{sum(1 for r in Sd if r['counts'].get(c, 0)):,}" for c in CODES])
    P.table("Misoperation in the DER Cases by Campaign",
            ["Set", "Cases", "Rate (%)", "w/o F-6 (%)", "F-1", "F-2", "F-3", "F-4", "F-5", "F-6", "NT"],
            rows, [1000, 950, 900, 1150, 780, 780, 780, 780, 780, 850, 780], double=True, bold_last=True,
            notes="Rate: share of DER cases with at least one code; code columns count cases carrying the code. "
                  "DER-free cases are excluded.")
    P.h2("B", "Penetration, Load and Fault Resistance")
    P.p("With all codes counted, the rate jumps to about 40% at the first penetration step because F-6 occurs "
        "whenever a DER lies downstream of the clearing breaker, whatever its size (Fig. 4a). Without F-6 it grows "
        "with penetration, from 8.5% to 43.0% for SG and from 7.9% to 32.7% for GFL, and dependability and security "
        "fall to 95.5% and 96.5% at 120% (Fig. 4b). Light load is worse than peak load at high penetration, and a "
        "larger fault resistance lowers the rate (Fig. 5).")
    P.fig("fig3_rate", "(a) Share of OCR cases with misoperation in campaign H1 against penetration, for each DER "
          "technology, with and without F-6. (b) Dependability and security over all grid-connected cases.", double=True)
    P.fig("fig4_heat", "Share of OCR cases with misoperation, excluding F-6: (a) penetration against load level at "
          "zero fault resistance; (b) penetration against fault resistance at peak load.", double=True)
    P.h2("C", "Relay Principle, DER Location and Fault Position")
    P.p("Distance protection is the most robust class and line differential protection the most exposed; "
        "directional overcurrent removes sympathetic trips but adds directional errors (Fig. 6). The DER location "
        "decides which code appears (Fig. 7): a DER at 806 blinds A1, a DER at 828 makes A2 overreach, a DER at "
        "840 or 848 trips A3 sympathetically, and a DER at B03 trips B1 on reverse load flow. Fig. 8 shows that SLG "
        "faults dominate, because every mechanism except reverse load flow acts through the zero-sequence network.")
    P.fig("fig5_class", "Share of cases carrying each code by relay class and penetration (peak load, bolted faults, "
          "110 DER cases per bar). A case can carry several codes.")
    P.fig("fig10_site", "Share of OCR cases (campaigns H1 and H2) carrying each code by DER bus and technology.")
    P.fig("fig11_matrix", "Share of OCR cases with misoperation, excluding F-6, for each fault case and DER bus "
          "(campaigns H1 and H2, all penetration levels).")

    P.h2("D", "Classification by Failure Cases")
    P.p("**F-1 blinding (224 cases).** The grounded winding of the DER transformer divides the zero-sequence fault "
        "current between the DER branch and the substation path, so the residual current reaching an upstream "
        "relay falls:", first=0)
    P.eq(r"3I_{0}^{(relay)}=3I_{0}^{(f)}\,\frac{Z_{0T}}{Z_{0T}+Z_{0S}+Z_{0L}}")
    P.p("where the relay current equals the fault residual current scaled by the DER transformer zero-sequence "
        "impedance over the total impedance of both paths. With a DER at 806, the residual current at A1 for an "
        "SLG fault at 812 falls from 334 A to between 170 A and 305 A, below the 50N setting of 325 A, and only the "
        "inverse-time 51N element clears the fault (Fig. 9). The primary trip delay rises from a median of 16 ms to "
        "0.57 s to 0.75 s, identical for SG and GFL (Fig. 10), which confirms that the transformer and not the "
        "generator is responsible. The lower band in Fig. 10 is A2, delayed to about 0.2 s by a DER at 840 or 848. "
        "In the islanded campaign the current-limited sources cannot reach pickups set for grid fault levels, and "
        "110 of the 198 cases are F-1.", first=0)
    P.fig("fig6_wave", "SLG fault at 812 with an SG of 120% at 806 and its DER-free anchor: (a) residual current at "
          "A1, which drops below the 50N setting so that only the delayed 51N element operates; (b) fault current, "
          "which persists after A1 opens because the DER keeps feeding it (F-6).", double=True)
    P.fig("fig12_delay", "Primary trip delay in the F-1 cases of campaigns H1 and H2 against penetration. The dashed "
          "line is the median delay of the same faults without DER.")
    P.p("**F-2 sympathetic tripping (420 cases).** A DER at 840 or 848 lies downstream of A3, and its grounded "
        "winding drives residual current backward through A3 for SLG faults at 812 and 830; the non-directional 51N "
        "of A3 with an 18 A pickup trips in 285 of the 420 cases. A DER at B03 does the same to B1.", first=0)
    P.p("**F-3 miscoordination (173 cases).** A DER at 828, immediately upstream of A2, lowers the zero-sequence "
        "impedance seen from faults beyond A2. For an SLG fault at 834 the residual current through A2 rises from "
        "150 A to 207 A with a GFL of 40%, above the 50N setting of 187 A, so A2 trips in 15 ms instead of letting A3 "
        "clear the fault in 0.15 s (Fig. 11); 149 of the 173 cases have a DER at 828.", first=0)
    P.fig("fig7_tcc", "Residual-current coordination of A1, A2 and A3 for an SLG fault at 834. Without DER, A3 clears "
          "the fault on its 51N curve; with a GFL of 40% at 828 the current through A2 exceeds its 50N setting and A2 "
          "trips first.")
    P.p("**F-4 directional error (68 cases).** All cases involve DOCR with a DER behind the relay: the angle of an "
        "inverter current is set by its controller, and the negative-sequence polarizing quantities are weak.", first=0)
    P.p("**F-5 under-reach (18 cases).** Infeed between the relay and the fault raises the apparent impedance:", first=0)
    P.eq(r"Z_{m}=Z_{1a}+\left(1+\frac{I_{DER}}{I_{R}}\right)Z_{1b}")
    P.p("where the first and second terms are the impedances from the relay to the DER bus and from the DER bus to "
        "the fault, the latter magnified by the ratio of DER current to relay current. For an SLG fault at 848, a GFL "
        "of 40% at 840 moves the impedance seen by A3 from zone 1 into zone 2 (Fig. 12).", first=0)
    P.fig("fig8_rx", "Mho characteristic of A3 and the impedance measured for an SLG fault at 848, without DER and "
          "with a GFL of 40% at 840; infeed moves the measured impedance from zone 1 to zone 2.")
    P.p("**F-6 sustained backfeed (1,655 cases).** After the path breaker opens, the DER, its transformer and the "
        "faulted section form an unintentional island that ride-through keeps energized. The backfeed current at "
        "the end of the run has a median of 20 A in campaigns H1 and H2 and grows with penetration, from 10 A (SG) "
        "and 3.5 A (GFL) at 20% to 62 A and 31 A at 120% (Fig. 13). A reclose onto such a fault fails.", first=0)
    P.fig("fig13_backfeed", "Fault current at the end of the run in the F-6 cases of campaigns H1 and H2, by "
          "penetration and technology (box: quartiles; whiskers: 1.5 interquartile range).")
    P.p("**NT nuisance trip (225 cases).** With a DER of 100% or more at B03, the export through B1 exceeds the 19 A "
        "pickup of its 51P, set for the light Feeder B load (137 cases). A DER inside the A1 to A2 differential zone "
        "at 80% or more injects current that the two ends do not measure, and the 87L trips before any fault "
        "(88 cases). Table VI lists the dominant DER bus and relay per code.", first=0)
    mech = [["F-1", "224", "806 (86)", "A1 (87)"],
            ["F-2", "420", "840, 848 (364)", "A3 (338)"],
            ["F-3", "173", "828 (149)", "A2 (144)"],
            ["F-4", "68", "840, 848 (40)", "A3 (38)"],
            ["F-5", "18", "840 (14)", "A3 (14)"],
            ["F-6", "1,655", "840, 848 (1,142)", "n/a"],
            ["NT", "225", "B03 (137)", "B1 (137)"]]
    P.table("Dominant DER Bus and Relay per Code", ["Code", "Cases", "DER bus (cases)", "Relay (findings)"], mech,
            [700, 900, 1900, 1500],
            notes="DER cases of all campaigns; a case can carry several codes and several findings.")

    # ---------------- V. Conclusion
    P.h1("V", "Conclusion")
    P.p("The full-factorial phasor-domain campaign of 5,247 cases on the IEEE 34-bus test feeder supports the "
        "following conclusions.")
    for b in [
        "Conventional protection with settings frozen at zero DER operates correctly in 98 of the 99 DER-free cases, "
        "the exception being a zone-design defect of the 87L scheme.",
        "Once DER is connected, 49.6% of the 5,148 cases contain at least one misoperation, and 20.6% when sustained "
        "backfeed into unintentional islands is not counted.",
        "The failure rate without backfeed rises with penetration from 8.6% at 20% to 32.2% at 120%; it is higher "
        "at light load and lower for high-resistance faults, and dependability and security fall to 95.5% and 96.5%.",
        "Distance protection is the most robust principle, line differential protection the most exposed, and "
        "directional overcurrent trades sympathetic trips for directional errors.",
        "The zero-sequence path of the DER interconnection transformer, independent of the generator technology, is "
        "the dominant mechanism: it blinds elements upstream of the DER, makes them overreach downstream relays and "
        "drives reverse residual current through healthy relays.",
        "Every failure is tied to observable DER states (online status, location, grounding and loading), which "
        "establishes both the urgency of adaptive protection for the feeder and the state variables it must track.",
        "Electromagnetic transient verification of representative cases and inverter models with negative-sequence "
        "control are the next steps.",
    ]:
        P.bullet(b)

    # ---------------- references
    P.h1("", "References".strip())
    refs = [
        'W. H. Kersting, "Radial distribution test feeders," IEEE Trans. Power Syst., vol. 6, no. 3, pp. 975-985, Aug. 1991.',
        'IEEE PES Distribution System Analysis Subcommittee, "IEEE 34 Node Test Feeder," IEEE PES Distribution Test Feeders, 2010.',
        'W. H. Kersting, Distribution System Modeling and Analysis, 4th ed. Boca Raton, FL, USA: CRC Press, 2017.',
        'IEEE Standard for Interconnection and Interoperability of Distributed Energy Resources with Associated Electric Power Systems Interfaces, IEEE Std 1547-2018, 2018.',
        'IEEE Standard for Interconnection and Interoperability of Inverter-Based Resources (IBRs) Interconnecting with Associated Transmission Electric Power Systems, IEEE Std 2800-2022, 2022.',
        'IEEE Standard for Inverse-Time Characteristics Equations for Overcurrent Relays, IEEE Std C37.112-2018, 2019.',
        'Measuring Relays and Protection Equipment, Part 151: Functional Requirements for Over/Under Current Protection, IEC 60255-151:2009, 2009.',
        'IEEE Guide for Protective Relay Applications to Distribution Lines, IEEE Std C37.230-2020, 2021.',
        'IEEE Guide for Protective Relay Applications to Transmission Lines, IEEE Std C37.113-2015, 2016.',
        'Short-Circuit Currents in Three-Phase A.C. Systems, Part 0: Calculation of Currents, IEC 60909-0:2016, 2016.',
        'P. P. Barker and R. W. de Mello, "Determining the impact of distributed generation on power systems. I. Radial distribution systems," in Proc. IEEE PES Summer Meeting, Seattle, WA, USA, 2000, vol. 3, pp. 1645-1656.',
        'N. Hadjsaid, J.-F. Canard, and F. Dumas, "Dispersed generation impact on distribution networks," IEEE Comput. Appl. Power, vol. 12, no. 2, pp. 22-28, Apr. 1999.',
        'S. M. Brahma and A. A. Girgis, "Development of adaptive protection scheme for distribution systems with high penetration of distributed generation," IEEE Trans. Power Del., vol. 19, no. 1, pp. 56-63, Jan. 2004.',
        'K. Kauhaniemi and L. Kumpulainen, "Impact of distributed generation on the protection of distribution networks," in Proc. 8th IEE Int. Conf. Developments in Power System Protection, Amsterdam, The Netherlands, 2004, pp. 315-318.',
        'C. J. Mozina, "Impact of green power distributed generation," IEEE Ind. Appl. Mag., vol. 16, no. 4, pp. 55-62, Jul./Aug. 2010.',
        'J. Keller and B. Kroposki, "Understanding fault characteristics of inverter-based distributed energy resources," National Renewable Energy Laboratory, Golden, CO, USA, Tech. Rep. NREL/TP-550-46698, Jan. 2010.',
        'A. Hooshyar and R. Iravani, "Microgrid protection," Proc. IEEE, vol. 105, no. 7, pp. 1332-1353, Jul. 2017.',
        'E. Sortomme, S. S. Venkata, and J. Mitra, "Microgrid protection using communication-assisted digital relays," IEEE Trans. Power Del., vol. 25, no. 4, pp. 2789-2796, Oct. 2010.',
        'H. J. Laaksonen, "Protection principles for future microgrids," IEEE Trans. Power Electron., vol. 25, no. 12, pp. 2910-2918, Dec. 2010.',
        'North American Electric Reliability Corporation, "1,200 MW fault induced solar photovoltaic resource interruption disturbance report," Atlanta, GA, USA, Jun. 2017.',
        'North American Electric Reliability Corporation and Texas Reliability Entity, "Odessa disturbance," Atlanta, GA, USA, Sep. 2021.',
        'J. L. Blackburn and T. J. Domin, Protective Relaying: Principles and Applications, 4th ed. Boca Raton, FL, USA: CRC Press, 2014.',
        'PT PLN (Persero), "Rencana Usaha Penyediaan Tenaga Listrik (RUPTL) PT PLN (Persero) 2025-2034," Jakarta, Indonesia, 2025.',
        'A. Girgis and S. Brahma, "Effect of distributed generation on protective device coordination in distribution system," in Proc. Large Engineering Systems Conf. Power Engineering (LESCOPE), Halifax, NS, Canada, 2001, pp. 115-119.',
        'The MathWorks, Inc., Simscape Electrical User\'s Guide (Specialized Power Systems), Release R2024b. Natick, MA, USA, 2024.',
        'M. Norshahrani, H. Mokhlis, A. H. A. Bakar, J. J. Jamian, and S. Sukumar, "Progress on protection strategies to mitigate the impact of renewable distributed generation on distribution systems," Energies, vol. 10, no. 11, Art. no. 1864, 2017.',
        'J. Mahseredjian, V. Dinavahi, and J. A. Martinez, "Simulation tools for electromagnetic transients in power systems: Overview and challenges," IEEE Trans. Power Del., vol. 24, no. 3, pp. 1657-1669, Jul. 2009.',
    ]
    for i, ref in enumerate(refs, 1):
        q = d.add_paragraph()
        pfmt(q, "both", 0, after=1)
        q.paragraph_format.left_indent = Inches(0.3)
        q.paragraph_format.first_line_indent = Inches(-0.3)
        set_font(q.add_run(f"[{i}]\t"), 8)
        set_font(q.add_run(re.sub(r'"([^"]+)"', r"“\1”", ref)), 8)
        q.paragraph_format.tab_stops.add_tab_stop(Inches(0.3))
    P.section_break(two_cols=True)
    last = P.body.findall(qn("w:sectPr"))[-1]
    for c in last.findall(qn("w:cols")):
        last.remove(c)
    P.finish(out, RUNNING)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
