<div align="center">
<h1>Gemini OCR</h1>

<p><img src="https://img.shields.io/badge/Python-3.x-blue.svg" alt="Python 3.0 badge"> <img src="https://img.shields.io/badge/License-MPL-yellow.svg" alt="MPL 2.0 badge"> <img src="https://img.shields.io/badge/Install_with-UV-orange.svg" alt="Install with UV"></p>

<p><small>✅ Cheap, 🚀 Fast, ✨ Clean.</small></p>
</div>

---

Large language models, and especially Gemini 2.0 Flash, change *everything* when it comes to cheap, effective, robust OCR. This project leverages Gemini's multimodal capabilities and powerful text transformation abilities to deliver unparalleled OCR results, coupled with intelligent post-processing to clean and harmonize extracted text without hallucinating.

## Table of Contents

*   [Why LLMs, and why Gemini 2.0 Flash and Flash-Lite?](#why-llms-and-why-gemini-20-flash-and-flash-lite)
*   [Acknowledgements](#acknowledgements)
*   [How it works](#how-it-works)
*   [Example](#example)
*   [Footnotes](#footnotes)

## Why LLMs, and why Gemini 2.0 Flash and Flash-Lite?

I've tried every OCR solution on the planet in my archival and collection process, and large language models are a massive force multiplier for doing large scale heuristic text edits, which is very necessary for the often messy work of OCRing old texts[^4]. Obviously, then, any modern OCR pipeline should involve a decent, and actually large (e.g., >70b parameter, so that it can follow instructions accurately and make good judgement calls) LLM in the process somewhere. Okay, so any such project was bound to involve LLMs in the first place --- but why use them for the OCR part too, and why use Gemini 2.0 Flash specifically?

First, because modern multimodal language models --- but *especially* Gemini 2.0 Flash --- are superior to almost all traditional OCR methods at accurately extracting text from images under the conditions that are useful to me. To quote that first source regarding OCR:

> Overall VLMs performance matched or exceeded most [all] traditional OCR providers. The most notable performance gains were in documents with charts/infograpics, handwriting, or complex input fieds (i.e. checkboxes, highlighted fields). **VLMs are also more predictable on photos and low quality scans. They are generally more capable of "looking past the noise" of scan lines, creases, watermarks.** Traditional models tend to outperform on high-density pages (textbooks, research papers) as well as common document formats like tax forms.[^1]

Here's a graph from the same article:

![](https://framerusercontent.com/images/eDrtZeseTAW1PlgUnHGBmHHdNIc.png)

Second, because Gemini 2.0 Flash is the first large language model I know of where performing OCR with it at datacenter speeds (so, not self hosted and taking hours on a single machine) is actually cost-effective when compared to traditional OCR methods

With [batch processing](https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/batch-prediction-gemini)[^2]:

| Provider | Model | PDF to Markdown, Pages per Dollar |
|---|---|---|
| Gemini | 2.0 Flash | 🏆 ≈ 6,000 |
| Gemini | 2.0 Flash Lite | ≈ 12,000 (have not tested this yet) |
| Gemini | 1.5 Flash | ≈ 10,000 |
| AWS Textract | Commercial | ≈ 1000 |
| Gemini | 1.5 Pro | ≈ 700 |
| OpenAI | 4o-mini | ≈ 450 |
| LlamaParse | Commercial | ≈ 300 |
| OpenAI | 4o | ≈ 200 |
| Anthropic | claude-3-5-sonnet | ≈ 100 |
| Reducto | Commercial | ≈ 100 |
| Chunkr | Commercial | ≈ 100 |

(without batch processing Flash would be ~3,000 and Lite would be ~6,000).

Or even without[^1]:

![](https://framerusercontent.com/images/0r5y8c29WMw1j5xElh7cgaTRs3Q.png)

Third, because Gemini 2.0 Flash, again, specifically, has an extremely low hallucination rate[^3] and large context window[^5], allowing it to perform these tasks with accuracy while also being able to handle large documents and prompts if need be.

And fourth, because involving two separate AI systems, one for OCR and one for text cleaning and harmonization, is simply much more complexity for little gain.

It's far from perfect, and whether it gets something right is generally stochastic to some degree of course, being a language model --- but whether a particular regex works on each instance of what I want it to apply to in a given document, or will miss some, or overmatch, or apply a bad transformation that removes crucial words from sentences, is, while technically deterministic, *also* essentially nondeterministic as part of the cybernetic system that is me and my computer as a whole, so I don't see it as a problem, and by and large Gemini is more accurate than most OCR methods. Additionally, technically more correct but more garbage-filled OCR is less useful to me than slightly less correct but cleaner OCR, for what I'm doing.

## Acknowledgements

The code is originally based on the code [here](https://apidog.com/blog/gemini-2-0-flash-ocr/), but I've since made it far more performant (through asynchrony) and robust, as well as encapsulated it into a relatively self explanatory and easy to use CLI utility.

## How it works

This pipeline executes a multi stage document transformation.

- The script first submits the entire PDF to Gemini, requesting a JSON list detailing the text and level of each major heading/section. Ideally, this is derived from the table of contents. If absent, for shorter texts, the model infers the structure page by page. This generates a global structural context to ensure overall coherence during localized chunk harmonization.
- The script then converts each page of the input PDF into a separate JPG image at 150dpi, caching the results in an output folder.
- It processes these images in batches, feeding them to Gemini 2.0 Flash Lite to perform OCR and extract the raw text content into an intermediate file. Each image is processed as a separate request to minimize hallucinations, but each request in a batch is processed simultaniously.
- The raw text is then split into large, overlapping chunks. This ensures context is not lost at the boundaries during the next step.
- Each chunk is passed to Gemini 2.0 Flash with a detailed harmonization prompt, which reflows paragraphs, standardizes markdown, and removes OCR artifacts, and uses the table of contents generated in the first step to decide, when it comes across something that is likely to be a heading, what level the heading should be. Again, these chunks are treated as separate asynchronous requests to minimize hallucinations and confusion.
- The cleaned chunks are stitched together into the final output markdown file.
- Finally, it runs a `wdiff` between the raw intermediate text and the final harmonized text. The diff report is fed to Gemini one last time to perform a QA analysis and generate a list of potential errors.
- Finally, the tool outputs a total cost estimation. Combining all the steps, the cost appears to be roughly 3,000 pages per dollar, and the cost goes down the more pages you add.

```
┌──────────────────────┐
│      PDF Input       ├─────┐
└──────────┬───────────┘     │
           │                 │
           ▼                │
┌──────────────────────┐     │
│ Submit PDF to Gemini │     │
│ (Request JSON TOC)   │     │
└──────────┬───────────┘     │
           │                 │
           ▼                │
┌──────────────────────┐     │
│ Global Struct. Ctxt  │     │
└──────────┬───────────┘     │
           │                 │
           │   ┌─────────────┴────────┐
           │   │  Convert PDF to JPGs │ (150dpi, Cached)
           │   └──────────┬───────────┘
           │              │
           │              ▼ (Batched Async Requests)
           │   ┌──────────────────────┐
           │   │  Gemini 2.0 Flash    │
           │   │       (OCR)          │
           │   └──────────┬───────────┘
           │              │
           │              ▼
           │   ┌──────────────────────┐
           │   │   Raw Text (Temp)    │
           │   └──────────┬───────────┘
           │              │
           │              ▼
           │   ┌──────────────────────┐
           │   │  Split into Chunks   │ (Large, Overlapping)
           │   └──────────┬───────────┘
           │              │
           │              ▼ (Batched Async Requests)
           │   ┌──────────────────────┐
           └──>│  Gemini 2.0 Flash    │
               │ (Harmonization + TOC)│
               └──────────┬───────────┘
                          │
                          ▼
               ┌──────────────────────┐
               │   Stitched Chunks    │
               └──────────┬───────────┘
                          │
                          ▼
               ┌──────────────────────┐     ┌──────────────────────┐
               │   Final Markdown     │     │  Raw Text (Temp)     │
               └──────────┬───────────┘     └──────────┬───────────┘
                          │              (wdiff)       │
                          └──────────────────┬─────────┘
                                             ▼
                                   ┌──────────────────────┐
                                   │   Diff Report        │
                                   │   (wdiff Output)     │
                                   └──────────────────────┘          
```

## Example

- [before](https://egressac.wordpress.com/2014/10/01/postcapitalist-desire-37-pieces-of-flair-october-2014/)

- [after](./postcapitalist-desire.md)

## Footnotes

[^1]: https://getomni.ai/blog/ocr-benchmark

[^2]: https://www.sergey.fyi/articles/gemini-flash-2

[^3]: https://github.com/vectara/hallucination-leaderboard

[^4]: https://review.gale.com/2024/09/03/using-large-language-models-for-post-ocr-correction/

[^5]: https://www.prompthub.us/models/gemini-2-0-flash
