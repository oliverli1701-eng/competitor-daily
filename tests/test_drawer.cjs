// Exercise the real product UI script against an in-memory DOM.
// These are application interaction tests, not native browser Tab/Escape tests.
// No browser is started and no local file is opened through a browser.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const scriptPath = process.argv[2] || 'contest_daily/product_ui.py';
const source = fs.readFileSync(scriptPath, 'utf8');
// Use the current embedded application script by default; a JS fixture path
// remains accepted for checking a generated report's exact script.
const script = scriptPath.endsWith('.py')
  ? source.match(/SCRIPT = r"""([\s\S]*?)"""/)[1]
  : source;

class Element {
  constructor(document, {id = '', classes = [], dataset = {}, text = '', tag = 'div'} = {}) {
    this.ownerDocument = document;
    this.id = id;
    this.tagName = tag.toUpperCase();
    this.dataset = {...dataset};
    this.textContent = text;
    this.value = '';
    this.checked = false;
    this.hidden = false;
    this.cssHidden = false;
    this.open = false;
    this.scrollTop = 0;
    this.scrollCalls = [];
    this.isContentEditable = false;
    this.children = [];
    this.parentElement = null;
    this.listeners = new Map();
    this.attributes = {};
    this.style = {setProperty(name,value) {this[name]=value;},removeProperty(name) {delete this[name];}};
    this.classes = new Set(classes);
    this.classList = {
      add: (...items) => items.forEach(item => this.classes.add(item)),
      remove: (...items) => items.forEach(item => this.classes.delete(item)),
      contains: item => this.classes.has(item),
      toggle: (item, force) => {
        const enabled = force === undefined ? !this.classes.has(item) : !!force;
        if (enabled) this.classes.add(item); else this.classes.delete(item);
        return enabled;
      },
    };
    if (document.motion) this.animate = (keyframes, options) => document.makeAnimation(this,keyframes,options);
  }
  get className() { return [...this.classes].join(' '); }
  set className(value) { this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get firstElementChild() { return this.children[0]||null; }
  get isConnected() {
    return this === this.ownerDocument.root || !!this.parentElement?.isConnected;
  }
  append(...elements) {
    for (const element of elements) {
      if(element.isFragment){this.append(...[...element.children]);continue;}
      if (element.parentElement) {
        const old = element.parentElement.children;
        old.splice(old.indexOf(element), 1);
      }
      element.parentElement = this;
      this.children.push(element);
    }
  }
  appendChild(element) { this.append(element); return element; }
  replaceChildren(...elements) {
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    this.append(...elements);
  }
  matches(selector) {
    const parts=selector.trim().split(/\s+/);
    if(parts.length>1){
      if(!this.matches(parts.pop()))return false;
      let parent=this.parentElement;
      while(parts.length){const part=parts.pop();while(parent&&!parent.matches(part))parent=parent.parentElement;if(!parent)return false;parent=parent.parentElement;}
      return true;
    }
    const attr=selector.match(/^(.*)\[data-([\w-]+)(?:=["']?([^\]"']+)["']?)?\]$/);
    if(attr){const key=attr[2].replace(/-([a-z])/g,(_,x)=>x.toUpperCase());return (!attr[1]||this.matches(attr[1]))&&key in this.dataset&&(attr[3]===undefined||this.dataset[key]===attr[3]);}
    const ordinary=selector.match(/^(.*)\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]$/);
    if(ordinary)return (!ordinary[1]||this.matches(ordinary[1]))&&ordinary[2] in this.attributes&&(ordinary[3]===undefined||this.attributes[ordinary[2]]===ordinary[3]);
    if (selector.startsWith('.')) return selector.slice(1).split('.').every(name => this.classes.has(name));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector === '[hidden]') return this.hidden;
    return selector.toUpperCase() === this.tagName;
  }
  querySelectorAll(selector) {
    const choices = selector.split(',').map(item => item.trim());
    const found = [];
    const visit = parent => {
      for (const child of parent.children) {
        if (choices.some(choice => child.matches(choice))) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let element = this; element; element = element.parentElement) {
      if (element.matches(selector)) return element;
    }
    return null;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]??null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  emit(name, values = {}) {
    const event = {
      target: this,
      currentTarget: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...values,
    };
    for (const listener of this.listeners.get(name) || []) listener(event);
    return event;
  }
  getClientRects() {
    if (!this.isConnected) return [];
    for (let element = this; element; element = element.parentElement) {
      if (element.hidden || element.cssHidden) return [];
    }
    return [{x: 0, y: 0, width: 100, height: 30}];
  }
  getBoundingClientRect() {
    const top=Math.max(0,this.parentElement?.children.filter(child=>!child.hidden).indexOf(this)||0)*60;
    return {x:0,y:top,left:0,top,right:100,bottom:top+30,width:100,height:30};
  }
  focus() {
    if (this.getClientRects().length) this.ownerDocument.activeElement = this;
  }
  scrollIntoView(options) {this.scrollCalls.push(options);}
  cloneNode(deep = false) {
    const clone = new Element(this.ownerDocument, {
      id: this.id, classes: [...this.classes], dataset: this.dataset, text: this.textContent, tag:this.tagName,
    });
    clone.hidden = this.hidden;
    clone.value = this.value;
    clone.checked = this.checked;
    clone.attributes = {...this.attributes};
    if (deep) clone.append(...this.children.map(child => child.cloneNode(true)));
    return clone;
  }
}

