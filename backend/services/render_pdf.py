"""
PDF rendering service.

Renders the book layouts to a print-ready PDF file.
Uses HTML/CSS rendering via WeasyPrint for flexibility.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional
from domain.models import Asset, Book, PageLayout, RenderContext, Theme


def render_book_to_pdf(
    book: Book,
    layouts: List[PageLayout],
    assets: Dict[str, Asset],
    context: RenderContext,
    output_path: str,
    media_root: str,
) -> str:
    """
    Render a book to PDF.
    
    Args:
        book: The book to render
        layouts: Computed layouts for all pages
        assets: Dict mapping asset ID to Asset
        context: Render context with theme
        output_path: Where to save the PDF
        media_root: Root path for media files
    
    Returns:
        Path to the generated PDF
    """
    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Generate HTML for the book
    html_content = render_book_to_html(
        book, layouts, assets, context, media_root, mode="pdf"
    )
    
    # Try to render with WeasyPrint
    try:
        from weasyprint import HTML, CSS
        
        # Create CSS for print
        css = _generate_print_css(context)
        
        # Render to PDF
        html_doc = HTML(string=html_content, base_url=media_root)
        css_doc = CSS(string=css)
        html_doc.write_pdf(output_path, stylesheets=[css_doc])
        
        return output_path
        
    except ImportError:
        # WeasyPrint not available, create a placeholder PDF
        return _create_placeholder_pdf(output_path, book, layouts)


def render_book_to_html(
    book: Book,
    layouts: List[PageLayout],
    assets: Dict[str, Asset],
    context: RenderContext,
    media_root: str,
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """
    Generate HTML for the entire book.
    Does not touch disk; intended for preview rendering.

    mode:
      - "pdf": keep filesystem-relative paths (resolved via base_url) for WeasyPrint
      - "web": use /media/{file_path} so the browser can load assets
    """
    return _generate_book_html(
        book, layouts, assets, context, media_root, mode, media_base_url
    )


def _generate_book_html(
    book: Book,
    layouts: List[PageLayout],
    assets: Dict[str, Asset],
    context: RenderContext,
    media_root: str,
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """Generate HTML for the entire book."""
    theme = context.theme
    width_mm = context.page_width_mm
    height_mm = context.page_height_mm
    
    pages_html = []
    for layout in layouts:
        page_html = _render_page_html(
            layout,
            assets,
            theme,
            width_mm,
            height_mm,
            media_root,
            mode,
            media_base_url,
        )
        pages_html.append(page_html)
    
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{book.title}</title>
</head>
<body>
    {''.join(pages_html)}
</body>
</html>
"""


def _render_page_html(
    layout: PageLayout,
    assets: Dict[str, Asset],
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """Render a single page to HTML."""
    bg_color = layout.background_color or theme.background_color
    
    elements_html = []
    for elem in layout.elements:
        if elem.asset_id and elem.asset_id in assets:
            asset = assets[elem.asset_id]
            # Path handling based on render mode
            normalized_path = asset.file_path.replace("\\", "/")
            if mode == "pdf":
                # Use filesystem-relative path (WeasyPrint resolves via base_url)
                img_path = normalized_path
            else:
                base = media_base_url.rstrip("/") if media_base_url else "/media"
                img_path = f"{base}/{normalized_path}"
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    overflow: hidden;
                ">
                    <img src="{img_path}" style="
                        width: 100%;
                        height: 100%;
                        object-fit: cover;
                    " />
                </div>
            """)
        elif elem.text:
            # Text element
            color = elem.color or theme.primary_color
            font_size = elem.font_size or 12
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    color: {color};
                    font-size: {font_size}pt;
                    font-family: {theme.title_font_family if font_size > 14 else theme.font_family};
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                ">
                    {elem.text}
                </div>
            """)
        elif elem.color:
            # Colored rectangle (overlay)
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    background: {elem.color};
                "></div>
            """)
    
    return f"""
        <div class="page" style="
            width: {width_mm}mm;
            height: {height_mm}mm;
            background: {bg_color};
            position: relative;
            page-break-after: always;
            overflow: hidden;
        ">
            {''.join(elements_html)}
        </div>
    """


def _generate_print_css(context: RenderContext) -> str:
    """Generate CSS for print output."""
    return f"""
        @page {{
            size: {context.page_width_mm}mm {context.page_height_mm}mm;
            margin: 0;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            margin: 0;
            padding: 0;
        }}
        
        .page {{
            overflow: hidden;
        }}
        
        .page:last-child {{
            page-break-after: avoid;
        }}
    """


def _create_placeholder_pdf(output_path: str, book: Book, layouts: List[PageLayout]) -> str:
    """
    Create a simple placeholder PDF when WeasyPrint is not available.
    Uses reportlab as a fallback, or creates an empty file.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        
        c = canvas.Canvas(output_path, pagesize=letter)
        
        for i, layout in enumerate(layouts):
            if i > 0:
                c.showPage()
            
            c.setFont("Helvetica", 16)
            c.drawString(72, 720, f"{book.title}")
            c.setFont("Helvetica", 12)
            c.drawString(72, 700, f"Page {i + 1} of {len(layouts)}")
            c.drawString(72, 680, f"Type: {layout.page_type.value}")
            
            if layout.elements:
                c.drawString(72, 660, f"Elements: {len(layout.elements)}")
        
        c.save()
        return output_path
        
    except ImportError:
        # No PDF library available, create empty file with info
        with open(output_path, 'w') as f:
            f.write(f"PDF generation requires WeasyPrint or reportlab.\n")
            f.write(f"Book: {book.title}\n")
            f.write(f"Pages: {len(layouts)}\n")
        return output_path
