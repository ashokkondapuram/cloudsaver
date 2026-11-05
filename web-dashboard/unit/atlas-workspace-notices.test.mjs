import assert from 'node:assert/strict';
import {dedupeNotices} from '../lib/notices.ts';

const notices = dedupeNotices([
  {id: 'a', severity: 'info', title: 'One'},
  {id: 'a', severity: 'warning', title: 'Dup'},
  {id: 'b', severity: 'error', title: 'Two', description: 'detail'},
]);
assert.equal(notices.length, 2);
assert.equal(notices[0].id, 'a');
assert.equal(notices[1].title, 'Two');

console.log('atlas-workspace-notices ok');
