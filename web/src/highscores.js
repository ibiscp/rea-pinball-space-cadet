// Port of highscores.py: the 5-entry high-score table (FUN_01004c3c /
// FUN_01004c60 / FUN_01004c8d / FUN_01004f99) and the options, with the
// same value names and "Verification" checksum the original keeps in the
// registry -- stored here in the browser's localStorage (or an in-memory
// store when there is none, e.g. under node).

const SCORES_SECTION = 'SpaceCadet';
const OPTIONS_SECTION = 'Pinball';
const CLEARED = -999;
const ENTRIES = 5;
const NAME_LIMIT = 31;
const STORAGE_KEY = 'space-cadet-pinball-settings';

const memory = {};

function storage() {
  try {
    if (typeof localStorage !== 'undefined') return localStorage;
  } catch (err) {
    // storage disabled (e.g. a file:// iframe in some browsers)
  }
  return null;
}

function readConfig() {
  const store = storage();
  try {
    const text = store ? store.getItem(STORAGE_KEY) : memory[STORAGE_KEY];
    return text ? JSON.parse(text) : {};
  } catch (err) {
    return {};
  }
}

function writeConfig(config) {
  const text = JSON.stringify(config);
  const store = storage();
  try {
    if (store) store.setItem(STORAGE_KEY, text);
    else memory[STORAGE_KEY] = text;
  } catch (err) {
    memory[STORAGE_KEY] = text;
  }
}

function resetMemoryStore() {
  delete memory[STORAGE_KEY];
}

class Entry {
  constructor(name = '', score = CLEARED) {
    this.name = name;
    this.score = score;
  }
}

function signedChar(ch) {
  const value = ch.charCodeAt(0) & 0xff;
  return value >= 128 ? value - 256 : value;
}

function checksum(entries) {
  let total = 0;
  for (const entry of entries) {
    for (const ch of entry.name) total += signedChar(ch);
    total += entry.score;
  }
  return total;
}

function cdiv(a, b) {
  return Math.trunc(a / b);
}

function cmod(a, b) {
  return a - cdiv(a, b) * b;
}

function pad3(n) {
  return String(n).padStart(3, '0');
}

// FUN_01004f99.
function formatScore(score, separator = ',') {
  if (score === CLEARED) return '';
  const billions = cdiv(score, 1000000000);
  const millions = cdiv(cmod(score, 1000000000), 1000000);
  const thousands = cdiv(cmod(score, 1000000), 1000);
  const units = cmod(score, 1000);
  if (billions >= 1) return `${billions}${separator}${pad3(millions)}${separator}${pad3(thousands)}${separator}${pad3(units)}`;
  if (millions >= 1) return `${millions}${separator}${pad3(thousands)}${separator}${pad3(units)}`;
  if (thousands >= 1) return `${thousands}${separator}${pad3(units)}`;
  return String(score);
}

function atol(text) {
  text = String(text ?? '').trim();
  let digits = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if ((ch >= '0' && ch <= '9') || (i === 0 && (ch === '+' || ch === '-'))) digits += ch;
    else break;
  }
  const v = parseInt(digits, 10);
  return Number.isNaN(v) ? 0 : v;
}

class HighScores {
  constructor() {
    this.entries = Array.from({ length: ENTRIES }, () => new Entry());
  }

  clear() {
    this.entries = Array.from({ length: ENTRIES }, () => new Entry());
  }

  score(rank) {
    return this.entries[rank].score;
  }

  rank(score) {
    if (score > 0) {
      for (let i = 0; i < this.entries.length; i++) if (this.entries[i].score < score) return i;
    }
    return -1;
  }

  insert(score, name, rank) {
    if (rank < 0) return rank;
    if (rank < ENTRIES) {
      this.entries.splice(rank, 0, new Entry());
      this.entries.length = ENTRIES;
    }
    const entry = this.entries[Math.min(rank, ENTRIES - 1)];
    entry.score = score;
    entry.name = name.slice(0, NAME_LIMIT);
    return rank;
  }

  load() {
    this.clear();
    const config = readConfig();
    const values = config[SCORES_SECTION] || {};
    this.entries.forEach((entry, i) => {
      entry.name = String(values[`${i}.Name`] ?? '').slice(0, NAME_LIMIT);
      entry.score = atol(values[`${i}.Score`] ?? '');
    });
    if (String(values.Verification ?? '') !== String(checksum(this.entries))) this.clear();
  }

  save() {
    const config = readConfig();
    const section = config[SCORES_SECTION] || {};
    this.entries.forEach((entry, i) => {
      section[`${i}.Name`] = entry.name;
      section[`${i}.Score`] = String(entry.score);
    });
    section.Verification = String(checksum(this.entries));
    config[SCORES_SECTION] = section;
    writeConfig(config);
  }
}

function loadOption(name, fallback) {
  const config = readConfig();
  const section = config[OPTIONS_SECTION];
  if (section && name in section) return atol(section[name]);
  return fallback;
}

function saveOptions(options) {
  const config = readConfig();
  const section = config[OPTIONS_SECTION] || {};
  for (const [name, value] of Object.entries(options)) section[name] = String(value);
  config[OPTIONS_SECTION] = section;
  writeConfig(config);
}

export { HighScores, formatScore, loadOption, saveOptions, resetMemoryStore, ENTRIES, NAME_LIMIT, CLEARED };
