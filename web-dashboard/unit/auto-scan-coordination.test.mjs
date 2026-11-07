import assert from 'node:assert/strict';
import {COOLDOWN_MS, cooldownActive, storageKey} from '../lib/auto-scan-coordination.ts';

assert.equal(storageKey('t1'), 'cloudsaver:auto-scan:t1');
assert.equal(cooldownActive('t1', 0), false);
assert.equal(cooldownActive('t1', COOLDOWN_MS), false);

console.log('auto-scan-coordination ok');
