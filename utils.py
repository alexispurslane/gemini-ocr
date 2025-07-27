import json
import string
import pprint
import datetime
import time
import sys
from contextlib import suppress
import re
import glob
import os
from google.genai import types
import pdf2image
from PIL import Image
import io
import pypdf

from typing import Iterator

WORD_JOIN_REGEX = re.compile(r"(.)- (.)")

class RecitationError(Exception):
    def __init__(self, partial_cost=0):
        self.partial_cost = partial_cost
        super().__init__("Recitation error occurred")

def _process_results(file_content: str, initial_cost: float) -> tuple[float, str, list[str]]:
    cost = initial_cost
    responses = sorted([parse_json(line) for line in file_content.split("\n") if len(line) != 0],
                       key=lambda x: int(x["key"].split("/")[-1]))
    fulltext = ""
    raw_responses = []
    
    for i, response in enumerate(responses):
        if response is not None and "response" in response:
            response_data = response["response"]
            try:
                # Accumulate cost before checking for errors
                cost += ((int(response_data["usageMetadata"]["promptTokenCount"]) / 1_000_000) * 0.10 + 
                         (int(response_data["usageMetadata"].get("candidatesTokenCount", 0)) / 1_000_000) * 0.4) * 0.5
                
                current_candidate = response_data.get("candidates", [{}])[0]
                if current_candidate.get("finishReason") == "RECITATION":
                    raise RecitationError(partial_cost=cost)

                raw_responses.append("")
                for part in current_candidate.get("content", {}).get("parts", []):
                    fulltext += part.get("text", "")
                    raw_responses[-1] += part.get("text", "")

                if len(fulltext) > 0 and fulltext.strip() and fulltext.strip()[-1] in string.punctuation:
                    fulltext += "\n"
                    raw_responses[-1] += "\n"
            
            except KeyError as e:
                print(f"🐍  \033[31mMissing expected property on response object {i}: \033[0m")
                pprint.pp(response_data)
                raise e
        else:
            print(f"⚠️  Malformed response object found: {response}")

    fulltext = WORD_JOIN_REGEX.sub(r"\1\2", fulltext.replace("\n\n", "\0").replace("\n", " ").replace("\0", "\n\n"))
    return (cost, fulltext, raw_responses)


def split_overlapping(text: str, chunk_size: int, overlap: int) -> Iterator[str]:    
    step = chunk_size - overlap
    words = text.split(" ")
    
    for i in range(0, len(words), step):
        yield " ".join(words[i:i + chunk_size])


def create_batches(elements, batch_size=50):
    """Group images into batches for processing"""
    for i in range(0, len(elements), batch_size):
        yield elements[i:i + batch_size]

def image_path_to_bytes(path: str):
    pil_im = Image.open(path)
    b = io.BytesIO()
    pil_im.save(b, 'jpeg')
    return b.getvalue()

def parse_json(s):
    res = None
    with suppress(json.JSONDecodeError):
        res = json.loads(s)
    return res

def sort_key(s: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.findall(r'\D+|\d+', s)]

