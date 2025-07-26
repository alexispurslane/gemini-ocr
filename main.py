import difflib
import json
from difflib import SequenceMatcher
import math
import webbrowser
import pprint
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
PAGES = []

# Configure the Gemini API
client = genai.Client(
    project=PROJECT_ID,
    location=LOCATION_ID or 'us-central1'
)

######################################################################################
#                                 Phase one                                          #
######################################################################################

class TOCHeading(pydantic.BaseModel):
    text: str
    level: int

def get_toc(pdf_file, output_folder):
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
        headings = json.loads(response.text)
        final_headings = []
        seen_headings = set()
        for i, heading in enumerate(headings):
            key = heading["text"].strip().lower().translate(str.maketrans('', '', string.punctuation))
            if key not in seen_headings:
                seen_headings.add(key)
                heading["level"] = str(min(
                    (int(final_headings[-1]["level"]) + 1) if i != 0 else math.inf,
                    int(heading["level"])
                ))
                final_headings.append(heading)
        with open(output_folder+"/toc.json", "w+") as f:
            f.write(json.dumps(final_headings))
        return final_headings

def process_large_pdf(image_paths, output_folder, table_of_contents):
    """Process images with Gemini 2.0 Flash for OCR"""
    global BATCH_JOB, COST, PAGES

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
                            {"text": "<table_of_contents>\n" + "\n".join([int(heading["level"])*"#" + " " + heading['text'] for heading in table_of_contents]) + "\n</table_of_contents>"},
                            {"inline_data": { "data": base64.b64encode(bytes).decode("utf-8"), "mime_type": "image/jpeg" }}]},
                    ]
                },
                'generation_config': {'temperature': '0.1'}
            }) + "\n")

    (cost, _, pages) = run_batch(client, requests_file, output_folder, output_folder+".intermediate.md")
    PAGES = pages
    COST += cost

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
def normalize(s, remove_whitespace=False):
    s = re.sub(r"  +", " ", s.translate(str.maketrans(",#", "  "))).strip().lower()
    if remove_whitespace:
        return re.sub(r"\s+|\n+", "", s)
    else:
        return s

def apply_table_of_contents(harmonized_text, headings):
    lines = harmonized_text.split("\n")
    for i, line in enumerate(lines):
        nl = normalize(line)
        ni, next_nonempty_line = next(((i+j, line) for j, line in enumerate(lines[i+1:i+4]) if len(line.strip()) > 1), (-1, None))
        first_char = next_nonempty_line.strip()[0] if next_nonempty_line != None else ""
        next_line_is_continuation = next_nonempty_line != None and not first_char.isupper() and not first_char.isnumeric()
        if len(line) == 0:
            continue
        else:
            line_already_merged = False
            for heading in headings:
                search = re.search(r"^([A-Za-z +0-9].*)[:.] (.*)$", heading["text"])
                last = heading["text"]
                if search:
                    last = max(reversed(search.groups()), key=len)
                nh = normalize(last.split(" by ")[0])
                if nl.endswith(nh) and not next_line_is_continuation:
                    print("Applying heading: ", heading)
                    without = nl.removesuffix(nh)
                    if len(without) > 0.90*len(nl):
                        lines[i] = line + "\n" + int(heading["level"])*"#" + " " + heading["text"]
                    else:
                        lines[i] = int(heading["level"])*"#" + " " + heading["text"]
                elif not line_already_merged and not nl.endswith(".") and next_line_is_continuation:
                    print("Merging lines", lines[i], "|", next_nonempty_line)
                    lines[i] = lines[i] + " " + next_nonempty_line
                    del lines[ni+1]
                    line_already_merged = True
            
    return "\n".join(lines)

def _test_toc():
     file = ""
     with open("conversions/libidinal-economy.intermediate.md", "r") as f: file = f.read()
     toc = []
     with open("conversions/libidinal-economy/toc.json", "r") as f: toc = json.loads(f.read())
     with open("foo", "w") as f: f.write(apply_table_of_contents(file, toc))
     
def harmonize_document(input_file, output_folder, headings):
    global CHUNK_OVERLAP_WORDS, PAGE_NUMBER, BATCH_JOB, COST

    print("\033[94m🔬 Harmonizing document...\033[0m")
    requests_file = output_folder+"/batch-requests-harmonize.jsonl"

    
    with open(requests_file, 'w+') as f, open(input_file, "r") as f2:
        ## Apply TOC
        extracted_text = apply_table_of_contents(re.sub("<BLANK_LINE>", "\n", f2.read()), headings)
        # extracted_text = f2.read()
        
        ## Create requests and ground truth to compare to
        chunks = split_overlapping(extracted_text, 2000, CHUNK_OVERLAP_WORDS)
        ground_truth_chunk_output = []
        for i, chunk in enumerate(chunks):
            words = chunk.split(' ')
            chunk_prompt = []
            if i == 0:
                chunk_prompt = [
                    {"text": "\n\n<chunk_context>\n" + "\n</chunk_context>\n\n"},
                    {"text": "\n\n<chunk>\n" + " ".join(words) + "\n</chunk>\n\n"}
                ]
                ground_truth_chunk_output.append(" ".join(words))
            else:
                chunk_prompt = [
                    {"text": "\n\n<chunk_context>\n" + " ".join(words[:CHUNK_OVERLAP_WORDS]) + "\n</chunk_context>\n\n"},
                    {"text": "\n\n<chunk>\n" + " ".join(words[CHUNK_OVERLAP_WORDS:]) + "\n</chunk>\n\n"}
                ]
                ground_truth_chunk_output.append(" ".join(words[CHUNK_OVERLAP_WORDS:]))

            f.write(json.dumps({
                "key": f"{output_folder}/chunks/{i+1}",
                "request": {
                    "contents": [
                        {"parts": [
                            {"text": prompts.harmonize_prompt()},
                            *chunk_prompt
                        ]}
                    ]
                },
                'generation_config': {'temperature': '0.1', 'max_output_tokens': 4096}
            }) + "\n")

    (cost, _, chunk_output) = run_batch(client, requests_file, output_folder, None)
    COST += cost

    with open(output_folder+".md", "w") as f:
        for ground_truth, model_output in zip(ground_truth_chunk_output, chunk_output):
            a = normalize(ground_truth, remove_whitespace=True)
            b = normalize(model_output, remove_whitespace=True)
            if SequenceMatcher(None, a, b).ratio() > 0.95:
                f.write(model_output)
            else:
                print("\033[93m⚠️  Model has output a harmonized chunk that is significantly different, in normalized form, from the original. Substituting the original back in to preserve document accuracy.\033[0m")
                print("GROUND TRUTH: ", ground_truth)
                print("MODEL OUTPUT: ", model_output)
                f.write(ground_truth)
            
    print("\n\n\033[92m📄 Cleaning done, wrote document to: \033[0m\033[94m" + output_folder+".md" + "\033[0m")

