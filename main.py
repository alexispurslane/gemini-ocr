import re
import glob
import asyncio
import os
import time
import sys
from google import genai
from google.genai import types
import pdf2image
from PIL import Image
import io
from split import split_overlapping
import pypdf

# Configure the Gemini API
client = genai.Client()
PDF_TEXT=""

def convert_pdf_to_images(pdf_path, output_folder, dpi=150):
    global PDF_TEXT
    # Create output directory if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"\033[92m📁 Created output directory: {output_folder}\033[0m")

    # Convert PDF pages to images
    print(f"\033[94m⏳ Converting PDF to images... This may take a moment.\033[0m")
    
    file = pypdf.PdfReader(pdf_path)
    PDF_TEXT = "".join([page.extract_text() for page in file.pages])
    image_paths = []
    
    page_count = len(file.pages)
    images = glob.glob(f'{output_folder}/*.jpg')
    image_count = len(images)
        
    if page_count == image_count:
        print("\033[93m⚠️  Reusing previous extracted images. Delete the output folder if you don't want that to happen.\033[0m")
        image_paths = images
    else:
        images = pdf2image.convert_from_path(pdf_path, dpi=dpi, thread_count=8)

        # Save images to the output folder
        image_paths = []
        for i, image in enumerate(images):
            image_path = os.path.join(output_folder, f'page_{i+1}.jpg')
            image.save(image_path, 'JPEG')
            sys.stdout.write("\033[K")
            print(f"\033[92m✅ Page {i+1} saved as {image_path}\033[0m", end='\r')
            image_paths.append(image_path)

            print(f"\n\033[92m✨ Conversion completed. Total images: {len(images)}\033[0m")
            
    return image_paths

def create_batches(elements, batch_size=50):
    """Group images into batches for processing"""
    for i in range(0, len(elements), batch_size):
        yield elements[i:i + batch_size]

def image_path_to_bytes(path: str):
    pil_im = Image.open(path)
    b = io.BytesIO()
    pil_im.save(b, 'jpeg')
    return b.getvalue()

async def ocr_with_gemini(image_paths, instruction):
    """Process images with Gemini 2.0 Flash for OCR"""
    images = [image_path_to_bytes(path) for path in image_paths]

    response = await client.aio.models.generate_content(
        model='gemini-2.0-flash',
        contents=[*[types.Part.from_bytes(data=bytes, mime_type='image/jpeg') for bytes in images]],
        config=types.GenerateContentConfig(
            system_instruction=f"""These are pages from a PDF document. Extract all text content (**ignoring headers at the top of the page and footers at the bottom**) while preserving the structure, but make sure things are clean and nice as well.

## Rules for Preserving Structure

For text:
1. Remove chapter or book titles and page numbers in the middle of the text. So for example,

> ...pellicule as 'skin'. 148 Libidinal Economy
> 
> And adjoining the skin of the fingertips, scraped by the nails, perhaps there should be huge silken...

must become:

> ...pellicule as 'skin'.
> 
> And adjoining the skin of the fingertips, scraped by the nails, perhaps there should be huge silken...            

2. Make sure each bibliography entry is separated by two line breaks.
3. Do not use any markdown formatting except bold and italic.

For multi-column layouts:
1. Process columns from left to right
2. Clearly separate content from different columns

## Final Warning

Make sure to preserve ALL core content text! Do not change any words of that text. DO NOT USE CODE FENCES.
""",
max_output_tokens=8192
        )
    )
    return response.text

loop = asyncio.get_event_loop()

REGEX = re.compile(r"(.)- (.)")
def process_large_pdf(image_paths, output_file):
    # Create batches of images (e.g., by chapter or section)
    batches = list(create_batches(image_paths, 3))
    
    print("\033[94m🌀 Extracting text...\033[0m")
    
    with open(output_file, 'w', encoding="utf-8") as f:
        start = time.time()
        print(f"\033[92m✅ Batches: \033[0m\033[94m{len(batches)}\033[0m")
        for i, batch in enumerate(batches):
            batch_text = [ocr_with_gemini([image], "Extract all text, maintaining document structure") for image in batch]
            batch_text = loop.run_until_complete(asyncio.gather(*batch_text))
            if batch_text != None:
                if None in batch_text:
                    print("batch failed!")
                    return
                else:
                    fulltext = "".join(batch_text)
                    fulltext = REGEX.sub(r"\1\2", fulltext.replace("\n\n", "\0").replace("\n", " ").replace("\0", "\n\n"))
                    
                    f.write(fulltext)
                    if len(batches) > 1:
                        avg_time = (time.time() - start) / (i+1)
                        batches_left = (len(batches) - (i+1))
                        seconds = int(avg_time*batches_left)
                        minutes=int((seconds/60)%60)
                        hours=int((minutes/60)%24)
                        sys.stdout.write("\033[K")
                        print(f"\033[92m>>> 📈 Progress: {round((i+1)/len(batches)*100, 2)}%   🕐 Average batch time: {int(avg_time)}s   ⏳ Estimated time: {hours}h:{minutes}m:{seconds%60}s <<<\033[0m", end='\r')
                    f.flush()
    print("\n")

