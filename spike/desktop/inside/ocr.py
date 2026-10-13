"""Reads the screen of one app with tesseract, and compares the words with the names in its tree."""
from PIL import Image

app = sys.argv[1]
desk()
launch(APPS[app])
fill(first_window())
time.sleep(5)
nodes = walk()
shot("/tmp/shot.png")
# The words a viewer can read: of small named elements, letters only, three or more.
wanted = []
for node in nodes:
    x, y, w, h = node["box"]
    if node["showing"] and node["depth"] > 0 and 0 < h <= 60 and w > 0:
        for word in re.findall(r"[A-Za-z]{3,}", node["name"]):
            wanted.append((word.casefold(), (x - 4, y - 4, x + w + 4, y + h + 4)))
results = []
for enlarge in (1, 2):
    source = "/tmp/shot.png"
    if enlarge > 1:
        picture = Image.open(source)
        picture.resize((picture.width * enlarge, picture.height * enlarge), Image.LANCZOS).save("/tmp/big.png")
        source = "/tmp/big.png"
    for mode in ("11", "6"):
        began = time.monotonic()
        table = sh("tesseract", source, "stdout", "--psm", mode, "-l", "eng", "tsv").stdout
        seconds = time.monotonic() - began
        read = []
        for row in table.splitlines()[1:]:
            cells = row.split("\t")
            if len(cells) == 12 and cells[0] == "5" and cells[11].strip():
                left, top, width, height = (int(cells[i]) / enlarge for i in (6, 7, 8, 9))
                for word in re.findall(r"[A-Za-z]{3,}", cells[11]):
                    read.append((word.casefold(), left + width / 2, top + height / 2))
        hits = sum(
            1 for word, (x0, y0, x1, y1) in wanted
            if any(heard == word and x0 <= x <= x1 and y0 <= y <= y1 for heard, x, y in read)
        )
        results.append({"enlarge": enlarge, "psm": mode, "seconds": round(seconds, 2), "wanted": len(wanted), "read": hits})
print(json.dumps({"app": app, "results": results}))