function fixture({motion=false,reducedMotion=true,now='2026-10-16T12:00:00+08:00',asOf='2026-10-15T12:00:00+08:00',withHero=true,intersection=true,darkScheme=false,finePointer=false,storageThrows=false}={}) {
  const animations=[];
  let nowMs=Date.parse(now),timerId=0;
  const timers=new Map(),observers=[],storage=new Map();
  const schedule=(callback,delay,repeat=false,raf=false)=>{const id=++timerId;timers.set(id,{callback,delay:Math.max(1,Number(delay)||1),due:nowMs+Math.max(1,Number(delay)||1),repeat,raf});return id;};
  const setTimeout=(callback,delay)=>schedule(callback,delay);
  const setInterval=(callback,delay)=>schedule(callback,delay,true);
  const clearTimer=id=>timers.delete(id);
  const requestAnimationFrame=callback=>schedule(callback,16,false,true);
  const advance=milliseconds=>{
    const end=nowMs+milliseconds;let ticks=0;
    while(true){
      const next=[...timers].filter(([,timer])=>timer.due<=end).sort((a,b)=>a[1].due-b[1].due)[0];
      if(!next)break;
      if(++ticks>10000)throw new Error('controlled timer exceeded 10000 callbacks');
      const [id,timer]=next;nowMs=timer.due;
      if(timer.repeat)timer.due+=timer.delay;else timers.delete(id);
      timer.callback(timer.raf?nowMs:undefined);
    }
    nowMs=end;
  };
  class ControlledDate extends Date {constructor(...args){super(...(args.length?args:[nowMs]));}static now(){return nowMs;}}
  class IntersectionObserver {
    constructor(callback,options){this.callback=callback;this.options=options;this.targets=new Set();observers.push(this);}
    observe(target){this.targets.add(target);}
    unobserve(target){this.targets.delete(target);}
    disconnect(){this.targets.clear();}
    deliver(target,isIntersecting=true){this.callback([{target,isIntersecting}]);}
  }
  const listeners=new Map();
  const events={
    addEventListener(name,callback){if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(callback);},
    emit(name,values={}){const event={target:document.root,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...values};for(const callback of listeners.get(name)||[])callback(event);return event;},
  };
  const document = {
    activeElement: null,
    hidden:false,
    motion,
    ...events,
    createElement(tag) { return new Element(this,{tag}); },
    createDocumentFragment() {const fragment=new Element(this,{tag:'#document-fragment'});fragment.isFragment=true;return fragment;},
    makeAnimation(target,keyframes,options) {
      let resolve, reject;
      const finished=new Promise((ok,no)=>{resolve=ok;reject=no;});
      // A canceled WAAPI animation rejects finished; this harness observes its
      // state without turning an intentional cancellation into an unhandled rejection.
      finished.catch(()=>{});
      const animation={target,keyframes,options,finished,cancelCalls:0,playState:'running',
        finish(){this.playState='finished';resolve(this);},
        cancel(){this.cancelCalls++;this.playState='idle';reject(new Error('Animation canceled'));},
      };
      animations.push(animation);return animation;
    },
    querySelector(selector) { return this.root.querySelector(selector); },
    querySelectorAll(selector) { return this.root.querySelectorAll(selector); },
    getElementById(id) {return this.root.querySelector('#'+id);},
  };
  document.root = new Element(document,{tag:'html',dataset:{theme:'auto'}});
  document.documentElement=document.root;
  document.root.scrollHeight=2400;
  const el = options => new Element(document, options);
  const nodes = {};
  for (const id of ['search', 'open-only', 'mode-filter', 'grade-filter', 'result-count', 'empty-state',
    'reset-filters', 'empty-reset', 'section-title', 'section-count', 'breadcrumb-section','active-filters']) {
    const tag=['search','open-only'].includes(id)?'input':['mode-filter','grade-filter'].includes(id)?'select':'div';
    nodes[id] = el({id,tag});
    document.root.append(nodes[id]);
  }
  nodes['mode-filter'].value = 'all';
  nodes['grade-filter'].value = 'all';
  const tabs = ['all', 'ongoing', 'deadlines', 'updates', 'new_registration'].map(section => {
    const tab = el({classes: ['tab'], dataset: {section}});
    document.root.append(tab);
    return tab;
  });
  const discovery=el({classes:['discovery'],dataset:{view:'list'}});
  const cardList = el({classes: ['card-list']});
  const timelineView=el({id:'timeline-view'});timelineView.hidden=true;
  discovery.append(cardList,timelineView);document.root.append(discovery);
  const viewToggle=el({classes:['view-toggle']});
  const viewButtons=['list','timeline'].map(view=>{const button=el({tag:'button',dataset:{view}});viewToggle.append(button);return button;});
  document.root.append(viewToggle);
  const themeSwitch=el({classes:['theme-switch']});
  const themeButtons=['auto','light','dark'].map(themeSet=>{const button=el({tag:'button',dataset:{themeSet}});themeSwitch.append(button);return button;});
  const themeMeta=el({tag:'meta'});themeMeta.setAttribute('name','theme-color');
  const shell=el({classes:['daily-shell'],dataset:{asOf:String(Date.parse(asOf)/1000)}});
  const scrollBar=el({id:'scroll-progress'});
  document.root.append(themeSwitch,themeMeta,shell,scrollBar);
  const makeCard = (id, name, search, modes) => {
    const node = action({at:1792454400, date:'10.20', track:'主赛'});
    const variant = {key:id+'-track', label:'主赛', levels:['A类'], sections: ['ongoing', 'deadlines'], search, open: true, status:'registration_open', modes, node, deadline:node};
    const card = el({id, classes: ['contest-card'], dataset: {
      name,featured:variant.key,sections: variant.sections.join(' '), search, open: 'true', modes: modes.join(' '),
      variants: JSON.stringify([variant]),
    }});
    const trigger = el({classes: ['detail-trigger'], text: name + '细则'});
    const state = el({classes: ['state-tag']});
    const stateLabel = el({classes: ['state-label'], text: '报名中'});
    state.append(el({tag:'i'}), stateLabel);
    // Cover both mode marker classes emitted by the real card renderer.
    const modeTag = el({classes:id==='contest-a'?['mode-tag']:['badge','mode'], text:modes[0]});
    const source = el({classes: ['rules-body']});
    const detail = el({classes: ['track-detail'], dataset: {
      sections: 'ongoing deadlines', variant: JSON.stringify(variant),
    }, text: name + '独有作品材料'});
    source.append(detail);
    const trackCount=el({classes:['track-count']});
    const brief=el({classes:['track-brief'],dataset:{key:variant.key,variant:JSON.stringify(variant)},text:name+'独有作品材料'});
    const actionNode=el({classes:['action-node'],dataset:{kind:node.kind}});
    for(const name of ['action-kind','action-date-label','action-date-value','action-clock','action-track','action-relative','action-time'])actionNode.append(el({classes:[name]}));
    const badge=el({classes:['action-badge']});
    const progress=el({classes:['action-progress']});progress.append(el({tag:'i'}));
    actionNode.append(badge,progress);
    const entry=el({classes:['entry-link']});
    const inner=el({classes:['card-inner']});
    inner.append(trackCount,state,modeTag,brief,actionNode,trigger,source,entry);card.append(inner);
    cardList.append(card);
    return {card,inner,trigger,source,detail,state,stateLabel,modeTag,brief,trackCount,actionNode,entry,badge,progress};
  };
  const first = makeCard('contest-a', '甲竞赛', '甲竞赛 python', ['online']);
  const second = makeCard('contest-b', '乙竞赛', '乙竞赛 数学', ['offline']);
  const hero={};
  if(withHero){
    hero.panel=el({classes:['focus-panel']});
    hero.block=el({id:'focus-hero'});hero.title=el({id:'hero-title',tag:'button'});hero.sub=el({id:'hero-sub'});
    hero.countdown=el({id:'hero-countdown'});hero.expired=el({id:'hero-expired'});hero.expired.hidden=true;
    for(const unit of ['days','hours','minutes','seconds'])hero.countdown.append(el({tag:'b',dataset:{unit},text:'00'}));
    hero.ring=el({classes:['hero-ring']});hero.ringValue=el({classes:['ring-value'],dataset:{full:'326.7'}});hero.ringValue.style.strokeDashoffset='200';
    const center=el({classes:['ring-center']});center.append(el({tag:'b'}));hero.ring.append(hero.ringValue,center);
    hero.block.append(hero.title,hero.sub,hero.countdown,hero.expired);hero.panel.append(hero.block,hero.ring);document.root.append(hero.panel);
  }
  const horizon=el({classes:['horizon']});
  const horizonCell=el({tag:'button',classes:['hz-cell'],dataset:{date:'10.20'}});
  horizon.append(horizonCell);document.root.append(horizon);
  const dialog = el({id: 'detail-dialog'});
  const title = el({id: 'detail-title'});
  const close = el({id: 'close-detail'});
  const body = el({id: 'detail-body'});
  dialog.append(title, close, body);
  document.root.append(dialog);
  dialog.showModalCalls = 0;
  dialog.closeCalls = 0;
  dialog.showModal = () => { dialog.showModalCalls++; dialog.open = true; };
  // Real close events are queued by a browser; synchronously dispatching here
  // checks our close handler, not native dialog implementation or event timing.
  dialog.close = () => {
    if (!dialog.open) return;
    dialog.closeCalls++;
    dialog.open = false;
    dialog.emit('close');
  };
  const makeMedia=matches=>({matches,listeners:[],addEventListener(name,callback){if(name==='change')this.listeners.push(callback);},removeEventListener(name,callback){this.listeners=this.listeners.filter(fn=>fn!==callback);},change(value){this.matches=value;for(const callback of this.listeners)callback({matches:value});}});
  const media=makeMedia(reducedMotion),scheme=makeMedia(darkScheme),fine=makeMedia(finePointer);
  const windowEvents=new Map();
  const window={innerHeight:800,scrollY:0,
    matchMedia:query=>query.includes('reduced-motion')?media:query.includes('color-scheme')?scheme:fine,
    addEventListener(name,callback){if(!windowEvents.has(name))windowEvents.set(name,[]);windowEvents.get(name).push(callback);},
    emit(name){for(const callback of windowEvents.get(name)||[])callback();},
    getComputedStyle:()=>({transform:'none',opacity:'1'}),
  };
  if(intersection)window.IntersectionObserver=IntersectionObserver;
  const localStorage={getItem(key){if(storageThrows)throw new Error('storage denied');return storage.get(key)??null;},setItem(key,value){if(storageThrows)throw new Error('storage denied');storage.set(key,String(value));}};
  vm.runInNewContext(script, {document,window,localStorage,IntersectionObserver,Date:ControlledDate,
    setTimeout,setInterval,clearTimeout:clearTimer,clearInterval:clearTimer,requestAnimationFrame,cancelAnimationFrame:clearTimer,performance:{now:()=>nowMs}}, {filename: scriptPath});
  return {document,window,media,scheme,fine,storage,timers,observers,advance,animations,nodes,tabs,first,second,cardList,discovery,timelineView,viewButtons,themeButtons,themeMeta,scrollBar,hero,horizonCell,dialog,title,close,body};
}