OVERLAP_SIZE = 1000
    
async def gemini_clean_text(i: int, chunk: str):
    global OVERLAP_SIZE
    response = await client.aio.models.generate_content(
        model='gemini-2.0-flash',
        contents=[types.Part.from_text(text=chunk)],
        config=types.GenerateContentConfig(
            system_instruction="""
The following chunk of text is part of a larger text that was extracted from a large PDF document in batches.

Harmonize the content by:
1. Ensure consistent Markdown formatting throughout
2. Fix any table structure issues at batch boundaries
3. Make sure that sentences, paragraphs, or words flow correctly and nicely.
4. Remove any unwanted unicode characters or similar garabage.
5. Preserve all punctuation.
6. Find text that is likely to be a heading based on its size or content, and convert it to **consistent levels** of markdown heading. Nest these to create a nicely structured document.
7. Make sure the text is broken properly into paragraphs.

OUTPUT NOTHING EXCEPT THE NEW TEXT.
""",
max_output_tokens=8192
        )
    )
    if response.text != None:
        return ' '.join(response.text.split(' ')[OVERLAP_SIZE:]) if i != 0 else response.text
    else:
        raise Exception("Model malfunctioned cleaning chunk.")

def harmonize_document(input_file, output_file):
    global OVERLAP_SIZE, PDF_TEXT
    print("\033[92m🔬 Cleaning text...\033[0m")
    with open(input_file, 'r', encoding="utf-8") as f, open(output_file, 'w', encoding="utf-8") as f2:
        extracted_text = f.read()
        res = list(split_overlapping(extracted_text, 2000, OVERLAP_SIZE))
        print(f"\033[92m✅ Overlapped chunks:\033[0m \033[94m{len(res)}\033[0m")
        batches = list(create_batches(res, batch_size=10))
        print(f"\033[92m✅ Batches:\033[0m \033[94m{len(batches)}\033[0m")
        f2.seek(0)
        start = time.time()
        total_words = 0
        for i, batch in enumerate(batches):
            chunks = [gemini_clean_text(i*10+j, chunk) for j, chunk in enumerate(batch)]
            chunks_text = loop.run_until_complete(asyncio.gather(*chunks))
            if None in chunks_text:
                raise Exception("Could not contact model for some chunks!")
            else:
                batch_text = "".join(chunks_text)
                f2.write(batch_text)
                total_words += len(batch_text.split(' '))
                if len(batches) > 1:
                    avg_time = (time.time() - start) / (i+1)
                    batches_left = (len(batches) - (i+1))
                    seconds = int(avg_time*batches_left)
                    minutes=int((seconds/60)%60)
                    hours=int((minutes/60)%24)
                    sys.stdout.write("\033[K")
                    print(f"\033[92m>>> 📈 Progress: {round((i+1)/len(batches)*100, 2)}%   🕐 Average batch time: {int(avg_time)}s   ⏳ Estimated time: {hours}h:{minutes}m:{seconds%60}s <<<\033[0m", end='\r')
                f2.flush()
        f2.truncate()
        print(f"\n\n\033[92m✅ Final/extracted/guessed word count: \033[0m\033[94m{total_words}/{len(extracted_text.split(' '))}/{len(PDF_TEXT.split(' '))}\033[0m")
    print("\033[92m📄 Cleaning done, wrote document to: \033[0m\033[94m" + output_file + "\033[0m")
                
if __name__ == "__main__":
    image_paths = convert_pdf_to_images(sys.argv[1], sys.argv[2])
    if not os.path.exists(sys.argv[2]+".intermediate.md"):
        process_large_pdf(image_paths, sys.argv[2]+".intermediate.md")
    else:
        print("\033[93m⚠️  Reusing previous intermediate file. Delete it if you don't want that to happen.\033[0m")
    harmonize_document(sys.argv[2]+".intermediate.md", sys.argv[2]+".md")
    #os.remove(sys.argv[2]+".intermediate.md")
    #os.rmdir(sys.argv[2])
