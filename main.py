import json
import datetime
import time
import sys
from contextlib import suppress
import signal
import re
import argparse
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
import shutil

PROJECT_ID = os.environ['GOCR_PROJECT_ID']
LOCATION_ID = os.environ.get('GOCR_LOCATION_ID')

# Configure the Gemini API
client = genai.Client(
    project=PROJECT_ID,
    location=LOCATION_ID or 'us-central1'
)
PDF_TEXT=""

print("Checking dependencies exist...")
if shutil.which('wdiff') is None:
    print("wdiff not found. Please install it:")
    if sys.platform == 'win32':
        print("Windows: Install using Chocolatey with 'choco install wdiff' or download from https://www.di-mgt.com.au/wdiff-for-windows.html")
    elif sys.platform == 'darwin':
        print("Mac: Install using Homebrew with 'brew install wdiff'")
    else:
        print("Linux: Use your package manager, e.g., 'sudo apt-get install wdiff' (Debian/Ubuntu) or 'sudo dnf install wdiff' (Red Hat), or use Linuxbrew with 'brew install wdiff'")

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

BATCH_JOB = None

def parse_json(s):
    res = None
    with suppress(json.JSONDecodeError):
        res = json.loads(s)
    return res

REGEX = re.compile(r"(.)- (.)")

def run_batch(requests_file, output_folder, output_file):
    uploaded_file = client.files.upload(
        file=requests_file,
        config=types.UploadFileConfig(display_name=requests_file,
                                      mime_type='jsonl')
    )

    if uploaded_file != None:
        BATCH_JOB = client.batches.create(
            model="gemini-2.0-flash",
            src=uploaded_file.name,
            config={
                'display_name': output_folder+"batch-1",
            }
        )

        completed_states = set([
            'JOB_STATE_SUCCEEDED',
            'JOB_STATE_FAILED',
            'JOB_STATE_CANCELLED',
        ])
        print(f"\033[32m✨ Waiting for job \033[33m{BATCH_JOB.name}\033[32m to complete...\033[0m")
        BATCH_JOB = client.batches.get(name=BATCH_JOB.name)
        spinner_chars = ['-', '\\', '|', '/']
        spinner_index = 0
        start_time = datetime.datetime.now()
        elapsed_time = 0
        elapsed_time_str = ""

        while BATCH_JOB.state.name not in completed_states:
            sys.stdout.write("\033[K")  # Clear the line
            elapsed_time = datetime.datetime.now() - start_time
            elapsed_time_str = str(elapsed_time).split('.')[0]

            if BATCH_JOB.state.name == "JOB_STATE_PENDING":
                print(f"Pending {spinner_chars[spinner_index]} Elapsed: {elapsed_time_str}", end="\r")
                spinner_index = (spinner_index + 1) % len(spinner_chars)
            else:
                print(f"Current state: {BATCH_JOB.state.name} Elapsed: {elapsed_time_str}", end="\r")

            time.sleep(1)
            BATCH_JOB = client.batches.get(name=BATCH_JOB.name)

        if BATCH_JOB.state.name == 'JOB_STATE_FAILED':
            print(f"\033[31m❌ Error: Batch job failed.\033[0m Check logs for details.")
        elif BATCH_JOB.state.name == 'JOB_STATE_SUCCEEDED':
            if BATCH_JOB.dest and BATCH_JOB.dest.file_name:
                result_file_name = BATCH_JOB.dest.file_name

                print(f"\033[32m✅ Job finished:\033[0m Final time: \033[33m{elapsed_time_str}\033[0m")

                file_content = client.files.download(file=result_file_name).decode('utf-8')
                responses = sorted([parse_json(line) for line in file_content.split("\n") if len(line) != 0],
                                   key=lambda x: int(x["key"].split("/")[-1]))
                response = "".join([part["text"] for response in responses for part in response["response"]["candidates"][0]["content"]["parts"]])
                with open(output_file, "w") as f:
                    f.seek(0)
                    f.write(REGEX.sub(r"\1\2", response.replace("\n\n", "\0").replace("\n", " ").replace("\0", "\n\n")))
                    print("\033[32m✅ File saved!\033[0m")
    else:
        raise Exception("Failed to upload batch.")

def process_large_pdf(image_paths, output_folder):
    """Process images with Gemini 2.0 Flash for OCR"""
    global BATCH_JOB
    
    print("\033[94m✨ OCR'ing document...\033[0m")
    requests_file = output_folder+"/batch-requests.jsonl"
    with open(requests_file, 'w+') as f:
        for i, image_path in enumerate(image_paths):
            sys.stdout.write("\033[K")  # Clear the line
            print(f"\033[94mUploading image {i+1}...\033[0m", end='\r')
            image_uri = client.files.upload(file=image_path).uri
            f.write(json.dumps({
                "key": f"{output_folder}/pages/{i+1}",
                "request": {
                    "contents": [
                        {"parts": [
                            {"text": prompts.ocr_prompt()},
                            {"file_data": {"file_uri": image_uri}}]}
                    ]
                }
            }) + "\n")

    run_batch(requests_file, output_folder, output_folder+".intermediate.md")

