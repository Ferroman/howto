"""Records the bare monitor while it turns white at known times."""
width, height = int(sys.argv[1]), int(sys.argv[2])
desk(width, height, wm=None)
sh("xsetroot", "-solid", "black")
command = [
    "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-y",
    "-f", "x11grab", "-draw_mouse", "1", "-framerate", "25", "-video_size", f"{width}x{height}", "-i", ":99",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", "-g", "25", "/out/grab.mkv",
]
wall, steady = time.time(), time.monotonic()
recorder = subprocess.Popen(command, stderr=subprocess.PIPE, text=True)
said, start = [], None
for line in recorder.stderr:
    said.append(line)
    found = re.search(r"start: (\d+\.\d+)", line)
    if found:
        start = float(found.group(1))
        break
if start is None:
    raise SystemExit("ffmpeg did not say when it started:\n" + "".join(said))
threading.Thread(target=lambda: said.extend(recorder.stderr), daemon=True).start()
# ffmpeg stamps a frame with the wall clock in some releases and with the
# steady clock in others. A wall-clock time is far larger than any uptime.
clock = "wall" if start > 3e8 else "steady"
first = start - (wall - steady) if clock == "wall" else start
flashes = []
for second in (2, 5, 8, 11, 14):
    time.sleep(max(0.0, first + second - time.monotonic()))
    flashes.append(time.monotonic() - first)
    sh("xsetroot", "-solid", "white")
    time.sleep(0.4)
    sh("xsetroot", "-solid", "black")
sh("xdotool", "mousemove", "200", "200")
time.sleep(2)
recorder.send_signal(signal.SIGINT)
recorder.wait(timeout=60)
print(json.dumps({
    "size": [width, height], "clock": clock, "flashes": flashes,
    "load": os.getloadavg()[0], "log": "".join(said)[-800:],
}))