def run_batch(client, requests_file, output_folder, output_file=None, attempt=0, max_retries=3) -> tuple[float, str, list[str]]:
    global BATCH_JOB
    
    uploaded_file = client.files.upload(
        file=requests_file,
        config=types.UploadFileConfig(display_name=requests_file, mime_type='jsonl')
    )

    if uploaded_file is None:
        raise Exception("Failed to upload batch file.")

    BATCH_JOB = client.batches.create(
        model="gemini-2.0-flash",
        src=uploaded_file.name,
        config={'display_name': f"{output_folder}-batch"}
    )

    completed_states = {'BATCH_STATE_RUNNING', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED'}
    print(f"\033[32m✨ Waiting for job \033[33m{BATCH_JOB.name}\033[32m to complete...\033[0m")
    
    start_time = datetime.datetime.now()
    spinner_chars = ['-', '\\', '|', '/']
    spinner_index = 0

    while BATCH_JOB.state.name not in completed_states:
        sys.stdout.write("\033[K")  # Clear the line
        elapsed_time_str = str(datetime.datetime.now() - start_time).split('.')[0]
        
        if BATCH_JOB.state.name == "BATCH_STATE_RUNNING":
            print(f"Pending {spinner_chars[spinner_index]} Elapsed: {elapsed_time_str}", end="\r")
            spinner_index = (spinner_index + 1) % len(spinner_chars)
        else:
            print(f"Current state: {BATCH_JOB.state.name} Elapsed: {elapsed_time_str}", end="\r")
        
        time.sleep(1)
        BATCH_JOB = client.batches.get(name=BATCH_JOB.name)

    if BATCH_JOB.state.name == 'JOB_STATE_FAILED':
        raise RuntimeError(f"❌ \033[31mBatch job '{BATCH_JOB.name}' failed with state '{BATCH_JOB.state.name}'.\033[0m\n\nFull job details:\n{BATCH_JOB}")

    elif BATCH_JOB.state.name == 'JOB_STATE_SUCCEEDED':
        if BATCH_JOB.dest and BATCH_JOB.dest.file_name:
            result_file_name = BATCH_JOB.dest.file_name
            elapsed_time_str = str(datetime.datetime.now() - start_time).split('.')[0]
            print(f"\n\033[32m✅ Job finished:\033[0m Final time: \033[33m{elapsed_time_str}\033[0m")
            
            file_content = client.files.download(file=result_file_name).decode('utf-8')
            
            try:
                (total_cost, fulltext, raw_responses) = _process_results(file_content, 0)
                
                if output_file is not None:
                    with open(output_file, "w") as f:
                        f.write(fulltext)
                    print("\033[32m✅ File saved!\033[0m")
                
                return (total_cost, fulltext, raw_responses)

            except RecitationError as e:
                if attempt < max_retries - 1:
                    backoff_time = 2 ** (attempt + 1)
                    print(f"\033[93m⚠️  Recitation error received. Retrying in {backoff_time}s (attempt {attempt + 2}/{max_retries})... \033[0m")
                    time.sleep(backoff_time)
                    (cost2, fulltext, pages) = run_batch(client, requests_file, output_folder, output_file, attempt=attempt + 1)
                    return (e.partial_cost+cost2, fulltext, pages)
                else:
                    raise RuntimeError(f"Maximum retries ({max_retries}) reached for recitation error.")
    else:
        raise Exception("Batch job did not complete successfully.")
    
def convert_pdf_to_images(pdf_path, output_folder, dpi=150, header_offset=0, footer_offset=0) -> tuple[list[str], str, int]:
    # Create output directory if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"\033[92m📁 Created output directory: {output_folder}\033[0m")

    # Convert PDF pages to images
    print(f"\033[94m⏳ Converting PDF to images... This may take a moment.\033[0m")

    file = pypdf.PdfReader(pdf_path)
    pdf_text = "".join([page.extract_text() for page in file.pages])
    image_paths = []

    page_count = len(file.pages)
    images = glob.glob(f'{output_folder}/*.jpg')
    image_count = len(images)

    if page_count == image_count:
       print("\033[93m⚠️  Reusing previous extracted images. Delete the output folder if you don't want that to happen.\033[0m")
       image_paths = sorted(images, key=sort_key)
    else:
        images = pdf2image.convert_from_path(pdf_path, dpi=dpi, thread_count=8, )

        # Save images to the output folder
        image_paths = []
        for i, image in enumerate(images):
            image_path = os.path.join(output_folder, f'page_{i+1}.jpg')
            image = image.crop((0, header_offset, image.width, image.height - footer_offset))
            image.save(image_path, 'JPEG')
            sys.stdout.write("\033[K")
            print(f"\033[92m✅ Page {i+1} saved as {image_path}\033[0m", end='\r')
            image_paths.append(image_path)

        print(f"\n\033[92m✨ Conversion completed. Total images: {len(images)}\033[0m")
        
    
    return (image_paths, pdf_text, page_count)

