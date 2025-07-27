import re
import json

def normalize(s, remove_whitespace=False):
    s = re.sub(r"  +", " ", s.translate(str.maketrans(",#", "  "))).strip().lower()
    if remove_whitespace:
        return re.sub(r"\s+|\n+", "", s)
    else:
        return s

def apply_table_of_contents(harmonized_text, headings):
    lines = harmonized_text.split("\n")
    for i, line in enumerate(lines):
        nl = normalize(line)
        ni, next_nonempty_line = next(((i+j, line) for j, line in enumerate(lines[i+1:i+4]) if len(line.strip()) > 1), (-1, None))
        first_char = next_nonempty_line.strip()[0] if next_nonempty_line != None else ""
        next_line_is_continuation = next_nonempty_line != None and not first_char.isupper() and not first_char.isnumeric()
        if len(line) == 0:
            continue
        else:
            line_already_merged = False
            for heading in headings:
                search = re.search(r"^([A-Za-z +0-9].*)[:.] (.*)$", heading["text"])
                last = heading["text"]
                if search:
                    last = max(reversed(search.groups()), key=len)
                nh = normalize(last.split(" by ")[0])
                if nl.endswith(nh) and not next_line_is_continuation:
                    print("Applying heading: ", heading)
                    without = nl.removesuffix(nh)
                    if len(without) > 0.90*len(nl):
                        lines[i] = line + "\n" + int(heading["level"])*"#" + " " + heading["text"]
                    else:
                        lines[i] = int(heading["level"])*"#" + " " + heading["text"]
                elif not line_already_merged and not nl.endswith(".") and next_line_is_continuation:
                    print("Merging lines", lines[i], "|", next_nonempty_line)
                    lines[i] = lines[i] + " " + next_nonempty_line
                    del lines[ni+1]
                    line_already_merged = True
            
    return "\n".join(lines)

def _test_toc():
     file = ""
     with open("conversions/libidinal-economy.intermediate.md", "r") as f: file = f.read()
     toc = []
     with open("conversions/libidinal-economy/toc.json", "r") as f: toc = json.loads(f.read())
     with open("foo", "w") as f: f.write(apply_table_of_contents(file, toc))
