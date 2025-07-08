import re
import difflib
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
from printable import filter_nonprintable
import prompts
from subprocess import run

# Configure the Gemini API
client = genai.Client()
PDF_TEXT=""

def sort_key(s: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.findall(r'\D+|\d+', s)]

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
        image_paths = sorted(images, key=sort_key)
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
        model='gemini-2.0-flash-lite',
        contents=[*[types.Part.from_bytes(data=bytes, mime_type='image/jpeg') for bytes in images]],
        config=types.GenerateContentConfig(
            system_instruction=prompts.ocr_prompt(),
            max_output_tokens=8192,
            temperature=0.2
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
    words = chunk.split(' ')
    chunk_context = ' '.join(words[:OVERLAP_SIZE])
    chunk = ' '.join(words[OVERLAP_SIZE:])
    response = await client.aio.models.generate_content(
        model='gemini-2.0-flash',
        contents=[
            types.Part.from_text(text=f"<chunk_context>\n{chunk_context}\n</chunk_context>"),
            types.Part.from_text(text=f"<chunk>\n{chunk}\n</chunk>")
        ] if i != 0 else [
            types.Part.from_text(text=f"<chunk_context>\n\n</chunk_context>"),
            types.Part.from_text(text=f"<chunk>\n{chunk_context + chunk}\n</chunk>")
        ],
        config=types.GenerateContentConfig(
            system_instruction=prompts.harmonize_prompt(),
            max_output_tokens=8192,
            temperature=0.2
        )
    )
    if response.text != None:
        return response.text
    else:
        raise Exception("Model malfunctioned cleaning chunk.")


PAGE_NUMBER = re.compile(r"\n\s*\n\s*([ivxlcdm\d]+)\s*\n\s*\n", flags=re.IGNORECASE|re.MULTILINE)

# --- ANSI Color Codes for Terminal Output ---
# This helper class can be defined at the module level.
class Colors:
    CRITICAL = '\033[91m'  # Red
    WARNING = '\033[93m'   # Yellow
    NOTE = '\033[94m'      # Blue
    SUCCESS = '\033[92m'   # Green
    RESET = '\033[0m'      # Reset to default color
    ERROR_BG = '\033[41m'  # Red background for errors

def colorize_text(text: str) -> str:
    """Helper function to apply ANSI colors to the linter's output string."""
    colorized_lines = []
    for line in text.splitlines():
        # Using .lstrip() to handle potential leading whitespace from the model
        if line.lstrip().startswith("* **CRITICAL"):
            colorized_lines.append(f"{Colors.CRITICAL}{line}{Colors.RESET}")
        elif line.lstrip().startswith("* **WARNING"):
            colorized_lines.append(f"{Colors.WARNING}{line}{Colors.RESET}")
        elif line.lstrip().startswith("* **NOTE"):
            colorized_lines.append(f"{Colors.NOTE}{line}{Colors.RESET}")
        elif "No significant issues found" in line:
            colorized_lines.append(f"{Colors.SUCCESS}{line}{Colors.RESET}")
        else:
            colorized_lines.append(line)
    return "\n".join(colorized_lines)


def run_qa_linter(input_file: str, output_file: str, final: int, extracted: int, guessed: int):
    print("\033[92m👩‍⚕️ Looking for possible problems...\033[0m")
    d = difflib.Differ()
    wdiff = str(run([
       "wdiff",
       input_file,
       output_file,
       "--no-common",
       "--ignore-case",
       "--statistics"
   ], capture_output=True).stdout).split("======================================================================")
    diff = '\n'.join(wdiff[:-1])
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[
            types.Part.from_text(text=f"<diff>\n{diff}\n</diff>")
        ],
        config=types.GenerateContentConfig(
            system_instruction=prompts.qa_prompt(wdiff[-1]),
            temperature=0.2
        )
    )
    if response.text != None:
        print(colorize_text(response.text))
    else:
        raise Exception("Model malfunctioned while doing QA.")

def harmonize_document(input_file, output_file):
    global OVERLAP_SIZE, PDF_TEXT, PAGE_NUMBER
    print("\033[92m🔬 Cleaning text...\033[0m")
    with open(input_file, 'r', encoding="utf-8") as f, open(output_file, 'w', encoding="utf-8") as f2:
        extracted_text = f.read()
        res = list(split_overlapping(extracted_text, 2000, OVERLAP_SIZE))
        print(f"\033[92m✅ Overlapped chunks:\033[0m \033[94m{len(res)}\033[0m")
        batches = list(create_batches(res, batch_size=10))
        print(f"\033[92m✅ Batches:\033[0m \033[94m{len(batches)}\033[0m")
        f2.seek(0)
        start = time.time()
        total_words = ""
        for i, batch in enumerate(batches):
            chunks = [gemini_clean_text(i*10+j, chunk) for j, chunk in enumerate(batch)]
            chunks_text = loop.run_until_complete(asyncio.gather(*chunks))
            if None in chunks_text:
                raise Exception("Could not contact model for some chunks!")
            else:
                batch_text = "".join(chunks_text)
                f2.write(batch_text)
                total_words += batch_text
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
        print("\n\n\033[92m📄 Cleaning done, wrote document to: \033[0m\033[94m" + output_file + "\033[0m")
        extracted_words = len(extracted_text.split(' '))
        guessed_words = len(PDF_TEXT.split(' '))
        print(f"\033[92m✅ Final/extracted/guessed word count: \033[0m\033[94m{len(total_words.split(' '))}/{extracted_words}/{guessed_words}\033[0m")
        run_qa_linter(extracted_text, total_words, len(total_words.split(' ')), extracted_words, guessed_words)
    
    
if __name__ == "__main__":
    image_paths = convert_pdf_to_images(sys.argv[1], sys.argv[2])
    if not os.path.exists(sys.argv[2]+".intermediate.md"):
        process_large_pdf(image_paths, sys.argv[2]+".intermediate.md")
    else:
        print("\033[93m⚠️  Reusing previous intermediate file. Delete it if you don't want that to happen.\033[0m")
    harmonize_document(sys.argv[2]+".intermediate.md", sys.argv[2]+".md")
    #os.remove(sys.argv[2]+".intermediate.md")
    #os.rmdir(sys.argv[2])