function action({at=1000,date='10.20',track='主赛',kind='registration_end',label='报名截止',days=5,urgent=true,clock=''}={}) {
  return {at,label,value:date+(clock?' '+clock:''),kind,days,urgent,urgency:urgent?(days===0?'today':days<=3?'soon':'week'):'',window:7,date_main:date,clock,datetime:'2026-10-20',relative:days===0?'今日截止':days+' 天后',track};
}

function setTracks(f,item,variants) {
  item.card.dataset.variants=JSON.stringify(variants);
  item.source.replaceChildren(...variants.map(v=>new Element(f.document,{
    classes:['track-detail'],dataset:{key:v.key,sections:v.sections.join(' '),variant:JSON.stringify(v)},text:v.label+'独有细则',
  })));
  for(const brief of item.card.querySelectorAll('.track-brief'))brief.parentElement.children.splice(brief.parentElement.children.indexOf(brief),1);
  const briefs=variants.map(v=>new Element(f.document,{classes:['track-brief'],dataset:{key:v.key,variant:JSON.stringify(v)},text:v.label+'独有资格与作品'}));
  (item.inner||item.card).append(...briefs);
  return briefs;
}

let checks = 0;
const queue=[];
function check(name, test,options) {
  if (require.main !== module) return;
  queue.push({name,test,options});
}

check('opens the requested contest, clones content, and focuses close', f => {
  const event = f.first.trigger.emit('click');
  assert.equal(event.defaultPrevented, true);
  assert.equal(f.dialog.showModalCalls, 1);
  assert.equal(f.dialog.open, true);
  assert.equal(f.title.textContent, '甲竞赛');
  assert.equal(f.body.children.length, 1);
  assert.notEqual(f.body.children[0], f.first.source);
  assert.notEqual(f.body.children[0].children[0], f.first.detail);
  assert.equal(f.body.children[0].children[0].textContent, '甲竞赛独有作品材料');
  assert.equal(f.first.source.closest('.contest-card'), f.first.card);
  assert.equal(f.document.activeElement, f.close);
});

check('content clicks keep the drawer open; backdrop clicks close it', f => {
  f.first.trigger.emit('click');
  f.dialog.emit('click', {target: f.body.children[0]});
  assert.equal(f.dialog.open, true);
  assert.equal(f.dialog.closeCalls, 0);
  f.dialog.emit('click', {target: f.dialog});
  assert.equal(f.dialog.open, false);
  assert.equal(f.dialog.closeCalls, 1);
  assert.equal(f.body.children.length, 0);
  assert.equal(f.document.activeElement, f.first.trigger);
});

