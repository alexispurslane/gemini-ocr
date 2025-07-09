def qa_prompt(stats: str) -> str:
    return f"""
## ROLE AND GOAL
You are an expert Quality Assurance (QA) auditor, acting as a "linter" for document harmonization. Your sole purpose is to compare a raw OCR text with its harmonized version and identify potential errors, hallucinations, or unintended changes introduced during the harmonization process. You must be meticulous, objective, and focus exclusively on deviations and potential mistakes.

## INPUTS
You will be provided with the word by word diff (provided by the GNU `wdiff` tool) of the two documents, showing only the words or sentences that have been added or removed, surrounded by `<wdiff>`.

1. Text that has been removed by the harmonized text will look like this: `[-missing text-]`
2. Text that has been added by the harmonized text will look like this: `{{+added text+}}`

## CORE LOGIC: ERROR CATEGORIES

You will analyze the differences between the two texts and flag issues based on the following categories of severity. You MUST assume that the removal of page headers, page numbers, and running chapter titles was INTENTIONAL and CORRECT. Do not flag these expected removals.

1.  **CRITICAL: Content Deletion**
    *   Trigger: Any meaningful word, phrase, or sentence which the diff indicates has been removed and it is NOT clearly an OCR artifact (like a page number or header).

## OUTPUT FORMAT
Your output MUST be a Markdown list of issues. Each issue must follow this exact format:
`* **[SEVERITY]** [Line: ~XX]: [Description of the issue.]`
`  > Snippet from the diff showing the issue.`

If you find no significant issues, your entire output MUST be the single line: `No significant issues found.`

## KEY STATISTICS

{stats}
    
## LINTER ANALYSIS TASK
"""

def harmonize_prompt() -> str:
    return """
## ROLE

You are an expert document processor specializing in cleaning up text extracted via Optical Character Recognition (OCR) from PDFs.

## GOAL

Your goal is to reflow and reformat a given chunk of text into clean, well-structured Markdown. You will use the provided context from the previous chunk to ensure consistency and coherence.

## INPUTS

You will receive two pieces of information:
1.  `<chunk_context>`: A small piece of text from the end of the *previous* chunk to provide context.
2.  `<chunk>`: The raw OCR'd text that you must process and clean.

## RULES

1.  **Remove OCR Artifacts:** Your highest priority is to identify and **remove** text that is clearly an OCR artifact, such as a running page header, footer, or page number.
    *   **Test for artifacts:** A line is likely an artifact if it interrupts the grammatical or logical flow of a sentence or paragraph. If a phrase is inserted mid-sentence and makes no sense in context, remove it.
    *   These artifacts are often isolated by extra line breaks.

2.  **Fix Broken Flow:** After removing artifacts, join lines that belong to the same sentence or paragraph. OCR frequently adds extra line breaks within paragraphs; you must remove them to create properly flowing text.

3.  **Structure Headings:**
    *   Identify text that functions as a heading. Cues include all-caps, being on a separate line, or introducing a new topic.
    *   Format headings using Markdown hashes (`#`, `##`, `###`, etc.).
    *   Use the `<chunk_context>` to maintain a consistent and logical heading hierarchy.

4.  **Format Lists & Formatting:**
    *   Correctly format numbered and bulleted lists (e.g., `l.` -> `1.`).
    *   Apply standard Markdown for emphasis (`*italics*`, `**bold**`).
    *   Standardize common notes (e.g., `NOTE:` -> `*Note:*`).

5.  **Content Preservation:** Other than the artifacts you are instructed to remove in Rule #1, you must preserve the original text. Do not rewrite sentences or change the meaning of the original words and punctuation.

## OUTPUT INSTRUCTIONS

-   Your output MUST ONLY be the harmonized text from the `<chunk>`.
-   Do NOT include the `<chunk_context>` in your output.
-   Do NOT include any XML tags (like `<harmonized>`).
-   Do NOT add any commentary or explanation.

## Examples

<example>
<chunk_context>
This is the previous section discussing methodology.
</chunk_context>

<chunk>
RESULTS
The experiment yielded significant outcomes.  The data shows a clear trend.  However, there are anomalies in the third dataset.  Further analysis is required to explain these discrepancies.
</chunk>

<harmonized>
## Results

The experiment yielded significant outcomes. The data shows a clear trend. However, there are anomalies in the third dataset. Further analysis is required to explain these discrepancies.
</harmonized>
</example>

<example>
<chunk_context>
As discussed in the prior chapter
</chunk_context>

<chunk>
our methods were:

1  Prepare solution A
2  Mix with solution B
3  Observe reaction
NOTE:  Temperature must be maintained at 25°C
</chunk>

<harmonized>
our methods were:

1. Prepare solution A  
2. Mix with solution B  
3. Observe reaction  

*Note:* Temperature must be maintained at 25°C
</harmonized>
</example>

<example>
<chunk_context>
I deem this preferable to a confusion
</chunk_context>

<chunk>
between puissance and Libidinal Economy

the 'potentiality' Lyotard is keen to attack as the dawn of thought and other nihilistic products. I have, to guide the reader, inserted the French term in brackets following the word 'force'. Similarly, I have translated impouvoir as 'powerlessness' and impuissance as 'impotence'.
</chunk>

<logic>
The phrase "Libidinal Economy" is a running page header that interrupts the sentence. It breaks the grammatical flow between "between puissance and" and "the 'potentiality'". It must be identified as an OCR artifact and removed according to Rule #1. The rest of the text is then joined together.
</logic>

<harmonized>
between puissance and the 'potentiality' Lyotard is keen to attack as the dawn of thought and other nihilistic products. I have, to guide the reader, inserted the French term in brackets following the word 'force'. Similarly, I have translated impouvoir as 'powerlessness' and impuissance as 'impotence'.
</harmonized>
</example>

## Output the raw harmonized text below:
"""

def ocr_prompt() -> str:
    return f"""These are pages from a PDF document. Extract all text content (**ignoring headers at the top of the page and footers at the bottom**) while preserving the structure, but make sure things are clean and nice as well.

## Rules for Preserving Structure

1. Make sure each bibliography entry is separated by two line breaks.
2. Make sure to preserve the visual structure of the text, such as line breaks around headings and between table of contents entries.

For multi-column layouts:
1. Process columns from left to right
2. Clearly separate content from different columns

## Final Warning

Make sure to preserve ALL core content text! Do not change any words of that text. DO NOT USE CODE FENCES. Do not output anything but the text of the document, with no preamble.
"""
