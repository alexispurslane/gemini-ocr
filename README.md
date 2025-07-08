# Gemini OCR

Gemini 2.0 Flash [changes *everything*](https://www.sergey.fyi/articles/gemini-flash-2) when it comes to cheap, effective, robust OCR.

I've tried every OCR solution on the planet in my archival and collection process, and nothing beats its abilities, not just in multimodal VLM extraction of text, but also in its cheap and fast ability to do large scale heuristic text edits. It's far from perfect, and whether it gets something right is generally stochastic to some degree of course, being a language model --- but whether a particular regex works on each instance of what I want it to apply to in a given document, or will miss some, or overmatch, or apply a bad transformation that removes crucial words from sentences, is, while technically deterministic, *also* essentially nondeterministic as part of the cybernetic system that is me and my computer as a whole, so I don't see it as a problem, and by and large Gemini is more accurate than most OCR methods. Additionally, technically more correct but more garbage-filled OCR is less useful to me than slightly less correct but cleaner OCR, for what I'm doing.

This project uses UV, so it should be very easy to install and run, unlike most Python packages. I make no promises though.

The code is originally based on the code [here](https://apidog.com/blog/gemini-2-0-flash-ocr/), but I've since made it far more performant (through asynchrony) and robust, as well as encapsulated it into a relatively self explanatory and easy to use CLI utility.
