"""
Generates assets/reference.docx programmatically with Sinhala Complex Script (w:cs)
and Noto Sans fonts configured for all standard styles, callouts, and MCQ tables.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
REF_DOCX = ASSETS_DIR / "reference.docx"
HASH_FILE = ASSETS_DIR / "reference.hash"

def get_config_font_settings():
    config_file = PROJECT_ROOT / "config.json"
    if not config_file.exists():
        config_file = PROJECT_ROOT / "config.default.json"
    
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "sinhala_font": data.get("sinhala_font", "Noto Sans Sinhala"),
        "latin_font": data.get("latin_font", "Noto Sans"),
        "body_font_size_pt": data.get("body_font_size_pt", 11),
        "line_spacing": data.get("line_spacing", 1.15)
    }

def get_pandoc_executable() -> str:
    # 1. Try pypandoc
    try:
        import pypandoc
        try:
            return pypandoc.get_pandoc_path()
        except Exception:
            pass
    except ImportError:
        pass

    # 2. Try which/where
    pandoc_path = shutil.which("pandoc")
    if pandoc_path:
        return pandoc_path

    # 3. Try auto download via pypandoc if available
    try:
        import pypandoc
        print("Pandoc not found. Attempting download via pypandoc...")
        pypandoc.download_pandoc()
        return pypandoc.get_pandoc_path()
    except Exception as e:
        raise RuntimeError(f"Could not locate or download Pandoc: {e}")

def dump_default_reference_docx(pandoc_exe: str, target: Path):
    cmd = [pandoc_exe, "-o", str(target), "--print-default-data-file", "reference.docx"]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        # Fallback using stdout redirection
        cmd2 = [pandoc_exe, "--print-default-data-file", "reference.docx"]
        res2 = subprocess.run(cmd2, capture_output=True)
        if res2.returncode == 0 and len(res2.stdout) > 0:
            target.write_bytes(res2.stdout)
        else:
            raise RuntimeError(f"Failed to dump default reference.docx: {res.stderr.decode('utf-8', errors='ignore')}")

def modify_styles(docx_path: Path, settings: dict):
    from docx import Document
    from docx.oxml import parse_xml, OxmlElement
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.style import WD_STYLE_TYPE
    import lxml.etree as etree

    doc = Document(str(docx_path))
    s_font = settings["sinhala_font"]
    l_font = settings["latin_font"]
    body_sz = int(settings["body_font_size_pt"] * 2) # half-points
    line_rule_val = str(int(settings["line_spacing"] * 240)) # 240 = single line

    # 1. Configure Page setup: A4, 20mm (1134 twips) margins
    for section in doc.sections:
        section.page_width = Inches(8.27)  # A4 210mm
        section.page_height = Inches(11.69) # A4 297mm
        section.top_margin = Inches(0.79)   # ~20mm
        section.bottom_margin = Inches(0.79)
        section.left_margin = Inches(0.79)
        section.right_margin = Inches(0.79)

    # 2. Modify styles element
    styles_el = doc.styles.element

    # Update or inject docDefaults / rPrDefault
    doc_defaults = styles_el.find(qn("w:docDefaults"))
    if doc_defaults is None:
        doc_defaults = parse_xml(f'<w:docDefaults {nsdecls("w")}/>')
        styles_el.insert(0, doc_defaults)
    
    rpr_default = doc_defaults.find(qn("w:rPrDefault"))
    if rpr_default is None:
        rpr_default = parse_xml(f'<w:rPrDefault {nsdecls("w")}/>')
        doc_defaults.append(rpr_default)
        
    rpr = rpr_default.find(qn("w:rPr"))
    if rpr is None:
        rpr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        rpr_default.append(rpr)

    # Set default fonts and lang in rPrDefault
    fonts_xml = f'<w:rFonts {nsdecls("w")} w:ascii="{l_font}" w:hAnsi="{l_font}" w:eastAsia="{l_font}" w:cs="{s_font}"/>'
    sz_xml = f'<w:sz {nsdecls("w")} w:val="{body_sz}"/>'
    sz_cs_xml = f'<w:szCs {nsdecls("w")} w:val="{body_sz}"/>'
    lang_xml = f'<w:lang {nsdecls("w")} w:val="en-GB" w:bidi="si-LK"/>'

    for xml_snip, tag in [(fonts_xml, "w:rFonts"), (sz_xml, "w:sz"), (sz_cs_xml, "w:szCs"), (lang_xml, "w:lang")]:
        old = rpr.find(qn(tag))
        if old is not None:
            rpr.remove(old)
        rpr.append(parse_xml(xml_snip))

    # Helper to style paragraph style XML
    def configure_style(style_id, name, is_heading=False, sz_pt=11, bold=False, color="000000", space_before_pt=0, space_after_pt=6):
        style = None
        for s in styles_el.findall(qn("w:style")):
            if s.get(qn("w:styleId")) == style_id:
                style = s
                break
        if style is None:
            style = parse_xml(f'<w:style {nsdecls("w")} w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/></w:style>')
            styles_el.append(style)

        s_rpr = style.find(qn("w:rPr"))
        if s_rpr is None:
            s_rpr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
            style.append(s_rpr)
            
        s_ppr = style.find(qn("w:pPr"))
        if s_ppr is None:
            s_ppr = parse_xml(f'<w:pPr {nsdecls("w")}/>')
            style.append(s_ppr)

        # Fonts
        old_fonts = s_rpr.find(qn("w:rFonts"))
        if old_fonts is not None:
            s_rpr.remove(old_fonts)
        s_rpr.append(parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{l_font}" w:hAnsi="{l_font}" w:eastAsia="{l_font}" w:cs="{s_font}"/>'))

        # Sizes
        half_pts = str(int(sz_pt * 2))
        for tag in ["w:sz", "w:szCs"]:
            old = s_rpr.find(qn(tag))
            if old is not None:
                s_rpr.remove(old)
        s_rpr.append(parse_xml(f'<w:sz {nsdecls("w")} w:val="{half_pts}"/>'))
        s_rpr.append(parse_xml(f'<w:szCs {nsdecls("w")} w:val="{half_pts}"/>'))

        # Bold
        for tag in ["w:b", "w:bCs"]:
            old = s_rpr.find(qn(tag))
            if old is not None:
                s_rpr.remove(old)
        if bold:
            s_rpr.append(parse_xml(f'<w:b {nsdecls("w")}/>'))
            s_rpr.append(parse_xml(f'<w:bCs {nsdecls("w")}/>'))

        # Color
        old_color = s_rpr.find(qn("w:color"))
        if old_color is not None:
            s_rpr.remove(old_color)
        if color != "000000":
            s_rpr.append(parse_xml(f'<w:color {nsdecls("w")} w:val="{color}"/>'))

        # Lang
        old_lang = s_rpr.find(qn("w:lang"))
        if old_lang is not None:
            s_rpr.remove(old_lang)
        s_rpr.append(parse_xml(f'<w:lang {nsdecls("w")} w:val="en-GB" w:bidi="si-LK"/>'))

        # Spacing
        old_spacing = s_ppr.find(qn("w:spacing"))
        if old_spacing is not None:
            s_ppr.remove(old_spacing)
        sb = str(int(space_before_pt * 20))
        sa = str(int(space_after_pt * 20))
        s_ppr.append(parse_xml(f'<w:spacing {nsdecls("w")} w:before="{sb}" w:after="{sa}" w:line="{line_rule_val}" w:lineRule="auto"/>'))

    # Configure Headings and Normal
    configure_style("Normal", "Normal", sz_pt=settings["body_font_size_pt"], space_before_pt=0, space_after_pt=4)
    configure_style("Heading1", "Heading 1", is_heading=True, sz_pt=16, bold=True, color="1F3864", space_before_pt=12, space_after_pt=6)
    configure_style("Heading2", "Heading 2", is_heading=True, sz_pt=13, bold=True, color="1F3864", space_before_pt=10, space_after_pt=4)
    configure_style("Heading3", "Heading 3", is_heading=True, sz_pt=12, bold=True, color="1F3864", space_before_pt=8, space_after_pt=3)

    # Configure Block Text (> blockquote in Pandoc)
    # Shading: #F2F2F2, left border 3pt #A6A6A6, left indent 0.25in
    block_style = None
    for s in styles_el.findall(qn("w:style")):
        if s.get(qn("w:styleId")) in ("BlockText", "BlockQuote"):
            block_style = s
            break
    if block_style is None:
        block_style = parse_xml(f'<w:style {nsdecls("w")} w:type="paragraph" w:styleId="BlockText"><w:name w:val="Block Text"/></w:style>')
        styles_el.append(block_style)

    b_ppr = block_style.find(qn("w:pPr"))
    if b_ppr is None:
        b_ppr = parse_xml(f'<w:pPr {nsdecls("w")}/>')
        block_style.append(b_ppr)
    
    # Clean old borders, shading, indent
    for tag in ["w:pBdr", "w:shd", "w:ind", "w:spacing"]:
        el = b_ppr.find(qn(tag))
        if el is not None:
            b_ppr.remove(el)
    
    b_ppr.append(parse_xml(f'<w:pBdr {nsdecls("w")}><w:left w:val="single" w:sz="24" w:space="12" w:color="A6A6A6"/></w:pBdr>'))
    b_ppr.append(parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="F2F2F2"/>'))
    b_ppr.append(parse_xml(f'<w:ind {nsdecls("w")} w:left="360" w:right="360"/>'))
    b_ppr.append(parse_xml(f'<w:spacing {nsdecls("w")} w:before="120" w:after="120" w:line="{line_rule_val}" w:lineRule="auto"/>'))

    # Configure MCQMarker paragraph style (hidden, 1pt)
    mcq_marker = styles_el.find(f".//w:style[@w:styleId='MCQMarker']", namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"})
    if mcq_marker is None:
        mcq_marker = parse_xml(f'''
            <w:style {nsdecls("w")} w:type="paragraph" w:styleId="MCQMarker">
                <w:name w:val="MCQMarker"/>
                <w:pPr>
                    <w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/>
                </w:pPr>
                <w:rPr>
                    <w:vanish/>
                    <w:sz w:val="2"/>
                    <w:szCs w:val="2"/>
                </w:rPr>
            </w:style>
        ''')
        styles_el.append(mcq_marker)

    # Configure MCQTable style (borderless table, full width)
    mcq_table = styles_el.find(f".//w:style[@w:styleId='MCQTable']", namespaces={"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"})
    if mcq_table is None:
        mcq_table = parse_xml(f'''
            <w:style {nsdecls("w")} w:type="table" w:styleId="MCQTable">
                <w:name w:val="MCQ Table"/>
                <w:basedOn w:val="TableNormal"/>
                <w:tblPr>
                    <w:tblW w:w="5000" w:type="pct"/>
                    <w:tblBorders>
                        <w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>
                        <w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>
                        <w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>
                        <w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>
                        <w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>
                        <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>
                    </w:tblBorders>
                    <w:tblCellMar>
                        <w:top w:w="80" w:type="dxa"/>
                        <w:left w:w="120" w:type="dxa"/>
                        <w:bottom w:w="80" w:type="dxa"/>
                        <w:right w:w="120" w:type="dxa"/>
                    </w:tblCellMar>
                </w:tblPr>
            </w:style>
        ''')
        styles_el.append(mcq_table)

    doc.save(str(docx_path))
    print(f"Updated styles in {docx_path.name} with Noto fonts and custom styles.")

def compute_settings_hash(settings: dict) -> str:
    s = json.dumps(settings, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def ensure_reference_docx(custom_settings: dict = None) -> Path:
    settings = custom_settings or get_config_font_settings()
    current_hash = compute_settings_hash(settings)

    if REF_DOCX.exists() and HASH_FILE.exists():
        try:
            if HASH_FILE.read_text(encoding="utf-8").strip() == current_hash:
                return REF_DOCX
        except Exception:
            pass

    pandoc_exe = get_pandoc_executable()
    dump_default_reference_docx(pandoc_exe, REF_DOCX)
    modify_styles(REF_DOCX, settings)
    HASH_FILE.write_text(current_hash, encoding="utf-8")
    return REF_DOCX

def main():
    print("=== Reference DOCX Generator ===")
    ref = ensure_reference_docx()
    print(f"reference.docx successfully built and saved to {ref}")

if __name__ == "__main__":
    main()
