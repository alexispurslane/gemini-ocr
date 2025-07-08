import itertools
import sys
import unicodedata

def filter_nonprintable(text):
    # Use characters of control category
    nonprintable = (ord(c) for c in (chr(i) for i in range(sys.maxunicode)) if unicodedata.category(c)=='Cc')
    # Use translate to remove all non-printable characters
    return text.translate({character:None for character in nonprintable})
