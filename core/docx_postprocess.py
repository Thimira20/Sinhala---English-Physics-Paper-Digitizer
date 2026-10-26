"""
DOCX Post-Processor: modifies OpenXML in Pandoc-generated documents.
Injects Sinhala Complex Script (w:cs) fonts, mirrors bold/italic/size to CS properties (bCs, iCs, szCs),
fixes OMML Math runs (m:r) containing Sinhala text with correct schema element ordering (m:nor, w:rPr),
and restyles MCQ tables.
"""
import re
import logging
from pathlib import Path
from typing import Optional
from docx import Document
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

logger = logging.getLogger(__name__)

RE_SINHALA = re.compile(r"[\u0D80-\u0DFF]")

# OOXML standard sequence for w:rPr child elements
RPR_CHILD_ORDER = [
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
    "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
    "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
    "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
    "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang"
]

def insert_child_in_order(parent, new_child, tag_order):
    new_tag = new_child.tag.split("}")[-1] if "}" in new_child.tag else new_child.tag
    try:
        new_idx = tag_order.index(new_tag)
    except ValueError:
        parent.append(new_child)
        return

    for i, child in enumerate(parent):
        c_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        try:
            c_idx = tag_order.index(c_tag)
            if c_idx > new_idx:
                parent.insert(i, new_child)
                return
        except ValueError:
            continue
    parent.append(new_child)

def process_w_run(r_el, sinhala_font: str, latin_font: str):
    """Processes normal text runs (w:r)."""
    text_content = "".join([t.text for t in r_el.findall(qn("w:t")) if t.text])
    has_sinhala = bool(RE_SINHALA.search(text_content))

    rpr = r_el.find(qn("w:rPr"))
    if rpr is None:
        if not has_sinhala:
            return
        rpr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        r_el.insert(0, rpr)

    # 1. Update w:rFonts
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{latin_font}" w:hAnsi="{latin_font}" w:eastAsia="{latin_font}" w:cs="{sinhala_font}"/>')
        insert_child_in_order(rpr, rfonts, RPR_CHILD_ORDER)
    else:
        rfonts.set(qn("w:cs"), sinhala_font)
        if not rfonts.get(qn("w:ascii")):
            rfonts.set(qn("w:ascii"), latin_font)
        if not rfonts.get(qn("w:hAnsi")):
            rfonts.set(qn("w:hAnsi"), latin_font)

    # 2. Mirror Bold -> bCs
    if rpr.find(qn("w:b")) is not None:
        if rpr.find(qn("w:bCs")) is None:
            insert_child_in_order(rpr, parse_xml(f'<w:bCs {nsdecls("w")}/>'), RPR_CHILD_ORDER)

    # 3. Mirror Italic -> iCs
    if rpr.find(qn("w:i")) is not None:
        if rpr.find(qn("w:iCs")) is None:
            insert_child_in_order(rpr, parse_xml(f'<w:iCs {nsdecls("w")}/>'), RPR_CHILD_ORDER)

    # 4. Mirror Size -> szCs
    sz = rpr.find(qn("w:sz"))
    if sz is not None:
        sz_val = sz.get(qn("w:val"))
        sz_cs = rpr.find(qn("w:szCs"))
        if sz_cs is None:
            insert_child_in_order(rpr, parse_xml(f'<w:szCs {nsdecls("w")} w:val="{sz_val}"/>'), RPR_CHILD_ORDER)
        else:
            sz_cs.set(qn("w:val"), sz_val)

    # 5. Add bidi language for Sinhala runs
    if has_sinhala:
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            insert_child_in_order(rpr, parse_xml(f'<w:lang {nsdecls("w")} w:val="en-GB" w:bidi="si-LK"/>'), RPR_CHILD_ORDER)
        else:
            lang.set(qn("w:bidi"), "si-LK")

