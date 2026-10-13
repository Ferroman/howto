"""Reads the tree of one app twice, measures the time, and draws the boxes on a screenshot."""
from PIL import Image, ImageDraw

app = sys.argv[1]
desk()
launch(APPS[app])
fill(first_window())
time.sleep(5)  # an Electron app builds its tree after its window
began = time.monotonic()
nodes = walk()
seconds = time.monotonic() - began
shot(f"/out/{app}.png")
time.sleep(3)
settled = len(walk()) == len(nodes)

named = [n for n in nodes if n["showing"] and n["name"].strip() and n["box"][2] > 0 and n["depth"] > 0]
picture = Image.open(f"/out/{app}.png").convert("RGB")
pen = ImageDraw.Draw(picture)
for node in named[:80]:
    x, y, w, h = node["box"]
    pen.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 0, 0))
picture.save(f"/out/{app}-boxes.png")
frames = [n for n in nodes if n["depth"] == 0 and n["showing"]]
print(json.dumps({
    "app": app,
    "toolkit": nodes[0]["toolkit"] if nodes else "",
    "nodes": len(nodes),
    "named": len(named),
    "seconds": round(seconds, 2),
    "settled": settled,
    "frame": frames[0]["box"] if frames else None,
    "roles": sorted({n["role"] for n in named}),
    "sample": [[n["role"], n["name"], n["box"]] for n in named[:15]],
}))
