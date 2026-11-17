import io
import os
import re
import csv
import base64
import json
import logging
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Supported Extensions Mapping
FILE_TYPE_MAPPINGS = {
    'pdf': ['pdf'],
    'image': ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff', 'svg'],
    'word': ['docx', 'doc'],
    'powerpoint': ['pptx', 'ppt'],
    'excel': ['xlsx', 'xls', 'csv'],
    'text': ['txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'sql', 'sh', 'bash', 'env', 'xml', 'toml', 'ini']
}


class DocumentProcessor:
    """
    Universal document and media extractor for DevDialogue AI.
    Handles PDF, Images (with OCR and Multimodal Vision), Word documents,
    PowerPoint presentations, Excel spreadsheets/CSVs, and plain text/code files.
    """

    @classmethod
    def detect_file_type(cls, filename: str, content_type: str = '') -> str:
        """Detect file type category from filename extension and MIME type."""
        ext = os.path.splitext(filename)[1].lower().lstrip('.')
        
        for category, extensions in FILE_TYPE_MAPPINGS.items():
            if ext in extensions:
                return category

        if content_type:
            ct = content_type.lower()
            if 'pdf' in ct:
                return 'pdf'
            elif 'image' in ct:
                return 'image'
            elif 'word' in ct or 'document' in ct:
                return 'word'
            elif 'presentation' in ct or 'powerpoint' in ct:
                return 'powerpoint'
            elif 'sheet' in ct or 'excel' in ct or 'csv' in ct:
                return 'excel'
            elif 'text' in ct or 'json' in ct:
                return 'text'

        return 'other'

    @classmethod
    def extract_content(cls, file_bytes: bytes, filename: str, content_type: str = '', user = None) -> Tuple[str, str, Dict[str, Any]]:
        """
        Extracts structured text and metadata from any supported document or media file.
        Returns: (extracted_text, file_type, metadata_dict)
        """
        file_type = cls.detect_file_type(filename, content_type)
        metadata: Dict[str, Any] = {
            'filename': filename,
            'file_type': file_type,
            'file_size': len(file_bytes),
        }

        try:
            if file_type == 'pdf':
                text, meta = cls._extract_pdf(file_bytes, filename, user=user)
            elif file_type == 'image':
                text, meta = cls._extract_image(file_bytes, filename, user=user)
            elif file_type == 'word':
                text, meta = cls._extract_word(file_bytes, filename)
            elif file_type == 'powerpoint':
                text, meta = cls._extract_powerpoint(file_bytes, filename)
            elif file_type == 'excel':
                text, meta = cls._extract_excel(file_bytes, filename)
            elif file_type == 'text':
                text, meta = cls._extract_text(file_bytes, filename)
            else:
                text, meta = cls._extract_fallback(file_bytes, filename)
            
            metadata.update(meta)
            return text.strip(), file_type, metadata

        except Exception as e:
            logger.warning(f"Error extracting content from {filename}: {e}", exc_info=True)
            fallback_text = f"[Attached Document: {filename} ({file_type.upper()})]\n*(Note: Could not fully parse file structure: {str(e)})*"
            metadata['error'] = str(e)
            return fallback_text, file_type, metadata

    @classmethod
    def _extract_pdf(cls, file_bytes: bytes, filename: str, user = None) -> Tuple[str, Dict[str, Any]]:
        """Extract text and embedded scanned page images from PDF using pypdf."""
        import pypdf
        
        pdf_file = io.BytesIO(file_bytes)
        reader = pypdf.PdfReader(pdf_file)
        num_pages = len(reader.pages)
        
        pages_text = []
        total_chars = 0
        embedded_images_count = 0
        scanned_page_ocr_count = 0

        for page_idx, page in enumerate(reader.pages):
            page_num = page_idx + 1
            extracted = page.extract_text() or ""
            extracted_clean = extracted.strip()
            total_chars += len(extracted_clean)

            # If page text is very sparse (< 40 chars), check if it's a scanned page with embedded images
            ocr_text = ""
            if len(extracted_clean) < 40 and hasattr(page, 'images'):
                try:
                    for img_name, img_file in page.images.items():
                        embedded_images_count += 1
                        img_data = img_file.data
                        img_ocr, _ = cls._extract_image(img_data, f"{filename}_page_{page_num}_{img_name}", user=user)
                        if img_ocr and not img_ocr.startswith("[Image:"):
                            ocr_text += f"\n[OCR Text from Embedded Image]:\n{img_ocr}\n"
                            scanned_page_ocr_count += 1
                except Exception as img_err:
                    logger.debug(f"Could not extract images from PDF page {page_num}: {img_err}")

            page_body = extracted_clean
            if ocr_text:
                page_body = f"{page_body}\n{ocr_text}".strip()

            if page_body:
                pages_text.append(f"--- Page {page_num} ---\n{page_body}")
            else:
                pages_text.append(f"--- Page {page_num} ---\n*(Blank or non-text page)*")

        body = "\n\n".join(pages_text)
        result_text = f"### PDF Document: {filename} ({num_pages} page{'s' if num_pages != 1 else ''})\n\n{body}"
        
        meta = {
            'pages': num_pages,
            'total_characters': total_chars,
            'scanned_pages_ocred': scanned_page_ocr_count,
            'embedded_images_found': embedded_images_count,
        }
        return result_text, meta

    @classmethod
    def _extract_word(cls, file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text, headings, and tables from Word (.docx / .doc) documents."""
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.doc':
            # Fallback for legacy .doc binary format
            return cls._extract_fallback(file_bytes, filename)

        import docx

        doc_io = io.BytesIO(file_bytes)
        doc = docx.Document(doc_io)
        
        content_parts = []
        heading_count = 0
        paragraph_count = 0
        table_count = 0

        # Extract paragraphs with heading levels
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            
            style_name = p.style.name if p.style else ''
            if style_name.startswith('Heading 1'):
                content_parts.append(f"\n# {text}")
                heading_count += 1
            elif style_name.startswith('Heading 2'):
                content_parts.append(f"\n## {text}")
                heading_count += 1
            elif style_name.startswith('Heading 3'):
                content_parts.append(f"\n### {text}")
                heading_count += 1
            elif 'List' in style_name:
                content_parts.append(f"- {text}")
                paragraph_count += 1
            else:
                content_parts.append(text)
                paragraph_count += 1

        # Extract tables as formatted Markdown tables
        for table in doc.tables:
            table_count += 1
            rows_data = []
            for row in table.rows:
                row_vals = [cell.text.strip().replace('\n', ' ') for cell in row.cells]
                rows_data.append(row_vals)

            if rows_data:
                md_table = cls._format_markdown_table(rows_data, title=f"Table {table_count}")
                content_parts.append(f"\n{md_table}\n")

        body = "\n\n".join(content_parts)
        result_text = f"### Word Document: {filename}\n\n{body}"
        meta = {
            'paragraphs': paragraph_count,
            'headings': heading_count,
            'tables': table_count,
        }
        return result_text, meta

    @classmethod
    def _extract_powerpoint(cls, file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any]]:
        """Extract slides, titles, bullet points, tables, and speaker notes from PowerPoint (.pptx)."""
        import pptx

        prs_io = io.BytesIO(file_bytes)
        prs = pptx.Presentation(prs_io)
        num_slides = len(prs.slides)
        
        slides_text = []

        for idx, slide in enumerate(prs.slides):
            slide_num = idx + 1
            slide_parts = []
            
            # 1. Slide Title
            slide_title = ""
            if slide.shapes.title and slide.shapes.title.text:
                slide_title = slide.shapes.title.text.strip()
                slide_parts.append(f"**Title**: {slide_title}")

            # 2. Text in shapes / textframes
            bullets = []
            for shape in slide.shapes:
                if shape == slide.shapes.title:
                    continue
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if text:
                            bullets.append(f"- {text}")
                elif shape.has_table:
                    # Slide table
                    table_rows = []
                    for row in shape.table.rows:
                        table_rows.append([cell.text.strip().replace('\n', ' ') for cell in row.cells])
                    if table_rows:
                        slide_parts.append(cls._format_markdown_table(table_rows))

            if bullets:
                slide_parts.extend(bullets)

            # 3. Speaker notes (essential for requirement specifications!)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    slide_parts.append(f"> **Speaker Notes**: {notes_text}")

            content = "\n".join(slide_parts) if slide_parts else "*(Visual slide with no text)*"
            slides_text.append(f"--- Slide {slide_num}{f': {slide_title}' if slide_title else ''} ---\n{content}")

        body = "\n\n".join(slides_text)
        result_text = f"### PowerPoint Presentation: {filename} ({num_slides} slide{'s' if num_slides != 1 else ''})\n\n{body}"
        meta = {
            'slides': num_slides,
        }
        return result_text, meta

    @classmethod
    def _extract_excel(cls, file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any]]:
        """Extract worksheets, schemas, and tabular rows from Excel (.xlsx) and CSV files."""
        ext = os.path.splitext(filename)[1].lower()
        
        if ext == '.csv':
            return cls._extract_csv(file_bytes, filename)

        import openpyxl

        excel_io = io.BytesIO(file_bytes)
        wb = openpyxl.load_workbook(excel_io, data_only=True)
        sheet_names = wb.sheetnames
        
        sheets_content = []
        total_rows_extracted = 0

        for sheet_name in sheet_names:
            ws = wb[sheet_name]
            all_rows = list(ws.iter_rows(values_only=True))
            if not all_rows:
                sheets_content.append(f"#### Sheet: `{sheet_name}` *(Empty)*")
                continue

            # Filter completely empty rows
            non_empty_rows = [[str(cell).strip() if cell is not None else "" for cell in r] for r in all_rows if any(c is not None and str(c).strip() for c in r)]
            if not non_empty_rows:
                sheets_content.append(f"#### Sheet: `{sheet_name}` *(Empty)*")
                continue

            row_count = len(non_empty_rows)
            col_count = len(non_empty_rows[0]) if non_empty_rows else 0
            total_rows_extracted += row_count

            # Cap large datasets to 50 sample rows + schema notice
            max_preview = 50
            preview_rows = non_empty_rows[:max_preview]
            table_md = cls._format_markdown_table(preview_rows)
            
            notice = f" *(Showing first {max_preview} of {row_count} rows)*" if row_count > max_preview else ""
            sheets_content.append(f"#### Sheet: `{sheet_name}` ({col_count} columns, {row_count} rows){notice}\n\n{table_md}")

        body = "\n\n".join(sheets_content)
        result_text = f"### Excel Spreadsheet: {filename} (Sheets: {', '.join(sheet_names)})\n\n{body}"
        meta = {
            'sheets': sheet_names,
            'total_rows': total_rows_extracted,
        }
        return result_text, meta

    @classmethod
    def _extract_csv(cls, file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any]]:
        """Extract CSV spreadsheet table data."""
        try:
            text_data = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            text_data = file_bytes.decode('latin-1', errors='ignore')

        reader = csv.reader(io.StringIO(text_data))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        
        row_count = len(rows)
        col_count = len(rows[0]) if rows else 0
        
        preview_rows = rows[:50]
        table_md = cls._format_markdown_table(preview_rows)
        notice = f" *(Showing first 50 of {row_count} rows)*" if row_count > 50 else ""

        result_text = f"### CSV Spreadsheet: {filename} ({col_count} columns, {row_count} rows){notice}\n\n{table_md}"
        meta = {
            'total_rows': row_count,
            'columns': col_count,
        }
        return result_text, meta

    @classmethod
    def _extract_image(cls, file_bytes: bytes, filename: str, user = None) -> Tuple[str, Dict[str, Any]]:
        """
        Extract text from images using OCR (pytesseract) or Multimodal Vision API (Gemini/OpenAI).
        Works for UI mockups, architectural diagrams, ERDs, whiteboard photos, and screenshots.
        """
        from PIL import Image

        img_io = io.BytesIO(file_bytes)
        img = Image.open(img_io)
        width, height = img.size
        img_format = img.format or os.path.splitext(filename)[1].upper().lstrip('.')
        size_kb = len(file_bytes) // 1024

        meta = {
            'dimensions': f"{width}x{height}",
            'format': img_format,
            'mode': img.mode,
            'size_kb': size_kb,
        }

        extracted_ocr_text = ""
        ocr_engine_used = None

        # 1. Attempt OCR with pytesseract if tesseract is available
        try:
            import pytesseract
            raw_text = pytesseract.image_to_string(img).strip()
            if raw_text and len(raw_text) > 5:
                extracted_ocr_text = raw_text
                ocr_engine_used = 'tesseract'
        except Exception as ocr_err:
            logger.debug(f"Pytesseract not available or failed: {ocr_err}")

        # 2. Attempt Multimodal Vision extraction via Gemini if configured
        if not extracted_ocr_text and user:
            try:
                gemini_text = cls._call_multimodal_vision(file_bytes, filename, img_format, user=user)
                if gemini_text:
                    extracted_ocr_text = gemini_text
                    ocr_engine_used = 'gemini_vision'
            except Exception as vision_err:
                logger.debug(f"Vision API extraction failed: {vision_err}")

        # 3. Assemble response
        if extracted_ocr_text:
            meta['ocr_engine'] = ocr_engine_used
            meta['has_ocr_text'] = True
            result_text = (
                f"### Image Document: {filename} ({width}x{height} {img_format}, {size_kb} KB)\n"
                f"**Extracted Text & Visual Blueprint (OCR/Vision)**:\n\n"
                f"{extracted_ocr_text}"
            )
        else:
            meta['has_ocr_text'] = False
            result_text = (
                f"### Image Document: {filename} ({width}x{height} {img_format}, {size_kb} KB)\n"
                f"*(Visual diagram/mockup attached. Dimensions: {width}x{height}px)*"
            )

        return result_text, meta

    @classmethod
    def _call_multimodal_vision(cls, file_bytes: bytes, filename: str, img_format: str, user = None) -> Optional[str]:
        """Call Gemini Multimodal Vision API to extract text & architectural components from images."""
        if not user:
            return None

        # Check API key from user profile or settings
        api_key = None
        if hasattr(user, 'profile') and user.profile.gemini_key:
            api_key = user.profile.gemini_key
        if not api_key:
            api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return None

        import urllib.request
        mime_map = {
            'PNG': 'image/png',
            'JPG': 'image/jpeg',
            'JPEG': 'image/jpeg',
            'WEBP': 'image/webp',
            'GIF': 'image/gif',
        }
        mime_type = mime_map.get(img_format.upper(), 'image/png')
        b64_data = base64.b64encode(file_bytes).decode('utf-8')

        prompt = (
            "Analyze this software architecture diagram, UI mockup, or document image in detail. "
            "Extract all text, labels, entities, relations, database fields, UI elements, and API specifications. "
            "Provide the extracted details in clear, structured Markdown."
        )

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {"inlineData": {"mimeType": mime_type, "data": b64_data}},
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.2}
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            candidates = data.get('candidates', [])
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                return "".join(p.get('text', '') for p in parts).strip()
        return None

    @classmethod
    def _extract_text(cls, file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text from code, markdown, or plain text files."""
        for enc in ['utf-8', 'latin-1', 'utf-16']:
            try:
                decoded = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = file_bytes.decode('utf-8', errors='ignore')

        lines = decoded.splitlines()
        ext = os.path.splitext(filename)[1].lower().lstrip('.')
        code_langs = {'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'sql', 'sh', 'json', 'yaml', 'yml', 'xml'}
        
        if ext in code_langs:
            body = f"```{ext}\n{decoded}\n```"
        else:
            body = decoded

        result_text = f"### File: {filename} ({len(lines)} lines)\n\n{body}"
        meta = {
            'lines': len(lines),
            'characters': len(decoded),
        }
        return result_text, meta

    @classmethod
    def _extract_fallback(cls, file_bytes: bytes, filename: str) -> Tuple[str, Dict[str, Any]]:
        """Extract printable ASCII/UTF-8 strings from binary/unknown files."""
        # Extract sequences of 4+ printable characters
        printable = re.findall(b'[\x20-\x7E\r\n\t]{4,}', file_bytes)
        strings = [p.decode('ascii', errors='ignore').strip() for p in printable[:200] if len(p.strip()) > 3]
        
        if strings:
            body = "\n".join(strings[:100])
            result_text = f"### File: {filename} (Extracted Text Strings)\n\n{body}"
        else:
            result_text = f"### File: {filename}\n*(Binary file attached - {len(file_bytes)} bytes)*"

        meta = {
            'strings_extracted': len(strings),
        }
        return result_text, meta

    @classmethod
    def _format_markdown_table(cls, rows: list, title: str = "") -> str:
        """Formats 2D array of rows into a GitHub Flavored Markdown table."""
        if not rows:
            return ""

        # Normalize column counts
        max_cols = max(len(r) for r in rows)
        if max_cols == 0:
            return ""

        padded_rows = []
        for r in rows:
            padded_rows.append(list(r) + [""] * (max_cols - len(r)))

        header = padded_rows[0]
        # Clean pipes from cells
        header = [str(c).replace('|', '\\|').strip() or f"Col_{i+1}" for i, c in enumerate(header)]
        separator = ["---"] * max_cols

        table_lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |"
        ]

        for row in padded_rows[1:]:
            cleaned_row = [str(c).replace('|', '\\|').strip() for c in row]
            table_lines.append("| " + " | ".join(cleaned_row) + " |")

        table_str = "\n".join(table_lines)
        if title:
            return f"**{title}**:\n{table_str}"
        return table_str