def process_omml_run(mr_el, sinhala_font: str = "Iskoola Pota"):
    """
    Processes Office Math runs (m:r) containing Sinhala characters.
    Ensures strict schema child ordering: m:rPr -> w:rPr -> m:t.
    Uses Iskoola Pota for equation math runs because Word's OMML engine requires
    Windows native complex script font tables for proper vowel mark positioning.
    """
    text_content = "".join([t.text for t in mr_el.findall(qn("m:t")) if t.text])
    if not RE_SINHALA.search(text_content):
        return # Latin/Greek math remains in Cambria Math

    # 1. m:rPr with m:nor (normal text) and m:sty
    mrpr = mr_el.find(qn("m:rPr"))
    if mrpr is None:
        mrpr = parse_xml(f'<m:rPr {nsdecls("m")}/>')
        mr_el.insert(0, mrpr)

    if mrpr.find(qn("m:nor")) is None:
        mrpr.append(parse_xml(f'<m:nor {nsdecls("m")}/>'))
    
    m_sty = mrpr.find(qn("m:sty"))
    if m_sty is None:
        mrpr.append(parse_xml(f'<m:sty {nsdecls("m")} m:val="p"/>'))

    # 2. w:rPr inside m:r, placed right after m:rPr and before m:t
    wrpr = mr_el.find(qn("w:rPr"))
    if wrpr is None:
        wrpr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        idx = list(mr_el).index(mrpr) + 1
        mr_el.insert(idx, wrpr)

    # Use Iskoola Pota inside equations for perfect glyph shaping in Word
    math_s_font = "Iskoola Pota"
    rfonts = wrpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{math_s_font}" w:hAnsi="{math_s_font}" w:cs="{math_s_font}"/>')
        wrpr.append(rfonts)
    else:
        rfonts.set(qn("w:ascii"), math_s_font)
        rfonts.set(qn("w:hAnsi"), math_s_font)
        rfonts.set(qn("w:cs"), math_s_font)

    lang = wrpr.find(qn("w:lang"))
    if lang is None:
        wrpr.append(parse_xml(f'<w:lang {nsdecls("w")} w:bidi="si-LK"/>'))
    else:
        lang.set(qn("w:bidi"), "si-LK")

def process_mcq_tables(doc_el):
    """
    Finds paragraphs with MCQMarker style, restyles the subsequent table to MCQTable (borderless),
    removes empty header row, and deletes the marker paragraph.
    """
    body = doc_el.find(qn("w:body"))
    if body is None:
        return

    children = list(body)
    to_remove = []

    for i, child in enumerate(children):
        if child.tag == qn("w:p"):
            pstyle = child.find(f".//{qn('w:pStyle')}")
            if pstyle is not None and pstyle.get(qn("w:val")) == "MCQMarker":
                to_remove.append(child)
                # Next sibling table
                if i + 1 < len(children) and children[i + 1].tag == qn("w:tbl"):
                    tbl = children[i + 1]
                    tbl_pr = tbl.find(qn("w:tblPr"))
                    if tbl_pr is not None:
                        # Set tblStyle to MCQTable
                        style_el = tbl_pr.find(qn("w:tblStyle"))
                        if style_el is not None:
                            style_el.set(qn("w:val"), "MCQTable")
                        else:
                            tbl_pr.insert(0, parse_xml(f'<w:tblStyle {nsdecls("w")} w:val="MCQTable"/>'))

                    # Remove empty header row if all cells are whitespace/empty
                    rows = tbl.findall(qn("w:tr"))
                    if rows:
                        first_row = rows[0]
                        cell_texts = ["".join([t.text for t in cell.findall(f".//{qn('w:t')}") if t.text]).strip() for cell in first_row.findall(qn("w:tc"))]
                        if all(len(t) == 0 for t in cell_texts):
                            tbl.remove(first_row)

    for marker in to_remove:
        body.remove(marker)

def fix_sinhala_and_styles(docx_path: Path, sinhala_font: str = "Noto Sans Sinhala", latin_font: str = "Noto Sans") -> None:
    """Main post-processor entry point."""
    doc = Document(str(docx_path))
    
    # 1. Main document body
    doc_el = doc.element
    for r_el in doc_el.findall(f".//{qn('w:r')}"):
        process_w_run(r_el, sinhala_font, latin_font)

    for mr_el in doc_el.findall(f".//{qn('m:r')}"):
        process_omml_run(mr_el, sinhala_font)

    process_mcq_tables(doc_el)

    # 2. Also process headers/footers if present
    for section in doc.sections:
        for hf in [section.header, section.footer]:
            if hf is not None:
                for r_el in hf._element.findall(f".//{qn('w:r')}"):
                    process_w_run(r_el, sinhala_font, latin_font)
                for mr_el in hf._element.findall(f".//{qn('m:r')}"):
                    process_omml_run(mr_el, sinhala_font)

    doc.save(str(docx_path))
    logger.info(f"Post-processing completed for {docx_path.name}")