check('close button restores the exact trigger and clears cloned details', f => {
  f.second.trigger.emit('click');
  assert.equal(f.title.textContent, '乙竞赛');
  f.close.emit('click');
  assert.equal(f.dialog.open, false);
  assert.equal(f.body.children.length, 0);
  assert.equal(f.document.activeElement, f.second.trigger);
});

check('filtering away the open contest closes it and focuses search', f => {
  f.first.trigger.emit('click');
  f.nodes.search.value = '数学';
  f.nodes.search.emit('input');
  assert.equal(f.first.card.hidden, true);
  assert.equal(f.second.card.hidden, false);
  assert.equal(f.dialog.open, false);
  assert.equal(f.body.children.length, 0);
  assert.equal(f.document.activeElement, f.nodes.search);
});

check('a CSS-hidden original trigger falls back to search on close', f => {
  f.first.trigger.emit('click');
  f.first.trigger.cssHidden = true; // e.g. opener becomes unavailable after a responsive layout change.
  f.close.emit('click');
  assert.equal(f.document.activeElement, f.nodes.search);
});

check('opening a different contest replaces all prior content', f => {
  f.first.trigger.emit('click');
  const oldClone = f.body.children[0];
  f.close.emit('click');
  f.second.trigger.emit('click');
  assert.equal(f.dialog.showModalCalls, 2);
  assert.equal(f.body.children.length, 1);
  assert.equal(f.title.textContent, '乙竞赛');
  assert.equal(f.body.children[0].children[0].textContent, '乙竞赛独有作品材料');
  assert.equal(oldClone.isConnected, false);
  assert.equal(f.body.children[0].children.some(item => item.textContent.includes('甲竞赛')), false);
  f.close.emit('click');
  assert.equal(f.document.activeElement, f.second.trigger);
});

check('without showModal support the summary keeps its native details action', f => {
  f.dialog.showModal = undefined;
  const event = f.first.trigger.emit('click');
  assert.equal(event.defaultPrevented, false);
  assert.equal(f.dialog.open, false);
  assert.equal(f.body.children.length, 0);
});

check('matching a third track keeps its own facts, date, scope, status and mode together', f => {
  const variants = ['first track','second track','third track'].map((search,index)=>{
    const node=action({at:1000+index,date:['10.20','11.30','12.18'][index],track:search,days:5+index,urgent:index===0,clock:index===2?'20:00':''});
    return {key:'track-'+index,label:search,levels:['A类'],sections:['ongoing'],search,open:index===0,status:['registration_open','in_progress','registration_closed'][index],modes:[['online'],['offline'],['hybrid']][index],node,deadline:node};
  });
  const briefs=setTracks(f,f.first,variants);
  f.nodes.search.value='third track';
  f.nodes.search.emit('input');
  assert.deepEqual(briefs.map(row=>row.hidden),[true,true,false]);
  assert.equal(f.first.actionNode.querySelector('.action-date-value').textContent,'12.18');
  assert.equal(f.first.actionNode.querySelector('.action-kind').textContent,'报名截止');
  assert.equal(f.first.actionNode.querySelector('.action-clock').textContent,'20:00');
  assert.equal(f.first.actionNode.querySelector('.action-track').textContent,'对应赛项 · third track');
  assert.match(f.first.trackCount.textContent,/1\s*\/\s*3/);
  assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 1 条赛项记录');
  assert.deepEqual(f.first.source.children.map(row=>row.hidden),[true,true,false]);
  assert.equal(f.first.stateLabel.textContent,'报名已截止');
  assert.equal(f.first.state.hidden,false);
  assert.equal(f.first.state.classList.contains('competing'),false);
  assert.equal(f.first.modeTag.textContent,'线上 + 线下');
  assert.equal(f.first.modeTag.hidden,false);

  f.nodes.search.value='second track';
  f.nodes.search.emit('input');
  assert.equal(f.first.stateLabel.textContent,'比赛进行中');
  assert.equal(f.first.state.classList.contains('competing'),true);
  assert.equal(f.first.modeTag.textContent,'线下');

  f.nodes.search.value='';
  f.nodes.search.emit('input');
  assert.equal(f.first.stateLabel.textContent,'含可报名赛项');
  assert.equal(f.first.state.classList.contains('competing'),false);
  assert.match(f.first.modeTag.textContent,/线上/);
  assert.match(f.first.modeTag.textContent,/线下/);
});

check('shared known modes use a multi-track label, then clear when only an unknown mode matches', f => {
  const variants = [
    {key:'known-1',label:'known one',levels:['A类'],sections:['ongoing'],search:'known track one',open:true,status:'registration_open',modes:['online']},
    {key:'known-2',label:'known two',levels:['A类'],sections:['ongoing'],search:'known track two',open:false,status:'in_progress',modes:['online']},
    {key:'unknown',label:'uncertain',levels:['A类'],sections:['updates'],search:'uncertain track',open:false,status:'unknown',modes:[]},
  ];
  f.first.card.dataset.variants=JSON.stringify(variants);
  f.nodes.search.value='known track';
  f.nodes.search.emit('input');
  assert.equal(f.first.stateLabel.textContent,'含可报名赛项');
  assert.equal(f.first.modeTag.textContent,'含线上赛项');
  assert.equal(f.first.modeTag.hidden,false);

  f.nodes.search.value='uncertain track';
  f.nodes.search.emit('input');
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.first.state.hidden,true);
  assert.equal(f.first.stateLabel.textContent,'');
  assert.equal(f.first.modeTag.hidden,true);
  assert.equal(f.first.modeTag.textContent,'');
});

