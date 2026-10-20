// Test the current embedded application script with the shared in-memory DOM.
// No browser or local page URL is used.
const assert = require('node:assert/strict');
const {fixture, setTracks, action} = require('./test_drawer.cjs');
const f=fixture();
setTracks(f,f.first,[
  {key:'a-online',label:'Python线上赛',levels:['A类'],sections:['ongoing','deadlines'],search:'蓝桥杯 python',open:false,status:'registration_closed',modes:['online'],node:action()},
  {key:'a-offline',label:'Python线下赛',levels:['A类'],sections:['ongoing'],search:'蓝桥杯 python',open:true,status:'registration_open',modes:['offline'],node:action({at:2000,date:'10.24'})},
]);
setTracks(f,f.second,[
  {key:'b',label:'数学初赛',levels:['B类'],sections:['ongoing'],search:'数学竞赛',open:false,status:'upcoming',modes:['offline'],node:action({at:3000,date:'10.25',kind:'competition_start',label:'比赛开始',urgent:false})},
]);

f.tabs.find(tab=>tab.dataset.section==='deadlines').emit('click');
assert.equal(f.first.card.hidden,false);
assert.equal(f.second.card.hidden,true);
assert.deepEqual(f.first.source.children.map(row=>row.hidden),[false,true]);
assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 1 条赛项记录');

f.tabs.find(tab=>tab.dataset.section==='all').emit('click');
assert.equal(f.second.card.hidden,false);
assert.deepEqual(f.first.source.children.map(row=>row.hidden),[false,false]);
assert.equal(f.nodes['result-count'].textContent,'截止优先，其次赛程');
f.nodes.search.value='PYTHON';
f.nodes.search.emit('input');
assert.equal(f.first.card.hidden,false);
assert.equal(f.second.card.hidden,true);
assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 2 条赛项记录');

f.nodes['open-only'].checked=true;
f.nodes['mode-filter'].value='online';
f.nodes['mode-filter'].emit('change');
assert.equal(f.first.card.hidden,true,'closed online and open offline must never combine into open online');
assert.equal(f.nodes['empty-state'].hidden,false);

f.nodes['empty-reset'].emit('click');
assert.equal(f.first.card.hidden,false);
assert.equal(f.second.card.hidden,false);
f.nodes['grade-filter'].value='B类';
f.nodes['grade-filter'].emit('change');
assert.equal(f.first.card.hidden,true);
assert.equal(f.second.card.hidden,false);
assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 1 条赛项记录');

f.tabs.find(tab=>tab.dataset.section==='new_registration').emit('click');
assert.equal(f.nodes['result-count'].textContent,'匹配 0 项赛事 / 0 条赛项记录');
assert.equal(f.nodes['empty-state'].hidden,false);
console.log('UI interaction checks passed: section/search/grade/form/registration intersection, record counts and reset.');
