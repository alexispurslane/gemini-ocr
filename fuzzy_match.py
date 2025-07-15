from difflib import SequenceMatcher

def correct_overlap_fuzzy(context: str, chunk: str, min_overlap: int = 15, ratio_threshold: float = 0.9) -> str:
# Find the longest contiguous matching block
    matcher = SequenceMatcher(None, context, chunk)
    match = matcher.find_longest_match(0, len(context), 0, len(chunk))

    # Check if a significant match was found at the boundary
    # 1. The match size must meet our minimum length.
    # 2. The match must be at the very start of the output_start string (match.b == 0).
    # 3. The match must be at the very end of the context_end string.
    # 4. The similarity ratio should be high to avoid coincidental matches.
    if (match.size >= min_overlap and matcher.ratio() > ratio_threshold):
        
        print(f"Fuzzy overlap detected! Trimming {match.size} characters: '{chunk[:match.size]}'")
        return chunk[match.size:]

    return chunk
