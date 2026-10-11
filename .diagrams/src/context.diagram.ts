import { model } from '@diagc/core';

// What howto works with. Everything inside the boundary runs on the user's own
// machine; the agent and the app that is filmed can be anywhere. howto itself
// calls no model: the agent is the only part that thinks.
const m = model('context', { name: 'howto and what it works with' });
m.notation('c4');

const person = m.node('person', { type: 'c4-person', name: 'You' });
const agent = m.node('agent', {
  type: 'c4-system-external',
  name: 'AI coding agent',
  technology: 'optional, follows skill/SKILL.md',
});
const app = m.node('app', { type: 'c4-system-external', name: 'Your web app' });

const machine = m.node('machine', { type: 'c4-enterprise-boundary', name: 'Your machine' });

const storyboard = m.node('storyboard', {
  type: 'c4-container-blob',
  name: 'Storyboard',
  technology: 'NAME.yaml',
});
const howto = m.node('howto', { type: 'c4-system', name: 'howto' });
const browser = m.node('browser', {
  type: 'c4-system-external',
  name: 'Chromium',
  technology: "Playwright's own",
});
const speech = m.node('speech', {
  type: 'c4-system-external',
  name: 'Speech command',
  technology: 'HOWTO_TTS',
});
const ffmpeg = m.node('ffmpeg', { type: 'c4-system-external', name: 'ffmpeg and ffprobe' });
const img2webp = m.node('img2webp', { type: 'c4-system-external', name: 'img2webp' });
const video = m.node('video', {
  type: 'c4-container-blob',
  name: 'Narrated video',
  technology: 'NAME.mp4, .srt, .vtt',
});
const picture = m.node('picture', {
  type: 'c4-container-blob',
  name: 'Animated picture',
  technology: 'NAME.gif, .webp',
});

machine.contains(storyboard, howto, browser, speech, ffmpeg, img2webp, video, picture);

m.relate(person, agent, { kind: 'sync', label: 'Asks in one sentence' });
m.relate(person, howto, { kind: 'sync', label: 'Signs in once: login' });
m.relate(agent, storyboard, { kind: 'writes', label: 'Writes and corrects' });
m.relate(agent, howto, { kind: 'sync', label: 'Probes, then renders' });
m.relate(storyboard, howto, { kind: 'sync', label: 'The only input' });

m.relate(howto, browser, { kind: 'sync', label: 'Performs and records' });
m.relate(browser, app, { kind: 'sync', label: 'Clicks and types' });
m.relate(howto, speech, { kind: 'sync', label: 'One WAV per sentence' });
m.relate(howto, ffmpeg, { kind: 'sync', label: 'Joins picture and sound' });
m.relate(howto, img2webp, { kind: 'sync', label: 'Encodes the WebP' });
m.relate(ffmpeg, video, { kind: 'writes', label: 'render' });
m.relate(ffmpeg, picture, { kind: 'writes', label: 'animate: GIF' });
m.relate(img2webp, picture, { kind: 'writes', label: 'animate: WebP' });

export default m;
