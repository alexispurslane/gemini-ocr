import json
import string
import enum
import pydantic
import sys
import signal
import re
import argparse
import os
import sys
from google import genai
from google.genai import types
from utils import *
import prompts
from subprocess import run
import shutil
import base64

######################################################################################
#                                 Global state                                       #
######################################################################################

CHUNK_OVERLAP_WORDS = 1000
COST = 0
PROJECT_ID = os.environ['GOCR_PROJECT_ID']
LOCATION_ID = os.environ.get('GOCR_LOCATION_ID')
BATCH_JOB = None

# Configure the Gemini API
client = genai.Client(
    project=PROJECT_ID,
    location=LOCATION_ID or 'us-central1'
)

######################################################################################
#                                 Phase one                                          #
######################################################################################

class HeadingLevel(enum.Enum):
  H1 = "H1"
  H2 = "H2"
  H3 = "H3"

class TOCHeading(pydantic.BaseModel):
    text: str
    page_number: int
    level: HeadingLevel

def get_toc(pdf_file):
    global COST
    print("\033[94m📚 Getting table of contents...\033[0m")
    uploaded_file = client.files.upload(
        file=pdf_file,
        config=types.UploadFileConfig(display_name=pdf_file,
                                      mime_type='application/pdf')
    )
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[prompts.toc_prompt(), uploaded_file],
        config={'temperature': '0.1', 'response_schema': list[TOCHeading], 'response_mime_type': 'application/json'}
    )
    COST += ((response.usage_metadata.prompt_token_count / 1_000_000) * 0.10 + (response.usage_metadata.candidates_token_count / 1_000_000) * 0.4)
    if response.text != None:
        print(response.text)
        headings = json.loads(response.text)
        final_headings = []
        seen_headings = set()
        for heading in headings:
            key = heading["text"].strip().lower().translate(str.maketrans('', '', string.punctuation))
            if key not in seen_headings:
                seen_headings.add(key)
                final_headings.append(heading)
        toc_string = "\n".join([int(entry["level"][-1])*"#" + " " + entry["text"] for entry in final_headings])
        print(toc_string)
        return toc_string

def process_large_pdf(image_paths, output_folder):
    """Process images with Gemini 2.0 Flash for OCR"""
    global BATCH_JOB, COST

    print("\033[94m✨ OCR'ing document...\033[0m")
    requests_file = output_folder+"/batch-requests.jsonl"
    with open(requests_file, 'w+') as f:
        for i, image_path in enumerate(image_paths):
            sys.stdout.write("\033[K")  # Clear the line
            print(f"\033[94mCreating batch request {i+1}...\033[0m", end='\r')
            bytes = image_path_to_bytes(image_path)
            f.write(json.dumps({
                "key": f"{output_folder}/pages/{i+1}",
                "request": {
                    "contents": [
                        {"parts": [
                            {"text": prompts.ocr_prompt()},
                            {"inline_data": { "data": base64.b64encode(bytes).decode("utf-8"), "mime_type": "image/jpeg" }}]}
                    ]
                }
            }) + "\n")

    COST += run_batch(client, requests_file, output_folder, output_folder+".intermediate.md")

def signal_handler(sig, frame):
    print('Quiting...')
    if BATCH_JOB != None:
        print('Cancelling batch job')
        client.batches.cancel(name=BATCH_JOB.name)
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

######################################################################################
#                                 Phase three                                        #
######################################################################################

def harmonize_document(input_file, output_folder, toc_string):
    global CHUNK_OVERLAP_WORDS, PAGE_NUMBER, BATCH_JOB, COST

    print("\033[94m🔬 Harmonizing document...\033[0m")
    requests_file = output_folder+"/batch-requests-harmonize.jsonl"
    with open(requests_file, 'w+') as f, open(input_file, "r") as f2:
        extracted_text = f2.read()
        chunks = split_overlapping(extracted_text, 2000, CHUNK_OVERLAP_WORDS)
        for i, chunk in enumerate(chunks):
            words = chunk.split(' ')
            chunk_prompt = [
                {"text": "<table_of_contents>\n" + toc_string + "\n</table_of_contents>"}
            ] + [
                {"text": "\n\n<chunk_context>\n" + " ".join(words[:CHUNK_OVERLAP_WORDS]) + "\n</chunk_context>\n\n"},
                {"text": "\n\n<chunk>\n" + " ".join(words[CHUNK_OVERLAP_WORDS:]) + "\n</chunk>\n\n"}
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

    COST += run_batch(client, requests_file, output_folder, output_folder+".md")
    print("\n\n\033[92m📄 Cleaning done, wrote document to: \033[0m\033[94m" + output_folder+".md" + "\033[0m")

######################################################################################
#                                 Phase four                                         #
######################################################################################


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
        diff_output = result.stdout.decode("utf-8").replace("\n======================================================================", "")
    except Exception as e:
        print(f"Error running wdiff: {e}")
        return

    red_start = "\033[91m[-"  # Bright red
    red_end = "-]\033[0m"       # Reset to default
    green_start = "\033[92m{+"  # Bright green
    green_end = "+}\033[0m"     # Reset to default

    highlighted_output = diff_output.replace("[-", red_start).replace("-]", red_end).replace("{+", green_start).replace("+}", green_end)
    print(highlighted_output)

######################################################################################
#                                 Main                                               #
######################################################################################
    
parser = argparse.ArgumentParser(description='Process a PDF and generate markdown files.')
parser.add_argument('input_pdf', help='Path to the input PDF file')
parser.add_argument('output_name', help='Base name for output files and directory')
parser.add_argument('--clean', action='store_true', help='Clean up intermediate files and directory')

if __name__ == "__main__":
    print("Checking dependencies exist...")
    if shutil.which('wdiff') is None:
        print("wdiff not found. Please install it:")
        if sys.platform == 'win32':
            print("Windows: Install using Chocolatey with 'choco install wdiff' or download from https://www.di-mgt.com.au/wdiff-for-windows.html")
        elif sys.platform == 'darwin':
            print("Mac: Install using Homebrew with 'brew install wdiff'")
        else:
            print("Linux: Use your package manager, e.g., 'sudo apt-get install wdiff' (Debian/Ubuntu) or 'sudo dnf install wdiff' (Red Hat), or use Linuxbrew with 'brew install wdiff'")

    args = parser.parse_args()

    if not os.path.exists(args.input_pdf):
        print("\033[93m⚠️  That PDF does not exist.\033[0m")
        exit(1)

    image_paths, pdf_text = convert_pdf_to_images(args.input_pdf, args.output_name)

    if not os.path.exists(args.output_name + ".intermediate.md"):
        process_large_pdf(image_paths, args.output_name)
    else:
        print("\033[93m⚠️  Reusing previous intermediate file. Delete it if you don't want that to happen.\033[0m")

    toc = get_toc(args.input_pdf)
    harmonize_document(args.output_name + ".intermediate.md", args.output_name, toc)

    run_qa_linter(args.input_pdf, args.output_name  + ".intermediate.md", args.output_name + ".md")

    print("\033[93m⚠️  Total cost: ${:,.4f}\033[0m".format(COST))

    if args.clean:
        os.remove(args.output_name + ".intermediate.md")
        shutil.rmtree(args.output_name, ignore_errors=True)

    exit(0)
