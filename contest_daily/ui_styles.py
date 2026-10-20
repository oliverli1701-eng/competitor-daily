"""竞赛日报 V7 动效特刊：在编辑部版式上加入数据驱动的动效层。

深色变量同时挂在 [data-theme='dark'] 与系统偏好媒体查询上：
未选择时跟随系统，手动选择后以记忆为准；打印始终回到浅色纸面。
"""

LIGHT = """
  color-scheme: light;
  --canvas: #f6f4ee;
  --paper: #fffdf8;
  --paper-raise: #f9f6ec;
  --ink: #221e15;
  --ink-soft: #46402f;
  --muted: #7a7160;
  --line: #d9d2c0;
  --line-soft: #eae5d5;
  --rule: #2b2519;
  --accent: #9d2c22;
  --accent-soft: #f6ebe6;
  --accent-line: #ddc2b8;
  --status: #2e6b4f;
  --today: #9d2c22;
  --today-bg: #f9ebe6;
  --today-line: #dcb0a5;
  --today-contrast: #ffffff;
  --soon: #8a4a10;
  --soon-bg: #faf0da;
  --soon-line: #e2c48c;
  --week: #8a6414;
  --week-bg: #faf4e2;
  --week-line: #e5d6a8;
  --focus: #4c8eae;
  --shadow-card: 0 1px 2px #221e1505, 0 10px 26px #221e150a;
  --shadow-card-hover: 0 2px 4px #221e1506, 0 16px 34px #221e1510;
  --shadow-drawer: -18px 0 60px #221e1524;
  --grain-opacity: 0.05;
"""

DARK = """
  color-scheme: dark;
  --canvas: #151310;
  --paper: #1d1a15;
  --paper-raise: #252118;
  --ink: #ece4d2;
  --ink-soft: #d3c9b4;
  --muted: #a2977f;
  --line: #3a3529;
  --line-soft: #2d2921;
  --rule: #cfc4a8;
  --accent: #dd7057;
  --accent-soft: #32211b;
  --accent-line: #5e382d;
  --status: #82c2a0;
  --today: #e28268;
  --today-bg: #341d17;
  --today-line: #6e352a;
  --today-contrast: #1d1a15;
  --soon: #dfa457;
  --soon-bg: #2c2312;
  --soon-line: #6b5121;
  --week: #cfa64f;
  --week-bg: #282212;
  --week-line: #5c4b22;
  --focus: #7ab2cf;
  --shadow-card: 0 1px 2px #00000055, 0 10px 26px #00000066;
  --shadow-card-hover: 0 2px 4px #00000055, 0 16px 34px #00000070;
  --shadow-drawer: -18px 0 60px #000000b3;
  --grain-opacity: 0.07;
"""

SHARED = """
  --ease-out: cubic-bezier(.22, .61, .36, 1);
  --ease-soft: cubic-bezier(.2, .7, .25, 1);
  --serif: 'Noto Serif SC', 'Source Han Serif SC', 'Songti SC', 'STZhongsong', SimSun, Georgia, 'Times New Roman', serif;
  --sans: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
"""

