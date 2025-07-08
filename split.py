from typing import Iterator

def split_overlapping(text: str, chunk_size: int, overlap: int) -> Iterator[str]:    
    step = chunk_size - overlap
    words = text.split(" ")
    
    for i in range(0, len(words), step):
        yield " ".join(words[i:i + chunk_size])
