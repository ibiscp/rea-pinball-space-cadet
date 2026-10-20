// Port of missions.py: the mission state machine (FUN_01011bb5 and its 33
// state handlers). Game extends Missions.

import { STRINGS } from './strings.js';

const MISSION_NAMES = new Map([
  [2, 60], [3, 61], [4, 62], [5, 63], [6, 64], [7, 65], [8, 66], [9, 67], [10, 68],
  [11, 69], [12, 70], [13, 71], [14, 72], [15, 73], [16, 74], [17, 75], [18, 76],
]);
const ACCEPT_POINTS = new Map();
for (let i = 2; i < 6; i++) ACCEPT_POINTS.set(i, 10000);
for (let i = 6; i < 15; i++) ACCEPT_POINTS.set(i, 20000);
for (let i = 15; i < 19; i++) ACCEPT_POINTS.set(i, 30000);
const RANKS = [84, 85, 86, 87, 88, 89, 90, 91, 92];
const SELECTION = new Map([
  [1, { 1: 3, 2: 4, 3: 2, 4: 5 }],
  [2, { 1: 9, 2: 0xb, 3: 10, 4: 0x10 }],
  [3, { 1: 9, 2: 0xb, 3: 10, 4: 0x10 }],
  [4, { 1: 6, 2: 8, 3: 7, 4: 0xf }],
  [5, { 1: 6, 2: 8, 3: 7, 4: 0xf }],
  [6, { 1: 0xc, 2: 0xd, 3: 0xe, 4: 0x11 }],
  [7, { 1: 0xc, 2: 0xd, 3: 0xe, 4: 0x11 }],
  [8, { 1: 0xf, 2: 0x10, 3: 0x11, 4: 0x12 }],
  [9, { 1: 0xf, 2: 0x10, 3: 0x11, 4: 0x12 }],
]);

const ATTACK_BUMPERS = ['a_bump1', 'a_bump2', 'a_bump3', 'a_bump4'];
const BANK_TARGETS = ['a_targ1', 'a_targ2', 'a_targ3', 'a_targ6', 'a_targ5', 'a_targ4', 'a_targ9', 'a_targ8', 'a_targ7'];
const DROP_TARGETS = [];
for (let i = 10; i < 23; i++) DROP_TARGETS.push(`a_targ${i}`);
const LANE_ROLLOVERS = ['a_roll3', 'a_roll2', 'a_roll1', 'a_roll112', 'a_roll111', 'a_roll110', 'a_roll4', 'a_roll8',
  'a_roll6', 'a_roll7', 'a_roll5'];
const REBOUNDS = ['v_rebo1', 'v_rebo2', 'v_rebo3', 'v_rebo4'];
const FLAGS = ['a_flag1', 'a_flag2'];
const TREKS = ['l_trek_lights', 'r_trek_lights'];

function nameOf(obj) {
  return obj && obj.name !== undefined ? obj.name : '';
}

class Missions {
  _missionText(string, args = [], seconds = -1.0) {
    this.text('mission', string, seconds, ...args);
  }

  _goalHint(show, hide) {
    for (const light of hide) if (this.lit(light)) this.msg(light, 0x14);
    if (!this.lit(show)) this.msg(show, 7);
  }

  _rankProgress(steps) {
    this.msg('lite16', 0x13);
    const outer = this.objects.get('outer_circle');
    for (let i = 0; i < steps; i++) outer.message(0x29, 2.0);
    const lit = outer.message(0x25);
    const total = outer.message(0x26);
    if (lit === total) {
      outer.message(0x10, 5.0);
      const middle = this.objects.get('middle_circle');
      middle.message(0x22);
      const rank = middle.message(0x25);
      if (rank < 9) {
        middle.message(0x29, 5.0);
        this._missionText(83, [STRINGS.get(RANKS[rank])], 8.0);
        this.play('soundwave10');
      }
      return 1;
    }
    if (Math.floor((total * 3) / 4) <= lit) this.msg('middle_circle', 0x1b, -1.0);
    return 0;
  }

  _complete(lights, doneText, award, rank, doneBox = 'mission') {
    for (const light of lights) this.msg(light, 0x14);
    this.setData('lite198', 1);
    this._mission(0x42, null);
    this.text(doneBox, doneText, 4.0);
    const added = this.award(award);
    if (this._rankProgress(rank) === 0) {
      this._missionText(78, [added], 8.0);
      this.play('soundwave9');
    }
  }

