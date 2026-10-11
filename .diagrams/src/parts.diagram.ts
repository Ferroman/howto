import { model } from '@diagc/core';

// The parts of howto, and what each hands to the next. cli.py calls the parts
// in this order and passes the results on. Along the arrows, only runner.py
// calls the next part itself: it drives capture.py through the Stage protocol,
// and the tests put FakeStage in its place. Where the three commands part
// ways, the label names the command. The helpers that several parts share
// (timeline.py, zoom.py, marks.py, tools.py) are left out.
//
// The parts are not put in a boundary. The layout places whatever is outside a
// boundary under it, so the speech command and the clips would leave narrate.py
// for the bottom row, and the picture would be half as wide again.
const m = model('parts', { name: 'The parts of howto' });
m.notation('c4');

const file = m.node('file', { type: 'c4-container-blob', name: 'Storyboard', technology: 'NAME.yaml' });

const part = (id: string, does: string) =>
  m.node(id, { type: 'c4-component', name: `${id}.py`, technology: does });

const storyboard = part('storyboard', 'reads and validates');
const voices = part('voices', 'a clip to clone, and its words');
const narrate = part('narrate', 'one kept clip per sentence');
const runner = part('runner', 'setup, steps and cleanup');
const capture = part('capture', 'the only Playwright import');
const probe = part('probe', 'the probe report');
const assemble = part('assemble', 'narration track and subtitles');
const animation = part('animation', 'the frames that differ');

const speech = m.node('speech', { type: 'c4-system-external', name: 'Speech command', technology: 'HOWTO_TTS' });
const clips = m.node('clips', { type: 'c4-container-blob', name: 'Spoken clips', technology: '~/.cache/howto/clips' });
const chromium = m.node('chromium', { type: 'c4-system-external', name: 'Chromium', technology: 'Playwright 1.63.0' });
const ffmpeg = m.node('ffmpeg', { type: 'c4-system-external', name: 'ffmpeg and ffprobe' });
const img2webp = m.node('img2webp', { type: 'c4-system-external', name: 'img2webp' });

const report = m.node('report', { type: 'c4-container-blob', name: 'Probe report', technology: 'text, on stdout' });
const video = m.node('video', { type: 'c4-container-blob', name: 'Narrated video', technology: 'NAME.mp4, .srt, .vtt' });
const picture = m.node('picture', { type: 'c4-container-blob', name: 'Animated picture', technology: 'NAME.gif, .webp' });

m.relate(file, storyboard, { kind: 'sync', label: 'Read as written' });

// Narration: render and narrate only. It comes first, so a speech failure
// stops a render before the browser starts.
m.relate(storyboard, narrate, { kind: 'sync', label: 'render: the sentences' });
m.relate(voices, narrate, { kind: 'sync', label: 'The voice, if named' });
m.relate(narrate, speech, { kind: 'sync', label: 'Speaks one sentence' });
m.relate(narrate, clips, { kind: 'writes', label: 'Keeps each clip' });

// The run in the browser: every command.
m.relate(storyboard, runner, { kind: 'sync', label: 'Setup, steps, cleanup' });
m.relate(narrate, runner, { kind: 'sync', label: 'Clips pace the steps' });
m.relate(runner, capture, { kind: 'sync', label: 'Actions, zoom, marks' });
m.relate(capture, chromium, { kind: 'sync', label: 'Performs and records' });

// After the run, one part for each command.
m.relate(runner, probe, { kind: 'sync', label: 'probe: steps, the page' });
m.relate(runner, assemble, { kind: 'sync', label: 'render: the timeline' });
m.relate(runner, animation, { kind: 'sync', label: 'animate: the crop' });

m.relate(probe, report, { kind: 'writes', label: 'One line per step' });
m.relate(assemble, ffmpeg, { kind: 'sync', label: 'Recording and narration' });
m.relate(assemble, video, { kind: 'writes', label: 'SRT and WebVTT' });
m.relate(animation, ffmpeg, { kind: 'sync', label: 'Frames, then the GIF' });
m.relate(animation, img2webp, { kind: 'sync', label: 'The same frames' });
m.relate(ffmpeg, video, { kind: 'writes', label: 'MP4' });
m.relate(ffmpeg, picture, { kind: 'writes', label: 'GIF' });
m.relate(img2webp, picture, { kind: 'writes', label: 'WebP' });

export default m;