MAIN = r'''
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--canvas);
  color: var(--ink);
  font: 14px/1.65 var(--sans);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
/* 纸面颗粒：SVG 噪点贴在画布上，给编辑部纸面一点触感。 */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  opacity: var(--grain-opacity);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E");
}
::selection { background: var(--accent); color: #fff; }
button, input, select { font: inherit; }
button, a, input, select, summary { -webkit-tap-highlight-color: transparent; }
button { color: inherit; cursor: pointer; }
a { color: inherit; text-decoration: none; }
button, input, select, summary { border-radius: 0; }
a, button, summary { touch-action: manipulation; }
button:focus-visible, a:focus-visible, summary:focus-visible,
input:focus-visible, select:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 4px;
}
[hidden] { display: none !important; }
.icon { display: inline-block; width: 19px; height: 19px; flex-shrink: 0; vertical-align: middle; }
svg { overflow: visible; }
.daily-shell { width: calc(100% - 88px); max-width: 1240px; margin: 0 auto; }

/* 阅读进度：顶部朱红细条随滚动伸展，量的是这条日报读到哪儿了。 */
#scroll-progress {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: 0 50%;
  z-index: 70;
  pointer-events: none;
}

/* 刊头：居中报名与日期栏，层级靠报格规则线分隔；印章落版、刊名逐字浮现。 */
.masthead { padding-top: 14px; animation: brief-reveal 380ms var(--ease-out) backwards; }
.utility-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 54px;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
}
.brand { display: inline-flex; align-items: center; gap: 11px; }
.brand-seal {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 4px;
  background: var(--accent);
  color: var(--today-contrast);
  font: 700 17px/1 var(--serif);
  box-shadow: inset 0 0 0 1px #ffffff2e;
  animation: seal-stamp 500ms cubic-bezier(.2, .75, .2, 1) 160ms backwards;
}
.brand-copy { display: flex; flex-direction: column; line-height: 1.25; }
.brand-copy b { font: 700 16px/1.3 var(--serif); letter-spacing: .16em; }
.brand-copy small { font: 600 9px/1.4 var(--sans); letter-spacing: .24em; color: var(--muted); }
.utility-actions { display: flex; align-items: center; gap: 14px; }
.theme-switch { display: inline-flex; border: 1px solid var(--line); background: var(--paper); }
.theme-switch button {
  min-height: 32px;
  padding: 5px 12px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  transition: color 160ms, background 160ms;
}
.theme-switch button + button { border-left: 1px solid var(--line); }
.theme-switch button:not(.active):hover { color: var(--ink); }
.theme-switch button.active { background: var(--ink); color: var(--paper); font-weight: 600; }
.export-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 33px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  transition: border-color 180ms, background 180ms;
}
.export-button .icon { width: 15px; height: 15px; }
.export-button:hover { border-color: var(--accent-line); background: var(--accent-soft); }

.nameplate { text-align: center; padding: 30px 0 0; }
.masthead-eyebrow { margin: 0; font-size: 12px; font-weight: 600; letter-spacing: .42em; text-indent: .42em; color: var(--muted); }
.nameplate h1 {
  margin: 13px 0 0;
  font-family: var(--serif);
  font-size: 52px;
  line-height: 1.15;
  font-weight: 700;
  letter-spacing: .3em;
  text-indent: .3em;
}
.title-char { display: inline-block; animation: char-drop 480ms var(--ease-soft) backwards; animation-delay: calc(200ms + var(--i) * 70ms); }
.dateline {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin: 17px 0 0;
  color: var(--ink-soft);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}
.dateline::before, .dateline::after { content: ''; flex: 0 1 110px; height: 1px; background: var(--line); }
.dateline-sep { color: var(--muted); }
.issue-meta {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 5px 14px;
  margin: 26px 0 0;
  padding: 9px 0;
  border-top: 2px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  color: var(--muted);
  font-size: 12.5px;
}
.issue-meta b { color: var(--ink); font-weight: 650; font-variant-numeric: tabular-nums; }
.meta-sep { color: var(--line); }

/* 焦点面板：今日最紧迫节点的实时倒计时 + 提醒窗口进度环 + 未来 14 天节点日历带。 */
.focus-panel {
  margin-top: 22px;
  border: 1px solid var(--line);
  border-top: 3px solid var(--rule);
  background: var(--paper);
  box-shadow: var(--shadow-card);
  animation: brief-reveal 460ms 140ms var(--ease-out) backwards;
}
.focus-panel[data-urgency='today'] { border-top-color: var(--today); }
.focus-panel[data-urgency='soon'] { border-top-color: var(--soon); }
.focus-panel[data-urgency='week'] { border-top-color: var(--week); }
.focus-hero { display: flex; align-items: center; justify-content: space-between; gap: 28px; padding: 24px 28px 20px; }
.hero-main { min-width: 0; }
.hero-eyebrow { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 11px; font-weight: 650; letter-spacing: .18em; color: var(--muted); }
.hero-live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: live-pulse 2.2s ease-in-out infinite; }
.hero-title {
  margin: 10px 0 0;
  padding: 0;
  border: 0;
  background: none;
  font-family: var(--serif);
  font-size: 27px;
  line-height: 1.4;
  font-weight: 700;
  color: var(--ink);
  text-align: left;
  letter-spacing: -.01em;
  overflow-wrap: anywhere;
}
.hero-title:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 6px; text-decoration-thickness: 2px; }
.hero-sub { margin: 6px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.hero-countdown { display: flex; align-items: stretch; gap: 8px; margin-top: 16px; }
.cd-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 64px;
  padding: 8px 10px 7px;
  border: 1px solid var(--line);
  background: var(--paper-raise);
}
.cd-num { font-family: var(--serif); font-size: 29px; font-weight: 700; line-height: 1; color: var(--ink); font-variant-numeric: tabular-nums; }
.cd-label { margin-top: 5px; font-size: 11px; color: var(--muted); letter-spacing: .12em; }
.focus-panel[data-urgency='today'] .cd-cell[data-cell='days'] .cd-num { color: var(--today); }
.focus-panel[data-urgency='soon'] .cd-cell[data-cell='days'] .cd-num { color: var(--soon); }
.focus-panel[data-urgency='week'] .cd-cell[data-cell='days'] .cd-num { color: var(--week); }
.hero-expired { margin: 16px 0 0; padding: 8px 12px; border: 1px dashed var(--line); color: var(--muted); font-size: 12.5px; }
.hero-ring { position: relative; width: 132px; height: 132px; flex-shrink: 0; }
.hero-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.ring-track { fill: none; stroke: var(--line-soft); stroke-width: 7; }
.ring-value { fill: none; stroke: var(--week); stroke-width: 7; stroke-linecap: round; transition: stroke-dashoffset .9s var(--ease-soft) .25s; }
.focus-panel[data-urgency='today'] .ring-value { stroke: var(--today); }
.focus-panel[data-urgency='soon'] .ring-value { stroke: var(--soon); }
.ring-center { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; gap: 2px; }
.ring-center b { font-family: var(--serif); font-size: 34px; line-height: 1; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }
.ring-center span { font-size: 10px; color: var(--muted); letter-spacing: .14em; }
.horizon { padding: 15px 28px 20px; border-top: 1px solid var(--line-soft); }
.horizon-title { margin: 0 0 12px; font-size: 11px; font-weight: 650; letter-spacing: .18em; color: var(--muted); }
.horizon-cells { display: grid; grid-template-columns: repeat(14, minmax(0, 1fr)); gap: 5px; }
.hz-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 2px 7px;
  border: 1px solid transparent;
  background: none;
  transition: background 150ms, border-color 150ms;
  animation: hz-rise 420ms var(--ease-soft) backwards;
  animation-delay: calc(260ms + var(--i) * 24ms);
}
.hz-cell:not(:disabled):hover { border-color: var(--line); background: var(--paper-raise); }
.hz-cell:disabled { cursor: default; opacity: .42; }
.hz-week { font-size: 10px; color: var(--muted); }
.hz-day { font-family: var(--serif); font-size: 15px; font-weight: 650; line-height: 1.2; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
.hz-bars { display: flex; gap: 2px; align-items: flex-end; height: 15px; margin-top: 3px; }
.hz-bars:empty::after { content: ''; width: 3px; height: 2px; background: var(--line); }
.hz-bars i { width: 3px; border-radius: 1px; background: var(--muted); }
.hz-bars i:nth-child(1) { height: 6px; }
.hz-bars i:nth-child(2) { height: 10px; }
.hz-bars i:nth-child(3) { height: 13px; }
.hz-bars i:nth-child(4) { height: 15px; }
.hz-count { font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; margin-top: 1px; }
.hz-flag {
  position: absolute;
  top: 3px; right: 3px;
  padding: 1px 3px;
  border: 1px solid var(--accent);
  color: var(--accent);
  font-size: 9px;
  line-height: 1.3;
}
.hz-cell.hz-issue .hz-day { color: var(--accent); }
.hz-cell.hz-today { border-color: var(--today-line); background: var(--today-bg); }
.hz-cell.hz-today .hz-day { color: var(--today); }
.hz-cell.hz-today .hz-bars i { background: var(--today); }
.hz-cell.hz-soon { border-color: var(--soon-line); background: var(--soon-bg); }
.hz-cell.hz-soon .hz-day { color: var(--soon); }
.hz-cell.hz-soon .hz-bars i { background: var(--soon); }
.hz-cell.hz-week { border-color: var(--week-line); }
.hz-cell.hz-week .hz-bars i { background: var(--week); }

/* 栏目索引：四个视角是本期目录，中文数字作版号；选中态由衬线版号与朱红下划线表达。 */
.section-nav { margin-top: 24px; animation: brief-reveal 400ms 45ms var(--ease-out) backwards; }
.section-tabs { display: flex; align-items: stretch; gap: 26px; border-bottom: 1px solid var(--rule); }
.section-tabs .tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-height: 46px;
  border: 0;
  padding: 8px 0 10px;
  background: none;
  color: var(--muted);
  font-size: 14px;
  white-space: nowrap;
  transition: color 180ms;
}
.tab-index { font-family: var(--serif); font-size: 13px; font-weight: 650; color: var(--line); transition: color 180ms; }
.tab-name { font-weight: 500; }
.tab-count { color: var(--muted); font-size: 12px; font-weight: 500; font-variant-numeric: tabular-nums; }
.section-tabs .tab:hover { color: var(--ink); }
.section-tabs .tab:hover .tab-index { color: var(--muted); }
.section-tabs .tab.active { color: var(--ink); }
.section-tabs .tab.active .tab-name { font-weight: 700; }
.section-tabs .tab.active .tab-index { color: var(--accent); }
.section-tabs .tab::after {
  content: '';
  position: absolute;
  inset: auto 0 -1px;
  height: 3px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: center;
  transition: transform 210ms var(--ease-soft);
}
.section-tabs .tab.active::after { transform: scaleX(1); }
.section-help { margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }

/* 筛选器保持一条基线：直角、细线、纸面底色，与版式同一套规则语言。 */
.filters { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 13px 24px; margin: 16px 0; animation: brief-reveal 420ms 80ms var(--ease-out) backwards; }
.search {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 230px;
  flex: 1 1 300px;
  max-width: 440px;
  min-height: 42px;
  padding: 0 13px;
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--muted);
  transition: border-color 180ms, box-shadow 180ms;
}
.search:focus-within { border-color: var(--ink-soft); box-shadow: 0 0 0 3px var(--accent-soft); }
.search .icon { width: 16px; height: 16px; }
.search input { width: 100%; min-width: 0; padding: 9px 0; border: 0; color: var(--ink); background: transparent; font-size: 13px; outline: none; }
.search input::placeholder { color: var(--muted); opacity: 1; }
.filter-options { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.open-toggle { position: relative; display: inline-flex; align-items: center; gap: 8px; min-height: 42px; color: var(--ink-soft); font-size: 12px; white-space: nowrap; cursor: pointer; }
.open-toggle input { position: absolute; opacity: 0; width: 30px; height: 18px; margin: 0; left: 0; cursor: pointer; }
.toggle-track { display: inline-flex; align-items: center; width: 29px; height: 17px; padding: 2px; border-radius: 12px; background: var(--line); transition: background .15s; }
.toggle-track::after { content: ''; display: block; width: 13px; height: 13px; border-radius: 50%; background: var(--paper); box-shadow: 0 1px 2px #00000026; transition: transform .15s; }
.open-toggle input:checked + .toggle-track { background: var(--accent); }
.open-toggle input:checked + .toggle-track::after { transform: translateX(12px); }
.open-toggle input:focus-visible + .toggle-track { outline: 3px solid var(--focus); outline-offset: 4px; }
.select-field { display: flex; align-items: center; gap: 7px; }
.select-field > span { color: var(--muted); font-size: 12px; white-space: nowrap; }
.select-field select { min-height: 38px; max-width: 175px; padding: 7px 25px 7px 10px; border: 1px solid var(--line); background: var(--paper); color: var(--ink-soft); font-size: 12px; cursor: pointer; transition: border-color 180ms; }
.select-field select:hover { border-color: var(--muted); }
.active-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin: -2px 0 16px; }
.filter-chip {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 31px;
  max-width: 100%;
  padding: 4px 7px 4px 11px;
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  line-height: 1.7;
  text-align: left;
  animation: chip-reveal 180ms var(--ease-out) backwards;
  transition: border-color 160ms, background 160ms;
}
.filter-chip > span:first-child { min-width: 0; overflow-wrap: anywhere; }
.filter-chip:hover { border-color: var(--accent); }
.chip-close { display: grid; place-items: center; flex-shrink: 0; width: 19px; height: 19px; border-radius: 50%; color: var(--accent); font-size: 16px; line-height: 1; transition: background 160ms; }
.filter-chip:hover .chip-close { background: #ffffff42; }

/* 列表刊头与视图切换：列表为默认阅读轴，时间线按日期纵排；切换时整体淡入滑升。 */
.list-heading { display: flex; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; gap: 10px 24px; margin: 0 0 12px; }
.list-heading h2 { margin: 0; font-family: var(--serif); font-size: 22px; line-height: 1.4; font-weight: 650; letter-spacing: .02em; }
.results-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; color: var(--muted); font-size: 12px; }
#result-count { font-variant-numeric: tabular-nums; }
#reset-filters { min-height: 30px; padding: 3px 0; border: 0; color: var(--accent); background: transparent; font-size: 12px; }
#reset-filters:hover { text-decoration: underline; text-underline-offset: 3px; }
.view-toggle { display: inline-flex; border: 1px solid var(--line); background: var(--paper); }
.view-toggle button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 5px 12px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  transition: color 160ms, background 160ms;
}
.view-toggle button + button { border-left: 1px solid var(--line); }
.view-toggle button:not(.active):hover { color: var(--ink); }
.view-toggle button.active { background: var(--ink); color: var(--paper); font-weight: 600; }
.view-toggle .icon { width: 15px; height: 15px; }

.list-column-labels { display: grid; grid-template-columns: minmax(225px, 1fr) minmax(0, 1.12fr) 224px; margin-bottom: 8px; padding: 5px 26px 7px; color: var(--muted); font-size: 12px; font-weight: 500; letter-spacing: .05em; }
.list-column-labels span:nth-child(1) { padding-right: 26px; }
.list-column-labels span:nth-child(2) { padding: 0 26px; }
.list-column-labels span:nth-child(3) { padding-left: 26px; }
.card-list { display: grid; gap: 14px; animation: view-in 220ms var(--ease-soft); }
.discovery[data-view='timeline'] .list-column-labels,
.discovery[data-view='timeline'] .card-list { display: none; }

/* 条目纸卡：外壳负责报格线、进场与 FLIP；内层负责网格、倾斜与光斑，互不打架。 */
.contest-card {
  position: relative;
  min-width: 0;
  padding: 22px 26px 0;
  border: 1px solid var(--line);
  border-top: 3px solid var(--rule);
  background: var(--paper);
  box-shadow: var(--shadow-card);
  scroll-margin-top: 24px;
  transition: border-color 200ms, box-shadow 220ms;
}
.contest-card:hover, .contest-card:focus-within { border-color: var(--muted); box-shadow: var(--shadow-card-hover); }
.contest-card[data-urgency='today'] { border-top-color: var(--today); }
.contest-card[data-urgency='soon'] { border-top-color: var(--soon); }
.contest-card[data-urgency='week'] { border-top-color: var(--week); }
/* 光斑跟随：指针位置写入 --mx/--my，卡片 hover 时浮现一圈朱红晕光。 */
.contest-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(300px circle at var(--mx, 50%) var(--my, 50%), var(--accent-soft) 0%, transparent 70%);
  opacity: 0;
  transition: opacity .3s;
  pointer-events: none;
}
@media (hover: hover) { .contest-card:hover::before { opacity: 1; } }
.card-inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(225px, 1fr) minmax(0, 1.12fr) 224px;
  grid-template-areas: 'identity brief action' 'actions actions actions';
  align-items: start;
  min-width: 0;
  transform: perspective(1100px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg));
  transition: transform .18s ease;
}
/* 进场编排：脚本启用 [data-reveal] 后卡片先隐后现，IntersectionObserver 逐张揭示。 */
[data-reveal] .contest-card { opacity: 0; transform: translateY(14px); }
[data-reveal] .contest-card.revealed { opacity: 1; transform: none; }
[data-reveal] .contest-card.revealed {
  transition: opacity .5s var(--ease-soft) var(--reveal-delay, 0ms),
              transform .5s var(--ease-soft) var(--reveal-delay, 0ms),
              border-color 200ms, box-shadow 220ms;
}
.card-identity { grid-area: identity; min-width: 0; padding-right: 26px; }
.card-classification { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; margin: 0 0 10px; line-height: 1.7; }
.grade-tag { color: var(--ink-soft); font-size: 12px; font-weight: 650; letter-spacing: .06em; }
.grade-tag::before { content: ''; display: inline-block; width: 14px; height: 1px; margin-right: 8px; vertical-align: middle; background: var(--accent); }
.recognition-tag { padding-bottom: 1px; border-bottom: 1px dotted var(--muted); color: var(--muted); font-size: 12px; cursor: help; }
.edition { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.card-identity h3 { margin: 0; font-family: var(--serif); color: var(--ink); font-size: 21px; line-height: 1.55; font-weight: 650; letter-spacing: -.2px; overflow-wrap: anywhere; }
.card-tags { display: flex; align-items: center; flex-wrap: wrap; gap: 7px 12px; margin-top: 12px; color: var(--ink-soft); font-size: 12px; }
.state-tag { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-soft); font-size: 12px; line-height: 1.8; }
.state-tag i { width: 5px; height: 5px; border-radius: 50%; background: var(--status); flex-shrink: 0; }
.state-tag.competing i { background: var(--muted); }
.state-tag.upcoming i { background: var(--line); }
.mode-tag, .badge.mode { display: inline-block; padding: 1px 7px; border: 1px solid var(--line); background: var(--paper-raise); color: var(--ink-soft); font-size: 12px; line-height: 1.8; }
.track-count { display: block; margin: 11px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.card-brief { grid-area: brief; min-width: 0; padding: 0 26px; border-left: 1px solid var(--line-soft); border-right: 1px solid var(--line-soft); }
.track-brief + .track-brief { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--line); }
.brief-line { margin-top: 11px; }
.brief-line:first-child { margin-top: 0; }
.brief-line > div { min-width: 0; }
.brief-line > div > span { display: block; margin-bottom: 2px; color: var(--muted); font-size: 12px; line-height: 1.7; }
.brief-line p { margin: 0; color: var(--ink-soft); font-size: 14px; line-height: 1.85; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

/* 日期栏：衬线大字号 + 分级徽章 + 窗口进度条；进度条按日报时点展示提醒窗口已走过多少。 */
.action-node { grid-area: action; min-width: 0; padding-left: 26px; border-left: 1px solid var(--line-soft); color: var(--ink-soft); }
.action-kind { display: block; color: var(--muted); font-size: 11px; font-weight: 650; letter-spacing: .14em; line-height: 1.7; }
.action-time { display: block; }
.action-date-value {
  display: block;
  margin: 5px 0 0;
  font-family: var(--serif);
  color: var(--ink);
  font-size: 27px;
  font-weight: 650;
  line-height: 1.35;
  font-variant-numeric: tabular-nums lining-nums;
  overflow-wrap: normal;
  white-space: normal;
}
.action-clock { display: block; margin-top: 2px; color: var(--ink-soft); font-size: 14px; line-height: 1.6; font-weight: 500; font-variant-numeric: tabular-nums; }
.action-progress { display: block; height: 3px; margin-top: 9px; background: var(--line-soft); overflow: hidden; }
.action-progress i { display: block; height: 100%; background: var(--week); }
.contest-card[data-urgency='today'] .action-progress i { background: var(--today); }
.contest-card[data-urgency='soon'] .action-progress i { background: var(--soon); }
.action-badge, .timeline-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border: 1px solid var(--line);
  font-size: 12px;
  font-weight: 650;
  line-height: 1.75;
  letter-spacing: .04em;
}
.action-badge.today, .timeline-badge.today { background: var(--today); border-color: var(--today); color: var(--today-contrast); }
.action-badge.soon, .timeline-badge.soon { background: var(--soon-bg); border-color: var(--soon-line); color: var(--soon); }
.action-badge.week, .timeline-badge.week { background: var(--week-bg); border-color: var(--week-line); color: var(--week); }
.action-node .action-badge { margin-top: 9px; }
.action-relative { display: block; margin-top: 7px; color: var(--muted); font-size: 12px; line-height: 1.7; font-style: normal; }
.action-date-label { display: block; margin: 8px 0 0; color: var(--ink-soft); font-size: 12px; line-height: 1.75; overflow-wrap: anywhere; }
.action-track { display: block; margin: 7px 0 0; padding-top: 8px; border-top: 1px solid var(--line-soft); color: var(--muted); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.contest-card[data-urgency='today'] .action-date-value { color: var(--today); }
.contest-card[data-urgency='soon'] .action-date-value { color: var(--soon); }
.contest-card[data-urgency='week'] .action-date-value { color: var(--week); }
/* “今日截止”的卡片让报格线呼吸一下：极轻的辉光脉冲，只此一处连续动效。 */
.contest-card[data-urgency='today'] { animation: urgent-breath 2.6s ease-in-out 1.2s infinite; }

.card-actions { grid-area: actions; display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; min-width: 0; margin-top: 20px; border-top: 1px solid var(--line-soft); }
.rules { flex: 1; min-width: 0; }
.detail-trigger { display: inline-flex; align-items: center; gap: 8px; min-height: 43px; padding: 10px 0; color: var(--accent); font-size: 12px; font-weight: 600; cursor: pointer; list-style: none; }
.detail-trigger::-webkit-details-marker { display: none; }
.detail-trigger .icon { width: 14px; height: 14px; transition: transform .15s; }
.detail-trigger:hover { text-decoration: underline; text-underline-offset: 3px; }
.detail-trigger:hover .icon { transform: translateX(2px); }
.entry-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  margin: 6px 0;
  padding: 5px 11px;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: var(--paper);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  transition: background 180ms, border-color 180ms, color 180ms, transform 180ms;
}
.entry-link .icon { width: 13px; height: 13px; }
.entry-link:hover { background: var(--accent); border-color: var(--accent); color: var(--today-contrast); transform: translateY(-1px); }
.rules-body { padding-bottom: 24px; }

/* 原生 dialog 保留键盘与焦点行为；细则用稳定的字段列阅读，报格线分区。 */
#detail-dialog { width: min(720px, 96vw); max-width: none; height: 100dvh; max-height: none; margin: 0 0 0 auto; padding: 0; border: 0; border-left: 1px solid var(--line); background: var(--paper); color: var(--ink); box-shadow: var(--shadow-drawer); overflow: hidden; }
#detail-dialog::backdrop { background: #221e1561; backdrop-filter: blur(4px); animation: backdrop-reveal 180ms ease-out both; }
#detail-dialog[open] { display: flex; flex-direction: column; animation: drawer-reveal 300ms var(--ease-soft) backwards; }
#detail-dialog[data-closing='true'] { animation: none; }
#detail-dialog[data-closing='true']::backdrop { animation: backdrop-dismiss 180ms ease-in both; }
.drawer-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 28px 32px 22px; border-bottom: 2px solid var(--rule); flex-shrink: 0; }
.drawer-eyebrow { color: var(--accent); font-size: 10px; font-weight: 650; letter-spacing: .24em; }
.drawer-header h2 { margin: 8px 0 7px; font-family: var(--serif); color: var(--ink); font-size: 24px; line-height: 1.5; font-weight: 650; overflow-wrap: anywhere; }
.drawer-header p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.8; }
.icon-button { display: grid; place-items: center; flex-shrink: 0; width: 36px; height: 36px; border: 1px solid var(--line); background: var(--paper); color: var(--ink-soft); transition: background 160ms, border-color 160ms, color 160ms; }
.icon-button .icon { width: 18px; height: 18px; }
.icon-button:hover { background: var(--paper-raise); border-color: var(--muted); color: var(--ink); }
.drawer-body { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 0 32px 30px; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }
.drawer-content { padding-top: 7px; }
.track-detail { padding: 23px 0; border-top: 1px solid var(--line); }
.drawer-content > .track-detail:first-child, .rules-body > .track-detail:first-child { border-top: 0; }
.track-detail h4 { margin: 0 0 15px; font-family: var(--serif); color: var(--ink); font-size: 17px; line-height: 1.65; font-weight: 650; overflow-wrap: anywhere; }
.track-detail dl { margin: 0; }
.fact { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 15px; padding: 8px 0; line-height: 1.85; }
.fact dt { color: var(--muted); font-size: 12px; padding-top: 2px; overflow-wrap: anywhere; }
.fact dd { margin: 0; color: var(--ink-soft); font-size: 14px; line-height: 1.9; overflow-wrap: anywhere; }
.track-links { display: flex; flex-direction: column; gap: 16px; margin-top: 18px; color: var(--accent); font-size: 13px; line-height: 1.8; }
.track-links > a { align-self: flex-start; font-weight: 600; }
.track-links a:hover { text-decoration: underline; text-underline-offset: 3px; }
.source-links { display: flex; flex-direction: column; gap: 7px; padding: 13px 15px; border: 1px solid var(--line); background: var(--paper-raise); }
.source-links a { color: var(--accent); font-size: 12px; line-height: 1.85; overflow-wrap: anywhere; }
.subtopics { margin: 15px 0 0; padding: 3px 15px; border-left: 2px solid var(--accent-line); background: var(--paper-raise); }
.subtopics p { color: var(--ink-soft); font-size: 14px; line-height: 1.9; overflow-wrap: anywhere; }
.subtopics b { display: block; margin-bottom: 3px; color: var(--ink); font-size: 14px; font-weight: 650; }
.recognition { margin: 18px 0; padding: 12px 14px; border: 1px solid var(--line); background: var(--paper-raise); color: var(--ink-soft); font-size: 12px; line-height: 1.9; }

/* 时间线：左轨日期、右侧行动，颜色与徽章体系同源；点击条目直达细则面板。 */
.timeline-view { display: grid; animation: view-in 220ms var(--ease-soft); }
.timeline-view:empty { display: none; }
.timeline-day { display: grid; grid-template-columns: 172px minmax(0, 1fr); border-bottom: 1px solid var(--line); scroll-margin-top: 24px; }
.timeline-day:first-child { border-top: 1px solid var(--line); }
.timeline-day.hz-flash { animation: day-flash 1.2s var(--ease-soft); }
.timeline-rail { padding: 19px 20px 17px 0; border-right: 1px solid var(--line); }
.timeline-rail time { display: block; font-family: var(--serif); font-size: 18px; font-weight: 650; line-height: 1.35; font-variant-numeric: tabular-nums; }
.rail-weekday { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }
.timeline-rail .timeline-badge { margin-top: 9px; }
.timeline-day[data-urgency='today'] .timeline-rail time { color: var(--today); }
.timeline-day[data-urgency='soon'] .timeline-rail time { color: var(--soon); }
.timeline-day[data-urgency='week'] .timeline-rail time { color: var(--week); }
.timeline-entries { min-width: 0; }
.timeline-entry {
  display: grid;
  grid-template-columns: 118px minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 2px 18px;
  width: 100%;
  padding: 13px 6px 13px 20px;
  border: 0;
  border-bottom: 1px dashed var(--line-soft);
  background: none;
  text-align: left;
  transition: background 140ms;
}
.timeline-entry:last-child { border-bottom: 0; }
.timeline-entry:hover { background: var(--paper-raise); }
.entry-kind { color: var(--muted); font-size: 11px; font-weight: 650; letter-spacing: .1em; line-height: 1.9; }
.timeline-entry[data-kind='registration_end'] .entry-kind,
.timeline-entry[data-kind='submission_deadline'] .entry-kind { color: var(--accent); }
.entry-main { min-width: 0; }
.entry-contest { display: block; font-family: var(--serif); color: var(--ink); font-size: 15.5px; font-weight: 650; line-height: 1.55; overflow-wrap: anywhere; }
.timeline-entry:hover .entry-contest { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.entry-track { display: block; color: var(--muted); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.entry-tail { display: inline-flex; align-items: center; gap: 10px; justify-self: end; font-variant-numeric: tabular-nums; }
.entry-tail .action-badge { margin: 0; }
.entry-clock { color: var(--ink-soft); font-size: 13px; font-weight: 500; }
.entry-relative { color: var(--muted); font-size: 12px; }

#empty-state { padding: 70px 24px; border: 1px dashed var(--line); background: var(--paper); text-align: center; }
.empty-icon { display: inline-grid; place-items: center; width: 48px; height: 48px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); }
.empty-icon .icon { width: 21px; height: 21px; }
#empty-state h3 { margin: 17px 0 8px; font-family: var(--serif); color: var(--ink); font-size: 18px; font-weight: 650; }
#empty-state p { margin: 0; color: var(--muted); font-size: 14px; }
#empty-reset { display: inline-flex; align-items: center; gap: 8px; min-height: 41px; margin-top: 23px; padding: 9px 16px; border: 0; background: var(--ink); color: var(--paper); font-size: 13px; font-weight: 600; }
#empty-reset .icon { width: 16px; height: 16px; }
.page-footer { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 10px 24px; margin-top: 28px; padding: 20px 0 30px; border-top: 2px solid var(--rule); color: var(--muted); font-size: 12px; line-height: 1.85; }
.page-footer a { color: var(--accent); }
.page-footer a:hover { text-decoration: underline; text-underline-offset: 3px; }
kbd { padding: 1px 5px; border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 3px; background: var(--paper); font: 600 10px/1.6 var(--sans); color: var(--ink-soft); }

/* 动效只反馈进入与操作；赛事重排由脚本 FLIP 控制，卡片 hover 不占用 transform。 */
@keyframes brief-reveal {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}
@keyframes chip-reveal {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: none; }
}
@keyframes drawer-reveal {
  from { opacity: .35; transform: translateX(28px); }
  to { opacity: 1; transform: none; }
}
@keyframes backdrop-reveal {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes backdrop-dismiss {
  from { opacity: 1; }
  to { opacity: 0; }
}
@keyframes seal-stamp {
  0% { opacity: 0; transform: scale(1.9) rotate(-12deg); }
  55% { opacity: 1; transform: scale(.93) rotate(2deg); }
  100% { transform: none; }
}
@keyframes char-drop {
  from { opacity: 0; transform: translateY(.35em) rotate(2deg); }
  to { opacity: 1; transform: none; }
}
@keyframes view-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}
@keyframes hz-rise {
  from { opacity: 0; transform: translateY(7px); }
  to { opacity: 1; transform: none; }
}
@keyframes live-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: .5; }
}
@keyframes day-flash {
  0% { background: var(--accent-soft); }
  100% { background: transparent; }
}
@keyframes urgent-breath {
  0%, 100% { box-shadow: var(--shadow-card); }
  50% { box-shadow: var(--shadow-card), 0 -3px 18px -6px var(--today); }
}

@media (max-width: 1120px) {
  .daily-shell { width: calc(100% - 64px); }
  .section-tabs { gap: 22px; }
  .nameplate h1 { font-size: 46px; }
  .list-column-labels, .card-inner { grid-template-columns: minmax(205px, 1fr) minmax(0, 1.06fr) 204px; }
  .list-column-labels { padding: 5px 22px 7px; }
  .list-column-labels span:nth-child(1) { padding-right: 22px; }
  .list-column-labels span:nth-child(2) { padding: 0 22px; }
  .list-column-labels span:nth-child(3) { padding-left: 22px; }
  .contest-card { padding: 20px 22px 0; }
  .card-identity { padding-right: 22px; }
  .card-brief { padding: 0 22px; }
  .action-node { padding-left: 22px; }
  .card-identity h3 { font-size: 20px; }
  .filter-options { gap: 12px; }
  .search { max-width: 350px; }
  .select-field select { max-width: 150px; }
  .timeline-day { grid-template-columns: 150px minmax(0, 1fr); }
  .focus-hero { padding: 22px 24px 18px; }
  .horizon { padding: 14px 24px 18px; }
}

@media (max-width: 900px) {
  .daily-shell { width: calc(100% - 48px); }
  .masthead { padding-top: 12px; }
  .utility-bar { flex-wrap: wrap; }
  .nameplate { padding-top: 24px; }
  .nameplate h1 { font-size: 42px; }
  .dateline::before, .dateline::after { flex-basis: 60px; }
  .section-tabs { gap: 22px; overflow-x: auto; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }
  .section-tabs .tab { flex-shrink: 0; min-height: 44px; font-size: 13px; }
  .filters { align-items: flex-start; gap: 12px; }
  .search { max-width: none; flex-basis: 100%; }
  .filter-options { width: 100%; justify-content: flex-start; gap: 12px 20px; }
  .list-column-labels { display: none; }
  .contest-card { padding: 22px 24px 0; }
  .card-inner { grid-template-columns: minmax(0, 1fr) 208px; grid-template-areas: 'identity action' 'brief brief' 'actions actions'; }
  .card-identity { padding-right: 0; }
  .action-node { padding-left: 24px; }
  .card-brief { border: 0; border-top: 1px solid var(--line-soft); margin-top: 18px; padding: 17px 0 0; }
  .track-brief { max-width: 660px; }
  .card-identity h3 { font-size: 20px; }
  .timeline-day { grid-template-columns: minmax(0, 1fr); }
  .timeline-rail { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; padding: 15px 0 8px; border-right: 0; border-bottom: 1px dashed var(--line-soft); }
  .timeline-rail time { font-size: 16px; }
  .rail-weekday { margin: 0; }
  .timeline-rail .timeline-badge { margin: 0; }
  .timeline-entry { padding-left: 0; }
  .focus-hero { flex-wrap: wrap; gap: 18px; }
  .hero-ring { width: 112px; height: 112px; }
}

@media (max-width: 620px) {
  .daily-shell { width: calc(100% - 36px); }
  .utility-bar { gap: 12px; }
  .brand-copy small { display: none; }
  .utility-actions { gap: 10px; }
  .theme-switch button { padding: 5px 9px; }
  .nameplate { padding-top: 20px; }
  .masthead-eyebrow { font-size: 11px; letter-spacing: .3em; text-indent: .3em; }
  .nameplate h1 { font-size: 36px; letter-spacing: .22em; text-indent: .22em; }
  .dateline { gap: 4px 9px; font-size: 12px; }
  .issue-meta { gap: 4px 10px; font-size: 12px; }
  .focus-panel { margin-top: 18px; }
  .focus-hero { flex-direction: column; align-items: flex-start; padding: 20px 19px 16px; gap: 14px; }
  .hero-title { font-size: 23px; }
  .cd-cell { min-width: 56px; padding: 7px 8px 6px; }
  .cd-num { font-size: 25px; }
  .hero-countdown { flex-wrap: wrap; }
  .horizon { padding: 13px 19px 17px; }
  .horizon-cells { grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .section-tabs { gap: 20px; margin-right: -18px; padding-right: 18px; scrollbar-width: none; }
  .section-tabs::-webkit-scrollbar { display: none; }
  .section-help { margin-top: 7px; font-size: 12px; }
  .filters { margin-bottom: 14px; gap: 11px; }
  .list-heading { align-items: center; gap: 6px 12px; margin-bottom: 10px; }
  .list-heading h2 { font-size: 19px; }
  .results-meta { gap: 10px; }
  .contest-card { padding: 20px 19px 0; scroll-margin-top: 15px; }
  .card-inner { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'identity' 'action' 'brief' 'actions'; }
  .card-classification { gap: 5px 11px; margin-bottom: 8px; }
  .card-identity h3 { font-size: 20px; }
  .card-tags { gap: 6px 11px; margin-top: 11px; }
  .action-node { border-left: 0; border-top: 1px solid var(--line-soft); margin-top: 16px; padding: 15px 0 0; }
  .action-date-value { font-size: 25px; }
  .action-node .action-badge { margin-top: 8px; }
  .card-brief { margin-top: 17px; padding-top: 15px; }
  .brief-line { margin-top: 12px; }
  .card-actions { gap: 12px; margin-top: 18px; flex-wrap: wrap; }
  .detail-trigger { min-height: 48px; padding: 13px 0; }
  .entry-link { min-height: 44px; margin: 2px 0; padding: 8px 10px; }
  .timeline-entry { grid-template-columns: minmax(0, 1fr); gap: 1px 0; padding: 12px 0; }
  .entry-tail { justify-self: start; margin-top: 3px; }
  .page-footer { flex-direction: column; gap: 6px; margin-top: 23px; padding: 18px 0 25px; }
  #empty-state { padding: 50px 19px; }
  #detail-dialog { width: 100vw; border-left: 0; }
  .drawer-header { padding: 22px 21px 18px; gap: 15px; }
  .drawer-header h2 { font-size: 21px; }
  .drawer-body { padding: 0 21px 24px; }
  .track-detail { padding: 21px 0; }
  .fact { grid-template-columns: minmax(0, 1fr); gap: 3px; padding: 9px 0; }
  .fact dt { padding: 0; }
  .source-links { padding: 11px 12px; }
  .subtopics { padding: 3px 12px; }
}

@media (max-width: 380px) {
  .daily-shell { width: calc(100% - 28px); }
  .contest-card { padding-left: 16px; padding-right: 16px; }
  .card-actions { gap: 0 16px; }
  .rules { flex-basis: 100%; }
  .entry-link { min-height: 40px; padding: 7px 10px; margin: 0 0 10px; }
  .cd-cell { min-width: 48px; }
  .hero-title { font-size: 21px; }
}

/* 减少动态效果：进场、倾斜、辉光全部退场，信息照常呈现。 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation: none !important; transition: none !important; }
  [data-reveal] .contest-card { opacity: 1; transform: none; }
  .contest-card::before { display: none; }
  .card-inner { transform: none; }
}

@media print {
  @page { margin: 15mm; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
  body { background: white; font-size: 10pt; }
  body::before, #scroll-progress, .focus-panel, .utility-actions, .section-nav, .filters, .active-filters,
  .results-meta, .view-toggle, .list-column-labels, .card-actions, #detail-dialog, #empty-state, #timeline-view { display: none !important; }
  .daily-shell { width: 100%; max-width: none; }
  .masthead { padding-top: 0; }
  .utility-bar { border-bottom-color: #2b2519; }
  .nameplate { padding-top: 14px; }
  .nameplate h1 { font-size: 26pt; letter-spacing: .2em; }
  .masthead-eyebrow { font-size: 9pt; }
  .dateline { font-size: 9pt; margin-top: 10px; }
  .issue-meta { border-color: #2b2519; color: #221e15; margin-top: 14px; margin-bottom: 14pt; }
  .issue-meta b { color: #221e15; }
  .card-list { gap: 0; }
  .contest-card {
    padding: 14pt 0;
    border: 0;
    border-bottom: 1px solid #999999;
    box-shadow: none;
    background: white;
    break-inside: avoid;
    opacity: 1 !important;
    transform: none !important;
  }
  .card-inner { display: grid; grid-template-columns: minmax(0, 1fr) 150px; grid-template-areas: 'identity action' 'brief brief'; column-gap: 20pt; transform: none; }
  .card-identity { padding-right: 0; }
  .card-identity h3 { font-size: 14pt; }
  .card-brief { border-top: 1px solid #dddddd; margin-top: 10pt; padding: 8pt 0 0; border-left: 0; border-right: 0; }
  .action-node { border-left: 1px solid #dddddd; padding-left: 10pt; }
  .brief-line p { display: block; overflow: visible; font-size: 9.5pt; }
  .action-date-value { font-size: 15pt; }
  .action-badge, .timeline-badge { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .page-footer { border-color: #2b2519; margin-top: 18pt; padding: 12pt 0 0; }
}
'''

CSS = (
    ":root {" + LIGHT + SHARED + "}\n"
    ":root[data-theme='dark'] {" + DARK + "}\n"
    "@media (prefers-color-scheme: dark) { :root:not([data-theme='light']):not([data-theme='dark']) {" + DARK + "} }\n"
    + MAIN +
    "\n@media print { :root, :root[data-theme='light'], :root[data-theme='dark'] {" + LIGHT + SHARED + "} }"
)

CSS += "\n.verification-note { margin:8px 0 0; color:var(--muted); font-size:11px; line-height:1.5; }\n"

CSS += "\n.daily-status {padding:12px 16px; border:1px solid var(--muted); color:var(--ink-soft); font-size:13px; line-height:1.6;}\n"
