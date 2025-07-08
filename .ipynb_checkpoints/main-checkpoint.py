import os
from google import genai
from google.genai import types
from pdf2image import convert_from_path
from PIL import Image
import io

# Configure the Gemini API
client = genai.Client(api_key= os.getenv('GOOGLE_API_KEY'))

def convert_pdf_to_images(pdf_path, output_folder, dpi=300):
    # Create output directory if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    # Convert PDF pages to images
    images = convert_from_path(pdf_path, dpi=dpi)
    
    # Save images to the output folder
    image_paths = []
    for i, image in enumerate(images):
        image_path = os.path.join(output_folder, f'page_{i+1}.jpg')
        image.save(image_path, 'JPEG')
        image_paths.append(image_path)
    
    return image_paths

def batch_images(image_paths, batch_size=50):
    """Group images into batches for processing"""
    for i in range(0, len(image_paths), batch_size):
        yield image_paths[i:i + batch_size]

def image_path_to_bytes(path: str):
    pil_im = Image.open(path)
    b = io.BytesIO()
    pil_im.save(b, 'jpeg')
    return b.getvalue()

def ocr_with_gemini(image_paths, instruction):
    """Process images with Gemini 2.0 Flash for OCR"""
    images = [image_path_to_bytes(path) for path in image_paths]
    
    prompt = f"""
    {instruction}
    
    These are pages from a PDF document. Extract all text content while preserving the structure.
    Pay special attention to tables, columns, headers, and any structured content.
    Maintain paragraph breaks and formatting.
    """
    
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[types.Part.from_text(text=instruction), *[types.Part.from_bytes(data=bytes, mime_type='image/jpeg') for bytes in images]],
        config=types.GenerateContentConfig(
            system_instruction=f"""These are pages from a PDF document. Extract all core text content while preserving the structure, but make sure things are clean and nice as well.

## Rules for Preserving Structure

For tables:
1. Maintain the table structure using markdown table format
2. Preserve all column headers and row labels
3. Ensure numerical data is accurately captured
    
For multi-column layouts:
1. Process columns from left to right
2. Clearly separate content from different columns
    
For charts and graphs:
1. Describe the chart type
2. Extract any visible axis labels, legends, and data points
3. Extract any title or caption
    
Preserve all headers, footers, page numbers, and footnotes.

## Rules for Cleaning Up

1. PDFs often have chapter or book titles in the header of each page. Remove these.
2. PDFs often have page numbers in the header or footer of each page. Remove these.
3. Make sure that sentences or paragraphs that were broken up by page breaks are unified again.
4. Remove any unwanted unicode characters or similar garabage.

## Final Warning

Make sure to preserve ALL core content text! Do not change any words of that text.
""",
max_output_tokens=8192
        )
    )
    return response.text

def process_large_pdf(pdf_path, output_folder, output_file):
    # Convert PDF to images
    image_paths = convert_pdf_to_images(pdf_path, output_folder)
    
    # Create batches of images (e.g., by chapter or section)
    batches = batch_images(image_paths, 1)
    
    full_text = ""
    for i, batch in enumerate(batches):
        print(f"Processing batch {i+1}...")
        batch_text = ocr_with_gemini(batch, "Extract all text, maintaining document structure")
        full_text += f"\n\n--- BATCH {i+1} ---\n\n{batch_text}"
    
    # Save the full extracted text
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(full_text)
    
    return full_text

def harmonize_document(extracted_text):
    prompt = """
    The following text was extracted from a large PDF document in batches.
    Harmonize the content by:
    1. Removing any batch separation markers
    2. Ensuring consistent formatting throughout
    3. Fixing any table structure issues at batch boundaries
    4. Ensuring paragraph and section flow is natural across batch boundaries
    
    Original extracted text:
    """
    
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[types.Part.from_text(text=prompt), types.Part.from_text(text=extracted_text)]
    )
    return response.text

