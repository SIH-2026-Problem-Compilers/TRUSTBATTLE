"""Fill the official AITHON 2.0 template with TRUSTBATTLE content.

Run from repo root:
    py scripts/fill_aithon_template.py

Input : AITHON_2.0_Presentation.pptx   (the official template - kept as-is)
Output: AITHON_2.0_TRUSTBATTLE_Submission.pptx

The template format is preserved: every template shape keeps its position,
size, font (Times New Roman), bullet formatting, logos and footer. We only
replace the [ placeholder ] body text and extend section bodies, adding a
few shapes only where the template provides room for them (slide 1 value
column, slide 2 highlight strip, slide 5 pathway sub-captions).
"""

from copy import deepcopy

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

SRC = "AITHON_2.0_Presentation.pptx"
DST = "AITHON_2.0_TRUSTBATTLE_Submission.pptx"

INK = RGBColor(0x0C, 0x0C, 0x0C)      # template body color
GREY = RGBColor(0x44, 0x44, 0x44)     # secondary text
FONT = "Times New Roman"

prs = Presentation(SRC)


# ------------------------------------------------------------- helpers ----
def set_body(tf, lines, size=12.5):
    """Replace a placeholder text frame with clean bullet lines.

    Template bullets (buChar) live on the paragraph level and are kept:
    we rebuild paragraphs and re-apply the char via XML to stay consistent
    with the template look.
    """
    def apply_bullet(p):
        pPr = p._p.get_or_add_pPr()
        for tag in ("a:buNone", "a:buAutoNum", "a:buChar"):
            for el in pPr.findall(
                    "{http://schemas.openxmlformats.org/drawingml/2006/main}"
                    f"{tag}"):
                pPr.remove(el)
        bu = pPr.makeelement(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}buChar",
            {"char": "\u2022"})
        # insert after any tab/font refs; append is fine for pptx readers
        pPr.append(bu)

    tf.word_wrap = True
    first = True
    for line in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        # clear existing runs
        for r in list(p.runs):
            r._r.getparent().remove(r._r)
        bold, rest = False, line
        if line.startswith("**") and "**" in line[2:]:
            end = line.index("**", 2)
            bold = True
            lead, rest = line[2:end], line[end + 2:]
        run = p.add_run()
        run.text = rest
        run.font.name = FONT
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = INK
        if bold:
            run2 = p.add_run()
            run2.text = " "
        apply_bullet(p)


def fill(shape, text, bold=None, size=None, color=None, keep_style=True):
    """Replace text in a single-line frame; lists go to the bullet writer."""
    if isinstance(text, list):
        set_body(shape.text_frame, text, size=size if size else 11)
        return None
    tf = shape.text_frame
    # remove all paragraphs except the first
    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    p = tf.paragraphs[0]
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    run = p.add_run()
    run.text = text
    if keep_style and p.runs:
        pass
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run.font.name = FONT
    return run


def by_name(slide, name):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    raise KeyError(f"shape {name!r} not found")


slides = list(prs.slides)
s1, s2, s3, s4, s5, s6, s7 = slides

# =========================================================== SLIDE 1 ======
# Track / title page. Keep the bullet labels, fill the value placeholders.
s1_map = {
    "Google Shape;14;p1": "AITHON 2.0 - Open Innovation",
    "Google Shape;15;p1": "AI-Driven Battlefield Information Integrity & "
                          "Trust Assessment",
    "Google Shape;16;p1": "Aerospace & Defence",
    "Google Shape;17;p1": "Software",
    "Google Shape;18;p1": "[ your Team ID ]",
    "Google Shape;19;p1": "[ your Team Name ]",
}
for name, val in s1_map.items():
    sh = by_name(s1, name)
    fill(sh, val, size=14.5)

# =========================================================== SLIDE 2 ======
fill(by_name(s2, "Google Shape;30;p2"),
     "TRUSTBATTLE - AI-Driven Battlefield Information Integrity & Trust "
     "Assessment Engine", size=12.5)
fill(by_name(s2, "Google Shape;32;p2"),
     "\u201cDon't just ask what the battlefield sensors are reporting - "
     "ask whether the information they report can be trusted.\u201d",
     size=12.5)
fill(by_name(s2, "Google Shape;34;p2"),
     "UAV, GNSS/IMU, visual and network data can be spoofed, replayed, "
     "jammed or faulty - and a manipulated measurement can look perfectly "
     "legitimate. Operators see what sensors report, but not whether each "
     "observation is trustworthy right now.", size=11)
fill(by_name(s2, "Google Shape;36;p2"),
     "An AI-assisted Information Integrity Layer between sensors and fusion: "
     "every observation gets a 0-100 trust score from five evidence streams "
     "(physical, temporal, cyber, cross-sensor, historical); suspicious "
     "sources are down-weighted in fusion, with a plain-language evidence "
     "checklist for the operator.", size=11)

# highlight strip in the empty top-right area (template has room: 7.2-9.4 x)
highlight = s2.shapes.add_textbox(Inches(6.95), Inches(1.15),
                                  Inches(2.50), Inches(2.30))
htf = highlight.text_frame
htf.word_wrap = True
diffs = [
    ("KEY DIFFERENTIATORS", None),
    ("Explainable evidence checklist, not a black-box score", "b"),
    ("Dynamic trust: drops in anomaly, recovers after - no permanent "
     "blacklisting", "b"),
    ("Trust-aware fusion: suspicious sources automatically down-weighted",
     "b"),
    ("Honest scope: integrity assessment, never claims \u201chacked\u201d "
     "without proof", "b"),
]
first = True
for text, style in diffs:
    p = htf.paragraphs[0] if first else htf.add_paragraph()
    first = False
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    if style is None:
        r.font.size = Pt(11.5)
        r.font.bold = True
    else:
        r.font.size = Pt(10)
        r.font.bold = False
    r.font.color.rgb = INK if style is None else GREY
    if style is not None:
        p.level = 1