check('individual ended and future tracks show their own status instead of a sibling registration badge', f => {
  const variants = [
    {key:'open',label:'open sibling',levels:['A类'],sections:['ongoing'],search:'open sibling',open:true,status:'registration_open',modes:['online']},
    {key:'ended',label:'ended track',levels:['A类'],sections:['updates'],search:'ended track',open:false,status:'closed',modes:['offline']},
    {key:'future',label:'future track',levels:['A类'],sections:['updates'],search:'future track',open:false,status:'upcoming',modes:['online']},
  ];
  f.second.card.dataset.variants=JSON.stringify(variants);
  f.nodes.search.value='ended track';
  f.nodes.search.emit('input');
  assert.equal(f.second.stateLabel.textContent,'本阶段结束');
  assert.equal(f.second.state.hidden,false);
  assert.equal(f.second.modeTag.textContent,'线下');

  f.nodes.search.value='future track';
  f.nodes.search.emit('input');
  assert.equal(f.second.stateLabel.textContent,'赛程预告');
  assert.equal(f.second.state.classList.contains('upcoming'),true);
  assert.equal(f.second.modeTag.textContent,'线上');
});

check('hybrid tracks match online, offline and hybrid filters; online-only tracks do not match hybrid', f => {
  f.first.card.dataset.variants=JSON.stringify([
    {key:'mixed',label:'mixed',levels:['A类'],sections:['ongoing'],search:'mixed contest',open:true,status:'registration_open',modes:['hybrid']},
  ]);
  f.second.card.dataset.variants=JSON.stringify([
    {key:'remote',label:'remote',levels:['A类'],sections:['ongoing'],search:'remote contest',open:true,status:'registration_open',modes:['online']},
  ]);
  for(const value of ['online','offline','hybrid']) {
    f.nodes['mode-filter'].value=value;
    f.nodes['mode-filter'].emit('change');
    assert.equal(f.first.card.hidden,false,'hybrid should remain visible for '+value);
    assert.equal(f.first.modeTag.textContent,'线上 + 线下');
    assert.equal(f.second.card.hidden,value!=='online','online-only visibility for '+value);
  }
  f.nodes['mode-filter'].value='all';
  f.nodes['mode-filter'].emit('change');
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.second.card.hidden,false);
});

check('filtering to a later track reverses card date order and clearing restores the earliest-track order', f => {
  const variant = (name, at, modes) => ({
    key:name, label:name, levels:['A类'], sections:['ongoing'], search:name, open:true, status:'registration_open', modes,
    node:at===null?null:action({at,date:'fixture date',track:name,urgent:false}),
  });
  const firstVariants = [
    variant('early online track',1000,['online']),
    variant('later offline track',3000,['offline']),
  ];
  const secondVariants = [variant('middle mixed track',2000,['hybrid'])];
  f.first.card.dataset.variants=JSON.stringify(firstVariants);
  f.second.card.dataset.variants=JSON.stringify(secondVariants);
  const order = () => f.cardList.children.filter(card=>!card.hidden).map(card=>card.id);

  f.tabs.find(tab=>tab.dataset.section==='all').emit('click');
  assert.deepEqual(order(),['contest-a','contest-b']);

  f.nodes['mode-filter'].value='offline';
  f.nodes['mode-filter'].emit('change');
  assert.deepEqual(order(),['contest-b','contest-a']);
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.second.card.hidden,false);

  f.nodes['mode-filter'].value='all';
  f.nodes['mode-filter'].emit('change');
  assert.deepEqual(order(),['contest-a','contest-b']);

  // Missing dates go after dated results; ties must use the original card
  // order, rather than whichever DOM order the previous filter produced.
  f.first.card.dataset.variants=JSON.stringify([variant('undated first',null,['online'])]);
  f.nodes.search.emit('input');
  assert.deepEqual(order(),['contest-b','contest-a']);
  f.second.card.dataset.variants=JSON.stringify([variant('undated second',null,['online'])]);
  f.nodes.search.emit('input');
  assert.deepEqual(order(),['contest-a','contest-b']);
});

check('a later real deadline outranks an earlier competition date and controls featured facts', f => {
  const deadline=action({at:3000,date:'10.23',track:'作品赛',kind:'submission_deadline',label:'作品提交截止',days:8,urgent:false});
  const earlierSchedule=action({at:1000,date:'10.16',track:'现场赛',kind:'competition_start',label:'比赛开始',days:1,urgent:false});
  const briefs=setTracks(f,f.first,[
    {key:'onsite',label:'现场赛',levels:['A类'],sections:['ongoing'],search:'same contest',open:false,status:'upcoming',modes:['offline'],node:earlierSchedule},
    {key:'works',label:'作品赛',levels:['A类'],sections:['ongoing'],search:'same contest',open:true,status:'registration_open',modes:['online'],node:deadline},
  ]);
  f.second.card.dataset.variants=JSON.stringify([
    {key:'start',label:'开赛项',levels:['A类'],sections:['ongoing'],search:'other',open:false,status:'upcoming',modes:['offline'],node:earlierSchedule},
  ]);
  f.nodes.search.emit('input');
  assert.deepEqual(f.cardList.children.map(card=>card.id),['contest-a','contest-b']);
  assert.deepEqual(briefs.map(brief=>brief.hidden),[true,false]);
  assert.equal(f.first.actionNode.querySelector('.action-date-value').textContent,'10.23');
  assert.equal(f.first.actionNode.querySelector('.action-kind').textContent,'作品截止');
  assert.equal(f.first.actionNode.querySelector('.action-track').textContent,'对应赛项 · 作品赛');
  assert.equal(f.first.card.dataset.urgent,'false');

  f.nodes['mode-filter'].value='offline';
  f.nodes['mode-filter'].emit('change');
  assert.deepEqual(briefs.map(brief=>brief.hidden),[false,true]);
  assert.equal(f.first.actionNode.querySelector('.action-date-value').textContent,'10.16');
  assert.equal(f.first.actionNode.querySelector('.action-kind').textContent,'比赛开始');
  assert.equal(f.first.actionNode.dataset.kind,'competition_start');
  assert.equal(f.first.card.dataset.urgent,'false');
});

check('closed records remain searchable and every visible scope reports family and track counts', f => {
  setTracks(f,f.first,[
    {key:'live',label:'可报赛',levels:['A类'],sections:['ongoing'],search:'live record',open:true,status:'registration_open',modes:['online'],node:action()},
    {key:'closed',label:'已闭赛',levels:['B类'],sections:['updates'],search:'closed record',open:false,status:'closed',modes:[],node:null},
    {key:'closed2',label:'另一闭赛',levels:['B类'],sections:['updates'],search:'closed second record',open:false,status:'registration_closed',modes:[],node:null},
  ]);
  f.nodes.search.value='closed';
  f.nodes.search.emit('input');
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.second.card.hidden,true);
  assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 2 条赛项记录');
  assert.equal(f.first.actionNode.hidden,true);
  assert.equal(f.first.modeTag.hidden,true);
  assert.match(f.first.trackCount.textContent,/2\s*\/\s*3/);
  assert.equal(f.first.source.children.filter(row=>!row.hidden).length,2);
});