  _count(code, obj, members, count, lights, progress, finish, setup = null) {
    if (code === 0x3f) {
      if (!members.includes(nameOf(obj))) return;
      const left = this.data('lite56') - 1;
      this.setData('lite56', left);
      if (left === 0) finish();
      else this._mission(0x43, obj);
      return;
    }
    if (code === 0x42) {
      this.setData('lite56', count);
      if (setup !== null) setup();
      for (const light of lights) this.msg(light, 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(progress, [this.data('lite56')]);
  }

  _resetBankTargets() {
    for (const name of BANK_TARGETS) {
      this.setData(name, 0);
      this.msg(name, 0x32);
    }
  }

  _startTreks() {
    for (const group of TREKS) {
      this.msg(group, 0x14);
      this.msg(group, 0x20, 0.2);
      this.msg(group, 0x1a, 0.2);
    }
  }

  // FUN_01011bb5.
  _mission(code, obj) {
    const state = this.data('lite198');
    if (code === 0x2f) {
      if (obj === this.objects.get('fuel_bargraph') && state > 1) {
        for (const group of TREKS) {
          this.msg(group, 0x22);
          this.msg(group, 0x14);
        }
        this._missionText(109, [], 4.0);
        this.setData('lite198', 1);
        this._mission(0x42, null);
      }
    } else if (code === 0x3c) {
      if (obj === this.objects.get('fuel_bargraph') && state !== 0) {
        if (this.msg('fuel_bargraph', 0x25) === 1) this._missionText(116, [], 4.0);
      } else if (nameOf(obj) === 'mission_text_box') {
        code = 0x43;
      }
    } else if (code === 0x3f1) {
      code = 0x43;
    }
    const handler = this._missionHandler(state);
    if (handler === null) {
      this.setData('lite198', 1);
      this._mission(0x42, null);
      return;
    }
    handler.call(this, code, obj);
  }

  _missionHandler(state) {
    const handlers = {
      0: this._mNone, 1: this._mSelect, 2: this._mTargetPractice, 3: this._mLaunchTraining,
      4: this._mReentryTraining, 5: this._mScience, 6: this._mStrayComet, 7: this._mBlackHole,
      8: this._mSpaceRadiation, 9: this._mBugHunt, 10: this._mAlienMenace, 11: this._mRescue,
      12: this._mSatellite, 13: this._mRecon, 14: this._mDoomsday, 15: this._mCosmicPlague,
      16: this._mSecret, 17: this._mTimeWarp, 18: this._mMaelstrom, 0x14: this._mAlienMenace2,
      0x15: this._mCosmicPlague2, 0x16: this._mSecret2, 0x17: this._mSecret3,
      0x18: this._mTimeWarp2, 0x19: this._mMaelstrom2, 0x1a: this._mMaelstrom3,
      0x1b: this._mMaelstrom4, 0x1c: this._mMaelstrom5, 0x1d: this._mMaelstrom6,
      0x1e: this._mMaelstrom7, 0x1f: this._mMaelstrom8, 0x20: this._mGameOver,
    };
    return Object.prototype.hasOwnProperty.call(handlers, state) ? handlers[state] : null;
  }

  _mNone(code, obj) {
    if (code === 0x3f) {
      if (nameOf(obj) === 's_onewy4' || nameOf(obj) === 's_onewy10') {
        this.setData('lite198', 1);
        this._mission(0x42, null);
      }
    } else if (code === 0x42) {
      this.clearText('mission');
    } else if (code === 0x43) {
      this._missionText(50);
    }
  }

  _mSelect(code, obj) {
    if (code === 0x2d || code === 0x2f) {
      if (obj !== this.objects.get('fuel_bargraph')) return;
    } else if (code !== 0x3f) {
      if (code === 0x42) {
        this.msg('lite198', 0x14);
        this.msg('outer_circle', 0x22);
        this.msg('ramp_tgt_lights', 0x14);
        this.setData('lite56', 0);
        this.setData('lite101', 0);
        for (const group of TREKS) {
          this.msg(group, 0x22);
          this.msg(group, 0x14);
        }
        this.msg('goal_lights', 0x14);
      } else if (code !== 0x43) {
        return;
      }
      if (this.msg('fuel_bargraph', 0x25) === 0) {
        this._missionText(105);
        this._goalHint('lite318', ['lite317', 'lite319']);
      } else if (!this.lit('lite56')) {
        this._missionText(104);
        this._goalHint('lite319', ['lite317', 'lite318']);
      } else {
        const id = MISSION_NAMES.has(this.data('lite56')) ? MISSION_NAMES.get(this.data('lite56')) : 60;
        this._missionText(106, [STRINGS.get(id)]);
        this._goalHint('lite317', ['lite318', 'lite319']);
      }
      return;
    } else {
      const picks = { a_targ13: 1, a_targ14: 2, a_targ15: 3 };
      let pick = picks[nameOf(obj)] ?? 0;
      if (pick === 0) {
        if (nameOf(obj) === 'ramp' && this.lit('lite56') && this.msg('fuel_bargraph', 0x25) !== 0) {
          this.msg('lite56', 0x14);
          this.msg('lite198', 0x13);
          this.msg('outer_circle', 0x1a, -1.0);
          for (const light of ['lite317', 'lite318', 'lite319']) if (this.lit(light)) this.msg(light, 0x14);
          const mission = this.data('lite56');
          this.setData('lite198', mission);
          this._mission(0x42, null);
          const added = this.award(ACCEPT_POINTS.has(mission) ? ACCEPT_POINTS.get(mission) : 0);
          this._missionText(77, [added], 4.0);
        }
        return;
      }
      if (this.data('lite101') === 7) {
        this.setData('lite101', 0);
        pick = 4;
      }
      const choices = SELECTION.get(this.msg('middle_circle', 0x25));
      if (choices === undefined) return;
      this.setData('lite56', choices[pick]);
      this.msg('lite56', 0xf, 2.0);
      this.msg('lite198', 4);
    }
    this._mission(0x43, obj);
  }

  _mTargetPractice(code, obj) {
    this._count(code, obj, ATTACK_BUMPERS, 8, ['lite308', 'lite311'], 107,
      () => this._complete(['lite308', 'lite311'], 108, 500000, 6));
  }

  _mLaunchTraining(code, obj) {
    this._count(code, obj, ['ramp'], 3, ['lite317'], 110, () => this._complete(['lite317'], 111, 500000, 6));
  }

  _mReentryTraining(code, obj) {
    this._count(code, obj, ['a_roll3', 'a_roll2', 'a_roll1'], 3, ['lite307'], 112,
      () => this._complete(['lite307'], 113, 500000, 6), () => this._startTreks());
  }

  _mScience(code, obj) {
    const lights = ['lite303', 'lite309', 'lite315'];
    this._count(code, obj, BANK_TARGETS, 9, lights, 114, () => this._complete(lights, 115, 750000, 9),
      () => this._resetBankTargets());
  }

  _mStrayComet(code, obj) {
    const name = nameOf(obj);
    if (code === 0x3f) {
      if (['a_targ19', 'a_targ20', 'a_targ21'].includes(name)) {
        if (this.data('lite107') === 7) {
          this.msg('lite306', 0x14);
          this.msg('lite304', 7);
          this.setData('lite107', 0xf);
          this._mission(0x43, obj);
        }
      } else if (name === 'a_kout2' && this.data('lite107') === 0xf) {
        this._complete(['lite304'], 119, 1000000, 8);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('bpr_solotgt_lights', 0x14);
      this.setData('lite107', 0);
      this.msg('lite306', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(this.data('lite107') === 0xf ? 118 : 117);
  }

  _mBlackHole(code, obj) {
    const bumper = this.bumpers.get('a_bump5');
    if (code === 0xb) {
      if (nameOf(obj) === 'a_bump5') this._mission(0x43, obj);
      return;
    }
    if (code === 0x3f) {
      if (nameOf(obj) === 'a_kout3' && bumper !== undefined && bumper.level !== 0) {
        for (const light of ['lite316', 'lite314']) if (this.lit(light)) this.msg(light, 0x14);
        this._complete([], 124, 1000000, 8);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('launch_bumpers', 0xb, 0.0);
    } else if (code !== 0x43) {
      return;
    }
    if (bumper === undefined || bumper.level === 0) {
      this._missionText(122);
      this._goalHint('lite316', ['lite314']);
    } else {
      this._missionText(123);
      this._goalHint('lite314', ['lite316']);
    }
  }

  _mSpaceRadiation(code, obj) {
    const name = nameOf(obj);
    if (code === 0x3f) {
      if (['a_targ16', 'a_targ17', 'a_targ18'].includes(name)) {
        if (this.data('lite104') === 7) {
          this.setData('lite104', 0xf);
          this.msg('bsink_arrow_lights', 7);
          this.msg('lite313', 0x14);
          this._mission(0x43, obj);
          this._advanceWormhole(1);
        }
      } else if (['v_sink1', 'v_sink2', 'v_sink3'].includes(name) && this.data('lite104') === 0xf) {
        this._complete([], 121, 1000000, 8);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('lchute_tgt_lights', 0x14);
      this.setData('lite104', 0);
      this.msg('lite313', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(this.data('lite104') === 0xf ? 120 : 176);
  }

  _mBugHunt(code, obj) {
    const lights = ['lite306', 'lite308', 'lite310', 'lite313', 'lite319'];
    const setup = () => {
      this._resetBankTargets();
      for (const group of ['top_circle_tgt_lights', 'ramp_tgt_lights', 'lchute_tgt_lights', 'bpr_solotgt_lights']) {
        this.msg(group, 0x14);
      }
    };
    this._count(code, obj, [...BANK_TARGETS, ...DROP_TARGETS], 15, lights, 125,
      () => this._complete(lights, 126, 750000, 7), setup);
  }

  _mAlienMenace(code, obj) {
    if (code === 0xb) {
      const bumper = this.bumpers.get('a_bump1');
      if (nameOf(obj) === 'a_bump1' && bumper !== undefined && bumper.level !== 0) {
        this.msg('lite307', 0x14);
        this.setData('lite198', 0x14);
        this._mission(0x42, null);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('attack_bumpers', 0xb, 0.0);
      this._startTreks();
      this.msg('lite307', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(175);
  }

  _mAlienMenace2(code, obj) {
    const lights = ['lite308', 'lite311'];
    const setup = () => {
      for (const group of TREKS) {
        this.msg(group, 0x22);
        this.msg(group, 0x14);
      }
    };
    this._count(code, obj, ATTACK_BUMPERS, 8, lights, 107, () => this._complete(lights, 130, 750000, 7), setup);
  }

  _mRescue(code, obj) {
    const name = nameOf(obj);
    if (code === 0x3f) {
      if (['a_targ1', 'a_targ2', 'a_targ3'].includes(name)) {
        this._mission(0x43, obj);
      } else if (name === 'a_kout2' && this.lit('lite20')) {
        const left = this.data('lite56') - 1;
        this.setData('lite56', left);
        if (left === 0) {
          for (const light of ['lite303', 'lite304']) if (this.lit(light)) this.msg(light, 0x14);
          this._complete([], 129, 750000, 7);
        } else {
          this._mission(0x43, obj);
        }
      }
      return;
    }
    if (code === 0x42) {
      this.msg('lite20', 0x14);
      this.msg('lite19', 0x14);
      this.setData('lite56', 1);
    } else if (code !== 0x43) {
      return;
    }
    if (!this.lit('lite20')) {
      this._missionText(127);
      this._goalHint('lite303', ['lite304']);
    } else {
      this._missionText(128);
      this._goalHint('lite304', ['lite303']);
    }
  }

  _mSatellite(code, obj) {
    this._count(code, obj, ['a_bump4'], 3, ['lite308'], 132, () => this._complete(['lite308'], 133, 1250000, 9));
  }

  _mRecon(code, obj) {
    const lights = ['lite301', 'lite302', 'lite307', 'lite316', 'lite320', 'lite321'];
    this._count(code, obj, LANE_ROLLOVERS, 15, lights, 134, () => this._complete(lights, 136, 1250000, 9));
  }

  _mDoomsday(code, obj) {
    const lights = ['lite301', 'lite320'];
    this._count(code, obj, ['a_roll4', 'a_roll8'], 3, lights, 137, () => this._complete(lights, 138, 1250000, 9));
  }

  _mCosmicPlague(code, obj) {
    const lights = ['lite305', 'lite312'];
    const finish = () => {
      for (const light of lights) this.msg(light, 0x14);
      this.setData('lite198', 0x15);
      this._mission(0x42, null);
      this.msg('lite20', 0x14);
      this.msg('lite19', 0x14);
    };
    const setup = () => {
      this.msg('lite20', 0x13);
      this.msg('lite19', 0x13);
    };
    this._count(code, obj, FLAGS, 75, lights, 139, finish, setup);
  }

  _mCosmicPlague2(code, obj) {
    if (code === 0x3f) {
      if (nameOf(obj) === 'a_roll9') this._complete(['lite310'], 141, 1750000, 11);
      return;
    }
    if (code === 0x42) this.msg('lite310', 7);
    else if (code !== 0x43) return;
    this._missionText(140);
  }

  _mSecret(code, obj) {
    if (code === 0x3f) {
      if (nameOf(obj) === 'v_sink3') {
        this.setData('lite198', 0x16);
        this._mission(0x42, null);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('worm_hole_lights', 0x14);
      this.msg('bsink_arrow_lights', 0x14);
      this.msg('bsink_arrow_lights', 0x17, 0.0);
      this.msg('lite110', 0x14);
      this.msg('lite7', 0x13);
      this.msg('lite3', 0xb, 0.0);
      this.msg('lite3', 0x13);
      this.msg('lite3', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(142);
  }

  _mSecret2(code, obj) {
    if (code === 0x3f) {
      if (nameOf(obj) === 'v_sink1') {
        this.setData('lite198', 0x17);
        this._mission(0x42, null);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('lite5', 0x13);
      this.msg('lite4', 0xb, 2.0);
      this.msg('lite4', 0x13);
      this.msg('lite4', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(143);
  }

  _mSecret3(code, obj) {
    if (code === 0x3f) {
      if (nameOf(obj) === 'v_sink2') {
        this.setData('lite198', 1);
        this._mission(0x42, null);
        this._missionText(145, [], 4.0);
        const added = this.award(1500000);
        if (this._rankProgress(10) === 0) {
          this._missionText(78, [added], 8.0);
          this.play('soundwave9');
        }
      }
      return;
    }
    if (code === 0x42) {
      this.msg('lite6', 0x13);
      this.msg('lite2', 0xb, 1.0);
      this.msg('lite2', 0x13);
      this.msg('lite2', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(144);
  }

  _mTimeWarp(code, obj) {
    const lights = ['lite300', 'lite322'];
    const finish = () => {
      for (const light of lights) this.msg(light, 0x14);
      this.setData('lite198', 0x18);
      this._mission(0x42, null);
    };
    this._count(code, obj, REBOUNDS, 25, lights, 146, finish);
  }

  _mTimeWarp2(code, obj) {
    const name = nameOf(obj);
    if (code === 0x3f) {
      if (name === 'a_kout2') {
        this._missionText(47, [], 4.0);
        const middle = this.objects.get('middle_circle');
        if (middle.message(0x25) > 1) {
          middle.message(0x21, 5.0);
          const rank = middle.message(0x25);
          this._missionText(174, [STRINGS.get(RANKS[rank - 1])], 8.0);
        }
      } else if (name === 'ramp') {
        this._missionText(46, [], 4.0);
        const middle = this.objects.get('middle_circle');
        let message = null;
        if (middle.message(0x25) < 9) {
          const rank = middle.message(0x25);
          middle.message(0x29, 5.0);
          message = STRINGS.get(173).replaceAll('%s', STRINGS.get(RANKS[rank]));
        }
        if (this._rankProgress(12) === 0 && message !== null) {
          this._missionText(message, [], 8.0);
          this.play('soundwave10');
        }
      } else {
        return;
      }
      this.award(2000000);
      for (const light of ['lite55', 'lite26', 'lite304', 'lite317']) this.msg(light, 0x14);
      this.setData('lite198', 1);
      this._mission(0x42, null);
      return;
    }
    if (code === 0x42) {
      this.msg('lite55', 7, -1.0);
      this.msg('lite26', 7, -1.0);
      this.msg('lite304', 7);
      this.msg('lite317', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(147);
  }

  _stage(code, obj, members, count, lights, progress, nextState) {
    const finish = () => {
      for (const light of lights) this.msg(light, 0x14);
      this.setData('lite198', nextState);
      this._mission(0x42, null);
    };
    this._count(code, obj, members, count, lights, progress, finish);
  }

  _mMaelstrom(code, obj) {
    this._stage(code, obj, BANK_TARGETS, 3, ['lite303', 'lite309', 'lite315'], 148, 0x19);
  }

  _mMaelstrom2(code, obj) {
    this._stage(code, obj, DROP_TARGETS, 3, ['lite306', 'lite308', 'lite310', 'lite313', 'lite319'], 149, 0x1a);
  }

  _mMaelstrom3(code, obj) {
    const lights = ['lite301', 'lite302', 'lite307', 'lite316', 'lite320', 'lite321'];
    this._stage(code, obj, LANE_ROLLOVERS, 5, lights, 150, 0x1b);
  }

  _single(code, obj, members, light, text, nextState, onEnter = null, onDone = null) {
    if (code === 0x3f) {
      if (members.includes(nameOf(obj))) {
        this.msg(light, 0x14);
        this.setData('lite198', nextState);
        this._mission(0x42, null);
        if (onDone !== null) onDone();
      }
      return;
    }
    if (code === 0x42) {
      if (onEnter !== null) onEnter();
      this.msg(light, 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(text);
  }

  _mMaelstrom4(code, obj) {
    this._single(code, obj, ['a_roll184'], 'lite318', 151, 0x1c, () => this.setData('lite56', 0));
  }

  _mMaelstrom5(code, obj) {
    this._single(code, obj, ['ramp'], 'lite317', 152, 0x1d);
  }

  _mMaelstrom6(code, obj) {
    if (code === 0x3f) {
      if (FLAGS.includes(nameOf(obj))) {
        for (const light of ['lite305', 'lite312']) this.msg(light, 0x14);
        this.setData('lite198', 0x1e);
        this._mission(0x42, null);
        this.msg('lite20', 0x14);
        this.msg('lite19', 0x14);
      }
      return;
    }
    if (code === 0x42) {
      this.msg('lite20', 0x13);
      this.msg('lite19', 0x13);
      this.msg('lite305', 7);
      this.msg('lite312', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(153);
  }

  _mMaelstrom7(code, obj) {
    if (code === 0x3f) {
      if (['v_sink1', 'v_sink2', 'v_sink3'].includes(nameOf(obj))) {
        this.setData('lite198', 0x1f);
        this._mission(0x42, null);
      }
      return;
    }
    if (code === 0x42) {
      this._advanceWormhole(1);
      for (const sink of ['v_sink1', 'v_sink2', 'v_sink3']) this.msg(sink, 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(154);
  }

  _mMaelstrom8(code, obj) {
    if (code === 0x3f) {
      if (nameOf(obj) === 'a_kout2') {
        this.msg('lite304', 0x14);
        this.msg('lite130', 0x14);
        this.setData('lite198', 1);
        this._mission(0x42, null);
        const added = this.award(5000000);
        this.text('info', 48, 4.0);
        if (this._rankProgress(0x12) === 0) {
          this._missionText(78, [added], 8.0);
          this.play('soundwave9');
        }
      }
      return;
    }
    if (code === 0x42) {
      this.msg('lite130', 0x13);
      this.msg('lite304', 7);
    } else if (code !== 0x43) {
      return;
    }
    this._missionText(155);
  }

  _mGameOver(code, obj) {
    const box = this.mission_box;
    if (code === 0x42) {
      this.msg('goal_lights', 0x14);
      this.setMode(2);
      this.flipperMessage(0x3fe);
      box.data = 0;
      return;
    }
    if (code !== 0x43) return;
    let place = box.data;
    if ((place & 0x100) === 0 && (place & 0x200) === 0) {
      box.data = 0x100;
      this.text('mission', 172, 10.0);
      return;
    }
    if (place & 0x100) {
      const player = place & 0xf;
      const score = player < 4 ? this.boxes[player] : -1;
      if (score >= 0) {
        this.text('mission', 180 + player, 3.0, score);
        const nxt = player + 1;
        box.data = nxt === this.player_count ? 0x200 : nxt | 0x100;
        return;
      }
      box.data = 0x200;
      place = player + 1;
    }
    const rank = place & 0xf;
    const score = rank < 5 ? this.high_scores.score(rank) : 0;
    if (score < 1) {
      box.data = 0x100;
      this.text('mission', 172, 10.0);
      return;
    }
    this.text('mission', 184 + rank, 3.0, score);
    box.data = rank + 1 === 5 ? 0 : (rank + 1) | 0x200;
  }
}

export { Missions, RANKS };
