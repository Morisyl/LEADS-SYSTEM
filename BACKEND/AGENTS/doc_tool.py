import cv2
import pytesseract
import numpy as np
from pdf2image import convert_from_path
from typing import Dict


pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
class DocTool:
    def __init__(self):
        # Configuration for Tesseract if needed
        pass

    def file_to_text_dict(self, file_path: str) -> Dict[int, str]:
        """
        Converts file to text, adds page markers, and chunks into 
        groups of 5 pages.
        """
        raw_pages = []
        
        # 1. Convert File to List of Text Strings
        if file_path.lower().endswith('.pdf'):
            pages = convert_from_path(file_path)
            for i, page in enumerate(pages):
                img = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
                text = pytesseract.image_to_string(img)
                raw_pages.append(f"{text}\npage [{i+1}].................\n")
        else:
            img = cv2.imread(file_path)
            text = pytesseract.image_to_string(img)
            raw_pages.append(f"{text}\npage [1].................\n")

        # 2. Package into Dictionary (Chunks of 5)
        chunked_doc = {}
        for i in range(0, len(raw_pages), 5):
            start_page = i + 1
            # Join up to 5 pages into a single string
            content = "".join(raw_pages[i : i + 5])
            chunked_doc[start_page] = content

        return chunked_doc