"""
Microsoft Word COM automation via pywin32.
Used for embedding TrueType fonts into DOCX (enabling correct rendering on any machine)
and high-fidelity PDF export preserving OMML math and Sinhala complex scripts.
"""
import logging
from pathlib import Path
import threading
import time

logger = logging.getLogger(__name__)

_WORD_LOCK = threading.Lock()

class WordUnavailable(Exception):
    """Raised when Microsoft Word is not installed or COM automation fails."""
    pass

def embed_fonts(docx_path: Path, timeout_sec: int = 60) -> bool:
    """
    Opens the DOCX in MS Word in background, sets EmbedTrueTypeFonts=True,
    SaveSubsetFonts=False, saves and closes.
    """
    abs_path = str(docx_path.resolve())
    with _WORD_LOCK:
        import pythoncom
        import win32com.client as win32

        pythoncom.CoInitialize()
        word = None
        doc = None
        try:
            logger.info(f"Opening Word to embed fonts in {docx_path.name}")
            word = win32.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0 # wdAlertsNone

            doc = word.Documents.Open(abs_path, ReadOnly=False, AddToRecentFiles=False)
            doc.EmbedTrueTypeFonts = True
            doc.SaveSubsetFonts = False
            doc.DoNotEmbedSystemFonts = True
            doc.Save()
            logger.info(f"Successfully embedded TrueType fonts into {docx_path.name}")
            return True
        except Exception as e:
            logger.error(f"Word font embedding failed for {docx_path.name}: {e}")
            raise WordUnavailable(f"Failed to embed fonts via Word: {e}") from e
        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

def convert_to_pdf(docx_path: Path, pdf_path: Path, timeout_sec: int = 90) -> bool:
    """
    Converts DOCX to PDF using Word COM ExportAsFixedFormat.
    """
    abs_docx = str(docx_path.resolve())
    abs_pdf = str(pdf_path.resolve())
    with _WORD_LOCK:
        import pythoncom
        import win32com.client as win32

        pythoncom.CoInitialize()
        word = None
        doc = None
        try:
            logger.info(f"Exporting {docx_path.name} to PDF via MS Word COM")
            word = win32.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0

            doc = word.Documents.Open(abs_docx, ReadOnly=True, AddToRecentFiles=False)
            # 17 = wdExportFormatPDF, 0 = wdExportOptimizeForPrint, 1 = wdExportCreateHeadingBookmarks
            doc.ExportAsFixedFormat(
                OutputFileName=abs_pdf,
                ExportFormat=17,
                OpenAfterExport=False,
                OptimizeFor=0,
                CreateBookmarks=1
            )
            logger.info(f"Successfully generated PDF: {pdf_path.name}")
            return True
        except Exception as e:
            logger.error(f"Word PDF export failed: {e}")
            raise WordUnavailable(f"Failed to export PDF via Word: {e}") from e
        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

to_pdf = convert_to_pdf

