# SPDX-License-Identifier: AGPL-3.0-or-later
import fitz  # PyMuPDF
import os

def transform_pdf_to_img(pdf_path, output_folder, dpi=1000):
    """
    Transforms each page of a PDF into an image.
    
    :param pdf_path: Path to the input PDF file.
    :param output_folder: Directory where the images will be saved.
    :param dpi: Resolution for the output images.
    :return: List of paths to the generated images.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found at: {pdf_path}")

    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
        
    # Open the PDF document
    doc = fitz.open(pdf_path)
    image_paths = []
    
    # Standard PDF resolution is 72 DPI.
    # We apply a zoom factor to achieve the desired DPI.
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    
    for page_num in range(len(doc)):
        # CARGA: Cede tempo para o sistema respirar entre páginas pesadas
        import time
        time.sleep(0.01)
        
        # Load the page
        page = doc.load_page(page_num)
        
        # Render the page to a pixmap (image)
        # alpha=False ensures the background is white instead of transparent if the PDF has none
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        # Construct the output filename
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        output_filename = f"{pdf_basename}_page_{page_num + 1}.png"
        output_path = os.path.join(output_folder, output_filename)
        
        # Save the image with retry logic for locked files
        max_retries = 3
        for attempt in range(max_retries):
            try:
                pix.save(output_path)
                # Liberação explícita de memória para evitar picos de RAM
                pix = None
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise e
        image_paths.append(output_path)
        
    doc.close()
    return image_paths

if __name__ == "__main__":
    # Quick manual check if run directly
    import sys
    if len(sys.argv) > 1:
        test_pdf = sys.argv[1]
        dest = "debug_output"
        try:
            print(f"Processing: {test_pdf}")
            results = transform_pdf_to_img(test_pdf, dest, dpi=150)
            print(f"Success! {len(results)} images created in {dest}/")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python transform_pdf_to_img.py <path_to_pdf>")
