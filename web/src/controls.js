// Port of controls.py: the six key bindings (Windows virtual-key codes, as
// the original stores them), the Player Controls dialog's key list
// (the table at 0x1023508) and the browser key -> VK mapping (US layout,
// as the Python port assumes).

import { STRINGS } from './strings.js';

const OPTION_NAMES = [
  'Left Flippper key', 'Right Flipper key', 'Plunger key', 'Left Table Bump key', 'Right Table Bump key',
  'Bottom Table Bump key',
];
const LEFT_FLIPPER = 0;
const RIGHT_FLIPPER = 1;
const PLUNGER = 2;
const BUMP_LEFT = 3;
const BUMP_RIGHT = 4;
const BUMP_BOTTOM = 5;

function atoi(text) {
  let digits = '';
  for (const ch of text.trim()) {
    if (ch < '0' || ch > '9') break;
    digits += ch;
  }
  return digits ? parseInt(digits, 10) : 0;
}

const DEFAULT_KEYS = [0, 1, 2, 3, 4, 5].map((i) => atoi(STRINGS.get(159 + i)));

const KEY_TABLE = [
  0x8041, 0x005a, 0x8030, 0x0039, 0x402e, 0x402f, 0x403b, 0x4027, 0x405b, 0x405d,
  0x0020, 0x000d, 0x0009, 0x0014, 0x0025, 0x0027, 0x0026, 0x0028, 0x002d, 0x002e,
  0x0024, 0x0023, 0x0021, 0x0022, 0x0090, 0x0091, 0x0013, 0xffff,
];

const CHAR_VK = new Map([
  ['.', 0xbe], ['/', 0xbf], [';', 0xba], ["'", 0xde], ['[', 0xdb], [']', 0xdd], [',', 0xbc], ['-', 0xbd],
  ['=', 0xbb], ['`', 0xc0], ['\\', 0xdc],
]);
const VK_NAMES = new Map([
  [0x20, 'Space'], [0x0d, 'Enter'], [0x09, 'Tab'], [0x14, 'Caps Lock'], [0x25, 'Left'], [0x27, 'Right'],
  [0x26, 'Up'], [0x28, 'Down'], [0x2d, 'Insert'], [0x2e, 'Delete'], [0x24, 'Home'], [0x23, 'End'],
  [0x21, 'Page Up'], [0x22, 'Page Down'], [0x90, 'Num Lock'], [0x91, 'Scroll Lock'], [0x13, 'Pause'],
]);

function keyName(vk) {
  if ((vk >= 0x41 && vk <= 0x5a) || (vk >= 0x30 && vk <= 0x39)) return String.fromCharCode(vk);
  for (const [ch, code] of CHAR_VK) if (code === vk) return ch;
  return VK_NAMES.get(vk) || '';
}

function keyList() {
  const out = [];
  let k = 0;
  while (KEY_TABLE[k] !== 0xffff) {
    const value = KEY_TABLE[k];
    const low = value & 0xff;
    if (value & 0x4000) {
      const ch = String.fromCharCode(low);
      if (CHAR_VK.has(ch)) out.push([CHAR_VK.get(ch), ch]);
    } else {
      let last = low;
      if (value & 0x8000) {
        k += 1;
        last = KEY_TABLE[k];
      }
      for (let vk = low; vk <= last; vk++) {
        const name = keyName(vk);
        if (name) out.push([vk, name]);
      }
    }
    k += 1;
  }
  return out;
}

const CODE_TO_VK = new Map([
  ['Space', 0x20], ['Enter', 0x0d], ['Tab', 0x09], ['CapsLock', 0x14], ['ArrowLeft', 0x25], ['ArrowRight', 0x27],
  ['ArrowUp', 0x26], ['ArrowDown', 0x28], ['Insert', 0x2d], ['Delete', 0x2e], ['Home', 0x24], ['End', 0x23],
  ['PageUp', 0x21], ['PageDown', 0x22], ['NumLock', 0x90], ['ScrollLock', 0x91], ['Pause', 0x13],
  ['Backspace', 0x08], ['Escape', 0x1b], ['ShiftLeft', 0x10], ['ShiftRight', 0x10], ['ControlLeft', 0x11],
  ['ControlRight', 0x11], ['Period', 0xbe], ['Slash', 0xbf], ['Semicolon', 0xba], ['Quote', 0xde],
  ['BracketLeft', 0xdb], ['BracketRight', 0xdd], ['Comma', 0xbc], ['Minus', 0xbd], ['Equal', 0xbb],
  ['Backquote', 0xc0], ['Backslash', 0xdc], ['F1', 0x70], ['F2', 0x71], ['F3', 0x72], ['F4', 0x73], ['F8', 0x77],
  ['F11', 0x7a], ['F12', 0x7b], ['F15', 0x7e], ['NumpadEnter', 0x0d],
]);
const KEYPAD_NAV = new Map([
  ['Numpad4', 0x25], ['Numpad6', 0x27], ['Numpad8', 0x26], ['Numpad2', 0x28], ['Numpad0', 0x2d],
  ['NumpadDecimal', 0x2e], ['Numpad7', 0x24], ['Numpad1', 0x23], ['Numpad9', 0x21], ['Numpad3', 0x22],
]);
const KEYPAD_NUM = new Map([
  ['Numpad0', 0x60], ['Numpad1', 0x61], ['Numpad2', 0x62], ['Numpad3', 0x63], ['Numpad4', 0x64], ['Numpad6', 0x66],
  ['Numpad7', 0x67], ['Numpad8', 0x68], ['Numpad9', 0x69], ['NumpadDecimal', 0x6e],
]);

// The VK a WM_KEYDOWN would carry for a browser KeyboardEvent.code (0 = none).
function vkOfCode(code, numLock = false) {
  if (/^Key[A-Z]$/.test(code)) return code.charCodeAt(3);
  if (/^Digit[0-9]$/.test(code)) return code.charCodeAt(5);
  if (KEYPAD_NAV.has(code)) return numLock ? KEYPAD_NUM.get(code) : KEYPAD_NAV.get(code);
  return CODE_TO_VK.get(code) || 0;
}

export {
  OPTION_NAMES, LEFT_FLIPPER, RIGHT_FLIPPER, PLUNGER, BUMP_LEFT, BUMP_RIGHT, BUMP_BOTTOM, DEFAULT_KEYS, keyList,
  keyName, vkOfCode,
};
