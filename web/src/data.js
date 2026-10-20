// Unpacks the web bundle (see web/build.mjs) into the structures the game
// uses: the table data (as partout.PartoutFile), the PBMSG_FT font bytes,
// the sound files, the theme and the splash PNG.

import { loadPartout } from './partout.js';

const SOUND_SECONDS_PER_BYTE = 9.090909e-5; // FUN_0100901f: file size * 9.0909e-05 s

function slice(blob, range) {
  return range ? blob.subarray(range[0], range[0] + range[1]) : null;
}

// raw: the inflated bundle (u32 header length, JSON header, blob).
function unpack(raw) {
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const length = dv.getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(raw.subarray(4, 4 + length)));
  const blob = raw.subarray(4 + length);
  return { header, blob };
}

function loadGameData({ header, blob }) {
  const sounds = new Map();
  for (const [name, range] of Object.entries(header.sounds)) sounds.set(name, slice(blob, range));
  return {
    pf: loadPartout(header.manifest, blob),
    font: slice(blob, header.font),
    splash: slice(blob, header.splash),
    music: slice(blob, header.music),
    sounds,
  };
}

// The length the original reports for a sound file (0 when it's missing).
function soundSeconds(sounds, filename) {
  const bytes = sounds.get(filename.toLowerCase());
  return bytes ? bytes.length * SOUND_SECONDS_PER_BYTE : 0.0;
}

export { unpack, loadGameData, soundSeconds };
