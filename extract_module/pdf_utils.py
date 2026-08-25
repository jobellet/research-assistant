import fitz  # PyMuPDF
import logging

logger = logging.getLogger(__name__)

import base64

def extract_first_page_as_image(pdf_path: str) -> str:
    """
    Extract the first page of a PDF as a base64 encoded PNG.
    """
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0: return None
        page = doc.load_page(0)
        # Use low-res (72 DPI) to save bandwidth/tokens
        pix = page.get_pixmap(alpha=False)
        img_data = pix.tobytes("png")
        doc.close()
        return base64.b64encode(img_data).decode("utf-8")
    except Exception as e:
        logger.error(f"Error converting PDF to image: {e}")
        return None

def extract_text_from_pdf(pdf_path: str, max_pages: int = None) -> str:
    """
    Extract text from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file.
        max_pages: Maximum number of pages to extract. If None, extract all pages.
        
    Returns:
        Extracted text as a string.
    """
    text = ""
    try:
        doc = fitz.open(pdf_path)
        pages_to_read = len(doc)
        if max_pages is not None:
            pages_to_read = min(max_pages, len(doc))
            
        for i in range(pages_to_read):
            page = doc.load_page(i)
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path}: {e}")
        return ""

if __name__ == "__main__":
    # Quick standalone test
    import sys
    if len(sys.argv) > 1:
        extracted = extract_text_from_pdf(sys.argv[1])
        print(extracted)
