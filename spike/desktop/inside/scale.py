"""Starts one app at a scale, reads where its controls are, and opens a second window for its title bar."""
app, scale, wm = sys.argv[1], int(sys.argv[2]), sys.argv[3]
desk(1920, 1080, scale=scale, wm=wm)
launch(APPS[app])
fill(first_window())
time.sleep(5)
nodes = walk()
shot(f"/out/{app}-{scale}.png")
frame = next((n["box"] for n in nodes if n["depth"] == 0 and n["showing"]), [0, 0, 0, 0])
# How many pixels of the monitor one unit of the tree is: 1, or the scale when the app counts in its own pixels.
unit = round(MONITOR[0] / frame[2]) if frame[2] else 0
controls = {}
for node in nodes:
    if node["showing"] and node["name"].strip() and node["depth"] > 0 and node["box"][2] > 0:
        # In pixels of the picture, which are the same at both scales.
        controls.setdefault(f'{node["role"]}|{node["name"]}', [value * unit / scale for value in node["box"]])
launch("xmessage -title Second 'A second window'")
wait(lambda: any(w["title"] == "Second" for w in windows()), 20, "the second window")
time.sleep(1)
second = next(w for w in windows() if w["title"] == "Second")
extents = re.findall(r"\d+", sh("xprop", "-id", second["id"], "_NET_FRAME_EXTENTS").stdout.split("=")[-1])
shot(f"/out/{app}-{scale}-second.png")
print(json.dumps({
    "app": app, "scale": scale, "wm": wm, "unit": unit, "frame": frame,
    "title_bar": int(extents[2]) if len(extents) == 4 else 0, "controls": controls,
}))