check('section, grade, registration and form must match the same track', f => {
  setTracks(f,f.first,[
    {key:'online-closed',label:'线上闭赛',levels:['A类'],sections:['updates'],search:'same competition',open:false,status:'closed',modes:['online']},
    {key:'offline-open',label:'线下报名',levels:['B类'],sections:['ongoing'],search:'same competition',open:true,status:'registration_open',modes:['offline']},
  ]);
  f.nodes['grade-filter'].value='A类';
  f.nodes['open-only'].checked=true;
  f.nodes['grade-filter'].emit('change');
  assert.equal(f.first.card.hidden,true,'A grade on a closed sibling cannot satisfy open-only');

  f.nodes['grade-filter'].value='B类';
  f.nodes['grade-filter'].emit('change');
  assert.equal(f.first.card.hidden,false);
  f.nodes['mode-filter'].value='online';
  f.nodes['mode-filter'].emit('change');
  assert.equal(f.first.card.hidden,true,'online on a closed sibling cannot satisfy offline registration');

  f.nodes['mode-filter'].value='offline';
  f.tabs.find(tab=>tab.dataset.section==='updates').emit('click');
  assert.equal(f.first.card.hidden,true,'updates on a different sibling cannot satisfy ongoing registration');
  assert.equal(f.nodes['result-count'].textContent,'匹配 0 项赛事 / 0 条赛项记录');
});

check('empty reset clears all filters and restores neutral ordering guidance', f => {
  f.nodes.search.value='no matching item';
  f.nodes['grade-filter'].value='B类';
  f.nodes['open-only'].checked=true;
  f.nodes['mode-filter'].value='offline';
  f.tabs.find(tab=>tab.dataset.section==='new_registration').emit('click');
  assert.equal(f.nodes['empty-state'].hidden,false);
  f.nodes['empty-reset'].emit('click');
  assert.equal(f.nodes.search.value,'');
  assert.equal(f.nodes['open-only'].checked,false);
  assert.equal(f.nodes['mode-filter'].value,'all');
  assert.equal(f.nodes['grade-filter'].value,'all');
  assert.equal(f.nodes['result-count'].textContent,'截止优先，其次赛程');
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.second.card.hidden,false);
  assert.equal(f.nodes['empty-state'].hidden,true);
});

check('registration entry follows the featured track and rejects unsupported URL schemes', f => {
  setTracks(f,f.first,[
    {key:'entry-a',label:'入口甲',levels:['A类'],sections:['ongoing'],search:'entry alpha',open:true,status:'registration_open',modes:['online'],node:action({track:'入口甲'}),entry_url:'https://contest.example/alpha'},
    {key:'entry-b',label:'入口乙',levels:['A类'],sections:['ongoing'],search:'entry beta',open:true,status:'registration_open',modes:['offline'],node:action({at:2000,track:'入口乙'}),entry_url:'https://contest.example/beta'},
    {key:'entry-bad',label:'无效入口',levels:['A类'],sections:['updates'],search:'entry invalid',open:true,status:'registration_open',modes:[],node:null,entry_url:'javascript:alert(1)'},
    {key:'entry-ended',label:'结束入口',levels:['A类'],sections:['updates'],search:'entry ended',open:false,status:'closed',modes:[],node:null,entry_url:'https://contest.example/ended'},
  ]);
  for(const [term,expected] of [['alpha','https://contest.example/alpha'],['beta','https://contest.example/beta']]){
    f.nodes.search.value=term;f.nodes.search.emit('input');
    assert.equal(f.first.entry.hidden,false);
    assert.equal(f.first.entry.attributes.href,expected);
  }
  for(const term of ['invalid','ended']){
    f.nodes.search.value=term;f.nodes.search.emit('input');
    assert.equal(f.first.entry.hidden,true);
    assert.equal(f.first.entry.attributes.href,'#');
  }
});

check('removing one active-filter chip preserves the remaining intersection and returns focus to its field', f => {
  f.nodes.search.value='python';
  f.nodes['open-only'].checked=true;
  f.nodes['mode-filter'].value='online';
  f.nodes['grade-filter'].value='A类';
  f.tabs.find(tab=>tab.dataset.section==='ongoing').emit('click');
  const chip=name=>f.nodes['active-filters'].querySelectorAll('.filter-chip').find(item=>item.dataset.filter===name);
  assert.equal(f.nodes['active-filters'].hidden,false);
  assert.equal(f.nodes['active-filters'].querySelectorAll('.filter-chip').length,5);
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.second.card.hidden,true);
  chip('search').emit('click');
  assert.equal(f.nodes.search.value,'');
  assert.equal(f.nodes['open-only'].checked,true);
  assert.equal(f.nodes['mode-filter'].value,'online');
  assert.equal(f.nodes['grade-filter'].value,'A类');
  assert.equal(f.tabs.find(tab=>tab.dataset.section==='ongoing').attributes['aria-pressed'],'true');
  assert.equal(f.nodes['active-filters'].querySelectorAll('.filter-chip').length,4);
  assert.equal(f.document.activeElement,f.nodes.search);
  chip('grade').emit('click');
  assert.equal(f.nodes['grade-filter'].value,'all');
  assert.equal(f.nodes['mode-filter'].value,'online');
  assert.equal(f.nodes['open-only'].checked,true);
  assert.equal(f.document.activeElement,f.nodes['grade-filter']);
});

check('filter chip labels keep search input as plain text and reset removes the entire active summary', f => {
  const term='<img src=x onerror=alert(1)>';
  f.nodes.search.value=term;
  f.nodes.search.emit('input');
  const chip=f.nodes['active-filters'].querySelectorAll('.filter-chip').find(item=>item.dataset.filter==='search');
  assert.ok(chip);
  assert.match(chip.children[0].textContent,/^.*<img src=x onerror=alert\(1\)>.*$/);
  assert.equal(chip.querySelectorAll('img').length,0);
  f.nodes['reset-filters'].emit('click');
  assert.equal(f.nodes['active-filters'].hidden,true);
  assert.equal(f.nodes['active-filters'].children.length,0);
  assert.equal(f.nodes['result-count'].textContent,'截止优先，其次赛程');
});