def signal_handler(sig, frame):
    print('Quiting...')
    if BATCH_JOB != None:
        print('Cancelling batch job')
        client.batches.cancel(name=BATCH_JOB.name)
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

OVERLAP_SIZE = 1000

def harmonize_document(input_file, output_folder):
    global OVERLAP_SIZE, PDF_TEXT, PAGE_NUMBER
    global BATCH_JOB
    
    print("\033[94m🔬 Harmonizing document...\033[0m")
    requests_file = output_folder+"/batch-requests-harmonize.jsonl"
    with open(requests_file, 'w+') as f, open(input_file, "r") as f2:
        extracted_text = f2.read()
        chunks = split_overlapping(extracted_text, 2000, OVERLAP_SIZE)
        for i, chunk in enumerate(chunks):
            words = chunk.split(' ')
            chunk_prompt = [
                {"text": "\n\n<chunk_context>\n" + " ".join(words[:OVERLAP_SIZE]) + "\n</chunk_context>\n\n"},
                {"text": "\n\n<chunk>\n" + " ".join(words[OVERLAP_SIZE:]) + "\n</chunk>\n\n"}
            ] if i != 0 else [
                {"text": "\n\n<chunk_context>\n" + "\n</chunk_context>\n\n"},
                {"text": "\n\n<chunk>\n" + " ".join(words) + "\n</chunk>\n\n"}
            ]
            
            f.write(json.dumps({
                "key": f"{output_folder}/chunks/{i+1}",
                "request": {
                    "contents": [
                        {"parts": [
                            {"text": prompts.harmonize_prompt()},
                            *chunk_prompt
                        ]}
                    ]
                }
            }) + "\n")

    run_batch(requests_file, output_folder, output_folder+".md")
    print("\n\n\033[92m📄 Cleaning done, wrote document to: \033[0m\033[94m" + output_folder+".md" + "\033[0m")


def run_qa_linter(pdf_file: str, input_file: str, output_file: str):
    print("\033[92m👩‍⚕️ Looking for possible problems...\033[0m")
    try:
        result = run(
            [
                "wdiff",
                input_file,
                output_file,
                "--no-common",
                "--ignore-case",
                "--statistics",
            ],
            capture_output=True,
        )
        diff_output = result.stdout.decode("utf-8").replace("======================================================================", "")
    except Exception as e:
        print(f"Error running wdiff: {e}")
        return

    red_start = "\033[91m[-"  # Bright red
    red_end = "-]\033[0m"       # Reset to default
    green_start = "\033[92m{+"  # Bright green
    green_end = "+}\033[0m"     # Reset to default

    highlighted_output = diff_output.replace("[-", red_start).replace("-]", red_end).replace("{+", green_start).replace("+}", green_end)
    print("Word diff: ")
    print(highlighted_output)
    print("Gemini assessment:")
    extracted_text = client.files.upload(file=input_file, config={ 'mime_type': 'text/markdown' })
    original_pdf = client.files.upload(file=pdf_file, config={ 'mime_type': 'application/pdf' })
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            prompts.qa_prompt(),
            extracted_text,
            diff_output
        ],
        config=types.GenerateContentConfig(
            temperature=0.1
        )
    )
    print(response.text)
    
    
parser = argparse.ArgumentParser(description='Process a PDF and generate markdown files.')
parser.add_argument('input_pdf', help='Path to the input PDF file')
parser.add_argument('output_name', help='Base name for output files and directory')
parser.add_argument('--clean', action='store_true', help='Clean up intermediate files and directory')

if __name__ == "__main__":
    args = parser.parse_args()

    if not os.path.exists(args.input_pdf):
        print("\033[93m⚠️  That PDF does not exist.\033[0m")
        exit(1)

    image_paths = convert_pdf_to_images(args.input_pdf, args.output_name)
    
    if not os.path.exists(args.output_name + ".intermediate.md"):
        process_large_pdf(image_paths, args.output_name)
    else:
        print("\033[93m⚠️  Reusing previous intermediate file. Delete it if you don't want that to happen.\033[0m")
    
    harmonize_document(args.output_name + ".intermediate.md", args.output_name)
    
    run_qa_linter(args.input_pdf, args.output_name  + ".intermediate.md", args.output_name + ".md")
    
    if args.clean:
        os.remove(args.output_name + ".intermediate.md")
        shutil.rmtree(args.output_name, ignore_errors=True)
        
    exit(0)
