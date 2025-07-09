<center>
<h1>Gemini OCR</h1>

<p><img src="https://img.shields.io/badge/Python-3.x-blue.svg" alt="Python 3.0 badge"><img src="https://img.shields.io/badge/License-MPL-yellow.svg" alt="MPL 2.0 badge"><img src="https://img.shields.io/badge/Install_with-UV-orange.svg" alt="Install with UV"></p>

<p><small>✅ Cheap, 🚀 Fast, ✨ Clean.</small></p>
</center>

---

Large language models, and especially Gemini 2.0 Flash, change *everything* when it comes to cheap, effective, robust OCR. This project leverages Gemini's multimodal capabilities and powerful text transformation abilities to deliver unparalleled OCR results, coupled with intelligent post-processing to clean and harmonize extracted text without hallucinating.

## Table of Contents

*   [Why LLMs, and why Gemini 2.0 Flash and Flash-Lite?](#why-llms-and-why-gemini-20-flash-and-flash-lite)
*   [Acknowledgements](#acknowledgements)
*   [How it works](#how-it-works)
*   [Example](#example)
*   [Footnotes](#footnotes)

## Why LLMs, and why Gemini 2.0 Flash and Flash-Lite?

I've tried every OCR solution on the planet in my archival and collection process, and nothing beats Gemini 2.0 Flash's abilities, not just in multimodal capabilities for extraction of text from images[^1][^2], but also in its cheap and fast ability to do large scale heuristic text edits to clean things up afterwards[^4] without hallucinating[^3]. To quote that first source regarding OCR:

> Overall VLMs performance matched or exceeded most [all] traditional OCR providers. The most notable performance gains were in documents with charts/infograpics, handwriting, or complex input fieds (i.e. checkboxes, highlighted fields). VLMs are also more predictable on photos and low quality scans. They are generally more capable of "looking past the noise" of scan lines, creases, watermarks. Traditional models tend to outperform on high-density pages (textbooks, research papers) as well as common document formats like tax forms.

It should also be noted that the top-of-the-line traditional OCR systems just do one thing: OCR. LLMs allow you to use the same tool for both OCR and post facto cleaning, which makes things simpler, and cheaper probably.

It's far from perfect, and whether it gets something right is generally stochastic to some degree of course, being a language model --- but whether a particular regex works on each instance of what I want it to apply to in a given document, or will miss some, or overmatch, or apply a bad transformation that removes crucial words from sentences, is, while technically deterministic, *also* essentially nondeterministic as part of the cybernetic system that is me and my computer as a whole, so I don't see it as a problem, and by and large Gemini is more accurate than most OCR methods. Additionally, technically more correct but more garbage-filled OCR is less useful to me than slightly less correct but cleaner OCR, for what I'm doing.

## Acknowledgements

The code is originally based on the code [here](https://apidog.com/blog/gemini-2-0-flash-ocr/), but I've since made it far more performant (through asynchrony) and robust, as well as encapsulated it into a relatively self explanatory and easy to use CLI utility.

## How it works

This pipeline executes a multi stage document transformation.

- The script converts each page of the input PDF into a separate JPG image at 150dpi, caching the results in an output folder.
- It processes these images in batches, feeding them to Gemini 2.0 Flash Lite to perform OCR and extract the raw text content into an intermediate file. Each image is processed as a separate request to minimize hallucinations, but each request in a batch is processed simultaniously (asynchronously), while the batches themselves are processed sequentially, to both speed up the process but avoid spamming too many requests at once.
- The raw text is then split into large, overlapping chunks. This ensures context is not lost at the boundaries during the next step.
- Each chunk is passed to Gemini 2.0 Flash with a detailed harmonization prompt, which reflows paragraphs, standardizes markdown, and removes OCR artifacts. Again, these chunks are treated as separate asynchronous requests to minimize hallucinations and confusion, where these requests are grouped into sequentially processed batches.
- The cleaned chunks are stitched together into the final output markdown file.
- Finally, it runs a `wdiff` between the raw intermediate text and the final harmonized text. The diff report is fed to Gemini one last time to perform a QA analysis and generate a list of potential errors.

```
┌─────────────┐
│  PDF Input  │
└──────┬──────┘
       │
       ▼
┌───────────────────┐
│ Convert to JPGs   │ (150dpi, Cached)
└─────────┬─────────┘
          │
          ▼ (Batched Async Requests)
┌───────────────────┐
│ Gemini 2.0 Flash  │
│      (OCR)        │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Raw Text (Temp)  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Split into Chunks │ (Large, Overlapping)
└─────────┬─────────┘
          │
          ▼ (Batched Async Requests)
┌───────────────────┐
│ Gemini 2.0 Flash  │
│   (Harmonization) │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Stitched Chunks   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐     ┌───────────────────┐
│ Final Markdown    │     │ Raw Text (Temp)   │
└─────────┬─────────┘     └─────────┬─────────┘
          │          (wdiff)          │
          └─────────────┬─────────────┘
                        ▼
              ┌───────────────────┐
              │ Diff Report       │
              │ (wdiff Output)    │
              └─────────┬─────────┘
                        │ (Gemini QA)
                        ▼
              ┌───────────────────┐
              │ Potential Errors  │
              │   List (QA)       │
              └───────────────────┘
```

## Example

- [before](https://egressac.wordpress.com/2014/10/01/postcapitalist-desire-37-pieces-of-flair-october-2014/)

- [after](./postcapitalist-desire.md)

## Footnotes

[^1]: https://getomni.ai/blog/ocr-benchmark

[^2]: https://www.sergey.fyi/articles/gemini-flash-2

[^3]: https://github.com/vectara/hallucination-leaderboard

[^4]: https://review.gale.com/2024/09/03/using-large-language-models-for-post-ocr-correction/