check('reduced motion keeps dialog closure immediate even when animation is supported', f => {
  f.first.trigger.emit('click');
  f.close.emit('click');
  assert.equal(f.dialog.open,false);
  assert.equal(f.dialog.closeCalls,1);
  assert.equal(f.document.activeElement,f.first.trigger);
  assert.equal(f.animations.filter(a=>a.target===f.dialog).length,0);
},{motion:true,reducedMotion:true});

check('animated close retains the modal until completion, ignores repeated close and then restores focus', async f => {
  f.first.trigger.emit('click');
  f.close.emit('click');
  assert.equal(f.dialog.open,true);
  assert.equal(f.dialog.closeCalls,0);
  assert.equal(f.document.activeElement,f.close);
  const exits=f.animations.filter(a=>a.target===f.dialog);
  assert.equal(exits.length,1);
  f.close.emit('click');
  assert.equal(f.animations.filter(a=>a.target===f.dialog).length,1);
  exits[0].finish();
  await Promise.resolve();await Promise.resolve();
  assert.equal(f.dialog.open,false);
  assert.equal(f.dialog.closeCalls,1);
  assert.equal(f.body.children.length,0);
  assert.equal(f.document.activeElement,f.first.trigger);
},{motion:true,reducedMotion:false});

check('Escape cancellation uses the same controlled close lifecycle', async f => {
  f.first.trigger.emit('click');
  const event=f.dialog.emit('cancel');
  assert.equal(event.defaultPrevented,true);
  assert.equal(f.dialog.open,true);
  const exit=f.animations.filter(a=>a.target===f.dialog)[0];
  assert.ok(exit);
  exit.finish();await Promise.resolve();await Promise.resolve();
  assert.equal(f.dialog.open,false);
  assert.equal(f.document.activeElement,f.first.trigger);
},{motion:true,reducedMotion:false});

check('a previously queued exit completion cannot close a newly opened contest', async f => {
  f.first.trigger.emit('click');
  f.close.emit('click');
  const oldExit=f.animations.filter(a=>a.target===f.dialog)[0];
  // Queue the old completion first, then reopen before its Promise callback runs.
  oldExit.finish();
  f.second.trigger.emit('click');
  await Promise.resolve();await Promise.resolve();
  assert.equal(f.dialog.open,true);
  assert.equal(f.dialog.closeCalls,0);
  assert.equal(f.title.textContent,'乙竞赛');
  assert.equal(f.document.activeElement,f.close);
  assert.equal(f.body.children[0].children[0].textContent,'乙竞赛独有作品材料');
},{motion:true,reducedMotion:false});

check('filter results update immediately while motion is pending and new motion cancels stale motion', f => {
  f.nodes.search.value='数学';f.nodes.search.emit('input');
  assert.equal(f.first.card.hidden,true);
  assert.equal(f.second.card.hidden,false);
  assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 1 条赛项记录');
  const firstMotion=f.animations.filter(a=>a.target===f.second.card).at(-1);
  assert.ok(firstMotion);
  assert.equal(firstMotion.playState,'running');
  f.nodes.search.value='';f.nodes.search.emit('input');
  assert.equal(f.first.card.hidden,false);
  assert.equal(f.second.card.hidden,false);
  assert.equal(f.nodes['result-count'].textContent,'截止优先，其次赛程');
  assert.ok(firstMotion.cancelCalls>0);
},{motion:true,reducedMotion:false});

check('manual and automatic theme choices update controls, persistence and browser chrome consistently', f => {
  f.themeButtons.find(button=>button.dataset.themeSet==='dark').emit('click');
  assert.equal(f.document.documentElement.dataset.theme,'dark');
  assert.equal(f.storage.get('cb-theme'),'dark');
  assert.equal(f.themeMeta.getAttribute('content'),'#151310');
  assert.equal(f.themeButtons.find(button=>button.dataset.themeSet==='dark').getAttribute('aria-pressed'),'true');
  f.themeButtons.find(button=>button.dataset.themeSet==='auto').emit('click');
  assert.equal(f.themeMeta.getAttribute('content'),'#f6f4ee');
  f.scheme.change(true);
  assert.equal(f.document.documentElement.dataset.theme,'auto');
  assert.equal(f.themeMeta.getAttribute('content'),'#151310');
  assert.equal(f.storage.get('cb-theme'),'auto');
});

check('denied local storage does not break theme selection or filtering', f => {
  f.themeButtons.find(button=>button.dataset.themeSet==='light').emit('click');
  assert.equal(f.document.documentElement.dataset.theme,'light');
  f.nodes.search.value='数学';f.nodes.search.emit('input');
  assert.equal(f.first.card.hidden,true);
  assert.equal(f.second.card.hidden,false);
  assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 1 条赛项记录');
},{storageThrows:true});

check('timeline view preserves the active filter and opens its matching contest with focus restoration', f => {
  f.nodes.search.value='python';f.nodes.search.emit('input');
  f.document.emit('keydown',{key:'t'});
  assert.equal(f.discovery.dataset.view,'timeline');
  assert.equal(f.timelineView.hidden,false);
  assert.equal(f.nodes.search.value,'python');
  const entries=f.timelineView.querySelectorAll('.timeline-entry');
  assert.equal(entries.length,1);
  assert.equal(entries[0].querySelector('.entry-contest').textContent,'甲竞赛');
  assert.equal(f.nodes['result-count'].textContent,'匹配 1 项赛事 / 1 条赛项记录');
  entries[0].emit('click');
  assert.equal(f.title.textContent,'甲竞赛');
  f.close.emit('click');
  assert.equal(f.document.activeElement,entries[0]);
  f.document.emit('keydown',{key:'T'});
  assert.equal(f.discovery.dataset.view,'list');
  assert.equal(f.timelineView.hidden,true);
});