# =========================================================== SLIDE 3 ======
fill(by_name(s3, "Google Shape;48;p3"), [
    "**Frontend / Backend:** React + Vite, Leaflet, Recharts; FastAPI, "
    "WebSocket, PostgreSQL",
    "**AI / ML:** scikit-learn Isolation Forest (primary), One-Class SVM, "
    "pandas/NumPy",
    "**Cloud & deployment:** modular Python packages on shared YAML "
    "config; any VM/host",
    "**Version control & CI/CD:** Git/GitHub, pytest suites, frozen data "
    "contracts",
], size=10.5)

fill(by_name(s3, "Google Shape;50;p3"), [
    "**Modular, layered:** M1 Physical, M2 Temporal, M4 Cyber -> M3 Trust "
    "Engine -> M5 Dashboard",
    "**AI/ML core logic:** Isolation Forest detectors -> Evidence Engine -> "
    "Trust Model (0-100)",
    "**Database / API:** stateless FastAPI + WebSocket push, SQLAlchemy to "
    "PostgreSQL",
    "**Secure, scalable flow:** calibrated thresholds; public datasets + "
    "controlled simulation",
], size=10.5)

# =========================================================== SLIDE 4 ======
fill(by_name(s4, "Google Shape;62;p4"), [
    "**Availability:** fully open-source stack; pipeline already runs "
    "end-to-end (integration/run_demo.py)",
    "**Development:** public GNSS datasets (TEXBAT) + synthetic attacks "
    "with ground truth; unsupervised IF needs no big labelled set",
], size=10.5)
fill(by_name(s4, "Google Shape;64;p4"), [
    "**Ease of implementation:** one layer on top of existing fusion - no "
    "sensor replacement",
    "**Ease of adoption:** trust %, green/amber/red states, plain-English "
    "evidence checklist",
], size=10.5)
fill(by_name(s4, "Google Shape;66;p4"), [
    "**Development cost:** zero licence fees - 100% open-source",
    "**Infrastructure:** lightweight models train in seconds on commodity "
    "hardware; simulation-first avoids test-range costs",
], size=10.5)
fill(by_name(s4, "Google Shape;68;p4"), [
    "**Future expansion:** V2 +Camera/EO -> V3 +Radar -> V4 multi-UAV -> "
    "V5 edge & real hardware",
    "**Long-term:** config-driven tuning; versioned data contracts + "
    "change-request governance keep it maintainable",
], size=10.5)

# =========================================================== SLIDE 5 ======
# Slide 5: numbered-card headers and pathway labels (Problem / Solution /
# Immediate Impact / Long-Term Impact) already exist in the template and are
# correct - leave them untouched, only add sub-captions below the pathway.

# pathway sub-captions: small textboxes under each chevron box
captions = [
    (0.77, "Unverifiable sensor data: spoofing / jamming / malfunction / "
           "deception"),
    (2.94, "Multi-evidence integrity layer + dynamic trust + trust-aware "
           "fusion"),
    (5.11, "Suspicious source down-weighted; evidence-backed alert; fusion "
           "stays accurate"),
    (7.28, "Resilient, explainable systems - transferable to AVs, drones, "
           "critical infrastructure"),
]
for x, text in captions:
    cap = s5.shapes.add_textbox(Inches(x), Inches(4.52), Inches(1.95),
                                Inches(0.75))
    ctf = cap.text_frame
    ctf.word_wrap = True
    p = ctf.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(8.5)
    r.font.color.rgb = GREY

# =========================================================== SLIDE 6 ======
fill(by_name(s6, "Google Shape;115;p6"), [
    "**Papers:** Liu et al., \u201cIsolation Forest\u201d (IEEE ICDM 2008); "
    "Sch\u00f6lkopf et al., One-Class SVM (Neural Computation 2001)",
    "**Existing solutions:** anti-jam GNSS / GPS firewalls, NIDS, Kalman "
    "fusion - each covers one fragment only",
    "**Industry / programmes:** U.S. Army SBIR \u201cEnsuring Sensor Data "
    "Security & Integrity\u201d; India's SANJAY battlefield surveillance "
    "system",
    "**Documented threats:** GNSS spoofing vs UAVs in the Russia-Ukraine "
    "conflict; decoys & electronic deception",
    "**Datasets:** UT Austin TEXBAT GPS spoofing battery; our synthetic "
    "UAV telemetry with labelled attacks at 0-30% corruption",
], size=10)

fill(by_name(s6, "Google Shape;117;p6"), [
    "**1.** Liu, Ting & Zhou, \u201cIsolation Forest\u201d, IEEE ICDM, 2008.",
    "**2.** Sch\u00f6lkopf et al., Neural Computation, 2001 (One-Class "
    "SVM).",
    "**3.** Humphreys et al., UT Austin Radionavigation Lab - TEXBAT "
    "(radionavlab.ae.utexas.edu).",
    "**4.** U.S. Army SBIR topic (armysbir.com).",
    "**5.** PIB releases on SANJAY (pib.gov.in).",
    "**6.** Official docs: scikit-learn, FastAPI, React/Vite, Leaflet.",
], size=10)

# =========================================================== SLIDE 7 ======
keep = {
    "Google Shape;127;p7", "Google Shape;128;p7", "Google Shape;129;p7",
    "Google Shape;130;p7", "Google Shape;131;p7", "Google Shape;132;p7",
    "Google Shape;133;p7", "Google Shape;134;p7",
}
# Slide 7 is the organizers' checklist - leave every line untouched.

prs.save(DST)
print(f"saved {DST} ({len(prs.slides)} slides)")
