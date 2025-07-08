# Gemini OCR

Gemini 2.0 Flash [changes *everything*](https://www.sergey.fyi/articles/gemini-flash-2) when it comes to cheap, effective, robust OCR.

I've tried every OCR solution on the planet in my archival and collection process, and nothing beats its abilities, not just in multimodal VLM extraction of text, but also in its cheap and fast ability to do large scale heuristic text edits. It's far from perfect, and whether it gets something right is generally stochastic to some degree of course, being a language model --- but whether a particular regex works on each instance of what I want it to apply to in a given document, or will miss some, or overmatch, or apply a bad transformation that removes crucial words from sentences, is, while technically deterministic, *also* essentially nondeterministic as part of the cybernetic system that is me and my computer as a whole, so I don't see it as a problem, and by and large Gemini is more accurate than most OCR methods. Additionally, technically more correct but more garbage-filled OCR is less useful to me than slightly less correct but cleaner OCR, for what I'm doing.

This project uses UV, so it should be very easy to install and run, unlike most Python packages. I make no promises though.

The code is originally based on the code [here](https://apidog.com/blog/gemini-2-0-flash-ocr/), but I've since made it far more performant (through asynchrony) and robust, as well as encapsulated it into a relatively self explanatory and easy to use CLI utility.

## How it works

This pipeline executes a multi stage document transformation.

- The script converts each page of the input PDF into a separate JPG image at 150dpi, caching the results in an output folder.
- It processes these images in batches, feeding them to Gemini 2.0 Flash Lite to perform OCR and extract the raw text content into an intermediate file. Each image is processed as a separate request to minimize hallucinations, but each request in a batch is processed simultaniously (asynchronously), while the batches themselves are processed sequentially, to both speed up the process but avoid spamming too many requests at once.
- The raw text is then split into large, overlapping chunks. This ensures context is not lost at the boundaries during the next step.
- Each chunk is passed to Gemini 2.0 Flash with a detailed harmonization prompt, which reflows paragraphs, standardizes markdown, and removes OCR artifacts. Again, these chunks are treated as separate asynchronous requests to minimize hallucinations and confusion, where these requests are grouped into sequentially processed batches.
- The cleaned chunks are stitched together into the final output markdown file.
- Finally, it runs a `wdiff` between the raw intermediate text and the final harmonized text. The diff report is fed to Gemini one last time to perform a QA analysis and generate a list of potential errors.

## Example

- [before](https://egressac.wordpress.com/2014/10/01/postcapitalist-desire-37-pieces-of-flair-october-2014/)

- [after](./postcapitalist-desire.md)