######################################################################################
#                                 Phase four                                         #
######################################################################################


def run_qa_linter(pdf_file: str, output_folder: str):
    print("\033[92m👩‍⚕️ Looking for possible problems in harmonization step...\033[0m")
    try:
        result = run(
            [
                "wdiff",
                output_folder+".intermediate.md",
                output_folder+".md",
                "--no-common",
                "--ignore-case",
                "--statistics",
            ],
            capture_output=True,
        )
        diff_output = result.stdout.decode("utf-8", errors="replace").replace("\n======================================================================", "")
    except Exception as e:
        print(f"Error running wdiff: {e}")
        return

    red_start = "\033[91m[-"  # Bright red
    red_end = "-]\033[0m"       # Reset to default
    green_start = "\033[92m{+"  # Bright green
    green_end = "+}\033[0m"     # Reset to default

    highlighted_output = diff_output.replace("[-", red_start).replace("-]", red_end).replace("{+", green_start).replace("+}", green_end)
    print(highlighted_output)
    html_body = ""
    for i, page in enumerate(PAGES):
        img_path = f"./page_{i+1}.jpg"
        html_body += f"""
<tr>
    <td><img src="{img_path}" alt="Page {i+1}"/></td>
    <td><pre>{page}</pre>
</tr>
"""
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OCR Visual QA Report</title>
    </head>
    <body>
        <h1>OCR Visual QA Report for: {pdf_file}</h1>
        <table>
            <thead><tr><td>Page</td><td>OCR Output</td></tr></thead>
            <tbody>
                {html_body}
            </tbody>
        </table>
    </body>
    </html>
    """

    report_path = os.path.join(output_folder, "qa_report.html")
    with open(report_path, "w") as f:
        f.write(html_template)
    
    print(f"\033[92m✅ Report saved to: \033[0m\033[94m{os.path.abspath(report_path)}\033[0m")
    print("\033[92m👩‍⚕️ Opening primary OCR report...\033[0m")
    webbrowser.open(os.path.abspath(report_path), new=2)

######################################################################################
#                                 Main                                               #
######################################################################################
    
parser = argparse.ArgumentParser(description='Process a PDF and generate markdown files.')
parser.add_argument('input_pdf', help='Path to the input PDF file')
parser.add_argument('output_name', help='Base name for output files and directory')
parser.add_argument('--clean', action='store_true', help='Clean up intermediate files and directory')
parser.add_argument('--header-offset', type=int, help="How much in pixels to crop off the top of each image.", default=0)
parser.add_argument('--footer-offset', type=int, help="How much in pixels to crop off the bottom of each image.", default=0)

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

    if not os.path.exists(args.output_name):
        os.mkdir(args.output_name)
    
    toc = []
    if not os.path.exists(args.output_name+"/toc.json"):
        toc = get_toc(args.input_pdf, args.output_name)
    else:
        print("\033[93m⚠️  Reusing previous table of contents. Delete it if you don't want that to happen. Note: uploading the entire PDF for TOC generation can be expensive. \033[0m")
        with open(args.output_name+"/toc.json", "r") as f:
            toc = json.loads(f.read())
    
    image_paths, pdf_text, page_count = convert_pdf_to_images(args.input_pdf, args.output_name, header_offset=args.header_offset, footer_offset=args.footer_offset)
    
    if not os.path.exists(args.output_name + ".intermediate.md"):
        process_large_pdf(image_paths, args.output_name, toc)
    else:
        print("\033[93m⚠️  Reusing previous intermediate file. Delete it if you don't want that to happen.\033[0m")

    harmonize_document(args.output_name + ".intermediate.md", args.output_name, toc)

    run_qa_linter(args.input_pdf, args.output_name)


    if COST > 0.3:
        print("\033[93m⚠️  Total cost: ${:,.4f}, or {} pages per dollar\033[0m".format(COST, 1.0 / (COST / page_count)))
    else:
        print("\033[94mℹ️  Total cost: ${:,.4f}, or {} pages per dollar\033[0m".format(COST, 1.0 / (COST / page_count)))


    if args.clean:
        os.remove(args.output_name + ".intermediate.md")
        shutil.rmtree(args.output_name, ignore_errors=True)

    exit(0)