check('timeline dates stay chronological while the default list keeps deadline priority', f => {
  setTracks(f,f.first,[{key:'late-deadline',label:'10月25日提交',levels:['A类'],sections:['ongoing'],search:'late deadline',open:true,status:'registration_open',modes:['online'],node:action({at:Date.parse('2026-10-25T12:00:00+08:00')/1000,date:'10.25',track:'10月25日提交',kind:'submission_deadline',label:'作品提交截止',days:10,urgent:false})}]);
  setTracks(f,f.second,[{key:'early-start',label:'10月16日开赛',levels:['A类'],sections:['ongoing'],search:'early competition',open:false,status:'upcoming',modes:['offline'],node:action({at:Date.parse('2026-10-16T12:00:00+08:00')/1000,date:'10.16',track:'10月16日开赛',kind:'competition_start',label:'比赛开始',days:1,urgent:false})}]);
  f.nodes.search.emit('input');
  assert.deepEqual(f.cardList.children.map(card=>card.id),['contest-a','contest-b']);
  f.viewButtons.find(button=>button.dataset.view==='timeline').emit('click');
  assert.deepEqual(f.timelineView.querySelectorAll('.timeline-day').map(day=>day.dataset.date),['10.16','10.25']);
  assert.deepEqual(f.timelineView.querySelectorAll('.timeline-entry').map(entry=>entry.dataset.kind),['competition_start','submission_deadline']);
});

check('keyboard shortcuts preserve typing, composing, modifiers and dialog interaction', f => {
  const editable=new Element(f.document,{tag:'div'});editable.isContentEditable=true;editable.setAttribute('contenteditable','true');f.document.root.append(editable);
  const textarea=new Element(f.document,{tag:'textarea'});f.document.root.append(textarea);
  for(const target of [f.nodes.search,f.nodes['mode-filter'],textarea,editable]){
    f.document.emit('keydown',{key:'t',target});
    f.document.emit('keydown',{key:'d',target});
    assert.equal(f.discovery.dataset.view,'list');
    assert.equal(f.document.documentElement.dataset.theme,'auto');
  }
  for(const flags of [{isComposing:true},{ctrlKey:true},{metaKey:true},{altKey:true}]){
    f.document.emit('keydown',{key:'t',...flags});
    f.document.emit('keydown',{key:'d',...flags});
    assert.equal(f.discovery.dataset.view,'list');
    assert.equal(f.document.documentElement.dataset.theme,'auto');
  }
  f.first.trigger.emit('click');
  f.document.emit('keydown',{key:'t'});f.document.emit('keydown',{key:'d'});
  assert.equal(f.discovery.dataset.view,'list');assert.equal(f.document.documentElement.dataset.theme,'auto');
  f.close.emit('click');
  const event=f.document.emit('keydown',{key:'/'});
  assert.equal(event.defaultPrevented,true);assert.equal(f.document.activeElement,f.nodes.search);
});

check('the real-time focus uses the same featured track as the filtered card', f => {
  const variants=['earlier sibling','requested sibling'].map((label,index)=>({
    key:'hero-'+index,label,levels:['A类'],sections:['ongoing'],search:label,open:true,status:'registration_open',modes:['online'],
    node:action({at:Date.parse(index?'2026-10-25T12:00:00+08:00':'2026-10-21T12:00:00+08:00')/1000,date:index?'10.25':'10.21',track:label,days:index?10:6}),
  }));
  setTracks(f,f.first,variants);
  f.nodes.search.value='requested sibling';f.nodes.search.emit('input');
  assert.equal(f.first.actionNode.querySelector('.action-track').textContent,'对应赛项 · requested sibling');
  assert.match(f.hero.sub.textContent,/requested sibling/);
  assert.doesNotMatch(f.hero.sub.textContent,/earlier sibling/);
  assert.equal(f.hero.countdown.querySelector('[data-unit="days"]').textContent,'09');
});

check('an expired historical report shows expiration without leaving a repeating ticker', f => {
  assert.equal(f.hero.countdown.hidden,true);
  assert.equal(f.hero.expired.hidden,false);
  assert.equal([...f.timers.values()].filter(timer=>timer.repeat).length,0);
  f.nodes.search.value='数学';f.nodes.search.emit('input');
  assert.equal(f.hero.countdown.hidden,true);assert.equal(f.hero.expired.hidden,false);
  assert.equal([...f.timers.values()].filter(timer=>timer.repeat).length,0);
},{now:'2028-01-01T12:00:00+08:00'});

check('a running countdown expires and cancels its own interval', f => {
  const at=Date.parse('2026-10-16T12:00:01.500+08:00')/1000;
  setTracks(f,f.first,[{key:'near',label:'near deadline',levels:['A类'],sections:['ongoing'],search:'near deadline',open:true,status:'registration_open',modes:['online'],node:action({at,date:'10.16',track:'near deadline',days:0})}]);
  f.nodes.search.value='near deadline';f.nodes.search.emit('input');
  assert.equal(f.hero.countdown.hidden,false);
  assert.equal([...f.timers.values()].filter(timer=>timer.repeat).length,1);
  f.advance(2000);
  assert.equal(f.hero.countdown.hidden,true);
  assert.equal(f.hero.expired.hidden,false);
  assert.equal([...f.timers.values()].filter(timer=>timer.repeat).length,0);
});

check('calendar navigation locates a matching timeline day and clears the transient highlight', f => {
  f.horizonCell.emit('click');
  assert.equal(f.discovery.dataset.view,'timeline');
  f.advance(16);
  const day=f.timelineView.querySelector('[data-date="10.20"]');
  assert.ok(day);assert.equal(day.scrollCalls.length,1);
  assert.equal(day.scrollCalls[0].behavior,'auto');
  assert.equal(day.classList.contains('hz-flash'),true);
  f.advance(1400);assert.equal(day.classList.contains('hz-flash'),false);
});

check('intersection reveal and unsupported-observer fallback retain readable cards', f => {
  assert.equal(f.observers.length,1);
  assert.equal(f.observers[0].targets.has(f.first.card),true);
  f.observers[0].deliver(f.first.card);
  assert.equal(f.first.card.classList.contains('revealed'),true);
  assert.equal(f.observers[0].targets.has(f.first.card),false);
},{motion:true,reducedMotion:false});

check('cards reveal immediately when IntersectionObserver is unavailable', f => {
  assert.equal(f.first.card.classList.contains('revealed'),true);
  assert.equal(f.second.card.classList.contains('revealed'),true);
},{motion:true,reducedMotion:false,intersection:false});

if (require.main === module) (async()=>{
  for(const {name,test,options} of queue){await test(fixture(options));checks++;console.log('PASS '+name);}
  console.log(`${checks} drawer application checks passed; native browser Tab/Escape behavior is outside this test.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
module.exports = {fixture, Element, action, setTracks};
