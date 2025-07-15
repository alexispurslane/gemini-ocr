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
import time
import sys
from google.genai import types
import pdf2image
from PIL import Image
import io
from utils import *
import pypdf

from typing import Iterator

WORD_JOIN_REGEX = re.compile(r"(.)- (.)")


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

def run_batch(client, requests_file, output_folder, output_file=None) -> (float, str, list[str]):
    global BATCH_JOB
    cost = 0
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
            return (0, "")
        elif BATCH_JOB.state.name == 'JOB_STATE_SUCCEEDED':
            if BATCH_JOB.dest and BATCH_JOB.dest.file_name:
                result_file_name = BATCH_JOB.dest.file_name

                print(f"\033[32m✅ Job finished:\033[0m Final time: \033[33m{elapsed_time_str}\033[0m")

                file_content = client.files.download(file=result_file_name).decode('utf-8')
                responses = sorted([parse_json(line) for line in file_content.split("\n") if len(line) != 0],
                                   key=lambda x: int(x["key"].split("/")[-1]))
                fulltext = ""
                raw_responses = []
                for i, response in enumerate(responses):
                    if response != None and "response" in response:
                        response = response["response"]
                        try:
                            cost += ((int(response["usageMetadata"]["promptTokenCount"]) / 1_000_000) * 0.10 + (int(response["usageMetadata"].get("candidatesTokenCount", 0)) / 1_000_000) * 0.4) * 0.5
                            
                            raw_responses.append("")
                            for part in response["candidates"][0]["content"]["parts"]:
                                fulltext += part["text"]
                                raw_responses[-1] += part["text"]
                            
                            if fulltext[-10:].strip()[-1] in string.punctuation:
                                fulltext += "\n"
                                raw_responses[-1] += "\n"
                        except KeyError as e:
                                print(f"\U0001F6A8  \033[31mMissing expected property on response object {i}: \033[0m")
                                pprint.pp(response)
                                if response["candidates"][0]["finishReason"] == "RECITATION":
                                    print("\033[93m⚠️  Recitation error received, retrying.\033[0m")
                                    (cost2, fulltext, pages) = run_batch(client, requests_file, output_folder, output_file)
                                    return (cost + cost2, fulltext, pages)
                                raise e
                    else:
                        print(response)

                fulltext = WORD_JOIN_REGEX.sub(r"\1\2", fulltext.replace("\n\n", "\0").replace("\n", " ").replace("\0", "\n\n"))
                if output_file != None:
                    with open(output_file, "w") as f:
                        f.seek(0)
                        f.write(fulltext)
                        print("\033[32m✅ File saved!\033[0m")
                return (cost, fulltext, raw_responses)
    else:
        raise Exception("Failed to upload batch.")
    
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

