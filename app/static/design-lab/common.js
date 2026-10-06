/* Standalone design prototypes: all data and interactions remain in this page. */
(() => {
  'use strict';
  const records = [
    { role: '前端开发工程师', date: '10 月 04 日 · 14:30', mode: '标准模式', score: 88.4, status: '已完成', note: '组件设计清晰，建议补充性能指标与优化前后的对比。' },
    { role: 'Web 全栈工程师', date: '10 月 02 日 · 10:15', mode: '压力模式', score: 79.2, status: '已完成', note: '能够说明技术选型，异常处理和数据一致性还需要更深入。' },
    { role: '前端开发工程师', date: '09 月 29 日 · 16:00', mode: '标准模式', score: 93.0, status: '已完成', note: '项目经历表达完整，问题定位方法和协作案例表现突出。' },
  ];
  const iconPaths = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    chart: '<path d="M4 4v16h16M8 15l4-5 4 2 4-7"/>',
    book: '<path d="M12 5v15m0-15C9 3 5 3 3 5v14c3-2 6-2 9 1 3-3 6-3 9-1V5c-2-2-6-2-9 0Z"/>',
    file: '<path d="M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8M8 16h6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    play: '<path d="m9 5 11 7-11 7V5Z"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
  };
  document.querySelectorAll('[data-icon]').forEach(el => {
    el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[el.dataset.icon] || iconPaths.grid}</svg>`;
  });
  const escape = value => String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  document.querySelectorAll('[data-records]').forEach(el => {
    el.innerHTML = `<div class="table-wrap"><table><caption class="sr-only">最近三次模拟面试记录，均为示例数据</caption><thead><tr><th scope="col">面试岗位</th><th scope="col">模式</th><th scope="col">综合得分</th><th scope="col">状态</th><th scope="col"><span class="sr-only">操作</span></th></tr></thead><tbody>${records.map((r, i) => `<tr><td><strong>${r.role}</strong><small>${r.date}</small></td><td>${r.mode}</td><td class="score-cell">${r.score.toFixed(1)}</td><td><span class="status">${r.status}</span></td><td><button class="text-button" data-report="${i}" aria-label="查看${r.date}的${r.role}报告">查看报告 ↗</button></td></tr>`).join('')}</tbody></table></div>`;
  });
  document.querySelectorAll('[data-chart]').forEach((el, i) => {
    const id = `chart-fill-${i}`;
    el.innerHTML = `<svg class="line-chart" viewBox="0 0 640 180" role="img" aria-label="最近七次面试分数为 68、74、72、82、79、93、88.4 分，总体呈上升趋势"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop stop-color="currentColor" stop-opacity=".16"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs><g class="chart-grid" stroke="currentColor" stroke-opacity=".12" stroke-dasharray="3 6"><path d="M35 25H620M35 75H620M35 125H620"/></g><path d="M35 138C65 138 97 101 132 100S195 119 229 117 290 62 327 63 389 91 425 84 486 22 523 25 586 49 620 45V165H35Z" fill="url(#${id})"/><path d="M35 138C65 138 97 101 132 100S195 119 229 117 290 62 327 63 389 91 425 84 486 22 523 25 586 49 620 45" fill="none" stroke="currentColor" stroke-width="3"/><g fill="currentColor"><circle cx="35" cy="138" r="4"/><circle cx="132" cy="100" r="4"/><circle cx="229" cy="117" r="4"/><circle cx="327" cy="63" r="4"/><circle cx="425" cy="84" r="4"/><circle cx="523" cy="25" r="4"/><circle cx="620" cy="45" r="5"/></g><g fill="currentColor" opacity=".65" font-size="11"><text x="30" y="179">09/16</text><text x="219" y="179">09/23</text><text x="415" y="179">09/29</text><text x="584" y="179">10/04</text></g></svg>`;
  });
  document.querySelectorAll('[data-skills]').forEach(el => {
    el.innerHTML = [['专业知识', 88], ['逻辑表达', 84], ['项目经验', 91], ['应变能力', 72]].map(([label, score]) => `<div class="skill"><div><span>${label}</span><strong>${score}</strong></div><meter min="0" max="100" value="${score}">${score} 分</meter></div>`).join('');
  });
  document.querySelectorAll('[data-week]').forEach(el => {
    el.innerHTML = ['一', '二', '三', '四', '五', '六', '日'].map((d, i) => `<span class="week-day ${i < 4 ? 'done' : ''}"><b>${i < 4 ? '✓' : '·'}</b><small>${d}</small></span>`).join('');
  });
  const dialog = document.createElement('dialog');
  dialog.className = 'demo-dialog';
  dialog.setAttribute('aria-labelledby', 'dialog-title');
  dialog.innerHTML = '<button class="dialog-close" aria-label="关闭弹窗">×</button><div id="dialog-content"></div>';
  document.body.append(dialog);
  const content = dialog.querySelector('#dialog-content');
  let opener;
  function open(html) { opener = document.activeElement; content.innerHTML = html; dialog.showModal(); }
  function close() { dialog.close(); opener?.focus(); }
  dialog.querySelector('.dialog-close').addEventListener('click', close);
  dialog.addEventListener('click', e => { if (e.target === dialog) { const b = dialog.getBoundingClientRect(); if (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom) close(); } });
  document.addEventListener('click', e => {
    const report = e.target.closest('[data-report]');
    if (report) {
      const r = records[Number(report.dataset.report)] || records[0];
      open(`<p class="eyebrow">示例面试报告</p><h2 id="dialog-title">${r.role}</h2><p>${r.date} · ${r.mode}</p><div class="report-number">${r.score.toFixed(1)}<small> / 100</small></div><h3>面试官反馈</h3><p>${r.note}</p><p class="demo-note">这是设计预览中的示例报告。</p>`);
    }
    const start = e.target.closest('[data-start]');
    if (start) open('<p class="eyebrow">准备下一次练习</p><h2 id="dialog-title">设置模拟面试</h2><p>用一次有针对性的练习，验证你的进步。</p><form id="setup-form"><label for="role">目标岗位</label><select id="role" name="role"><option>前端开发工程师</option><option>Web 全栈工程师</option><option>产品经理</option></select><label for="mode">面试难度</label><select id="mode" name="mode"><option>标准模式</option><option>新手模式</option><option>压力模式</option></select><button class="button primary" type="submit">进入面试预览 →</button></form><p class="demo-note">设计预览 · 不会创建真实面试或调用 AI 服务。</p>');
    const resource = e.target.closest('[data-resource]');
    if (resource) open(`<p class="eyebrow">学习资料预览</p><h2 id="dialog-title">${escape(resource.dataset.resource)}</h2><p>练习目标：用清楚的结构解释你的思考过程。</p><ol class="resource-outline"><li>先说明问题背景和约束条件。</li><li>解释方案选择，以及你放弃了什么。</li><li>用具体结果证明方案有效。</li></ol><p class="demo-note">建议用 STAR 结构整理一个真实项目案例。</p>`);
    const resume = e.target.closest('[data-resume]');
    if (resume) open('<p class="eyebrow">简历预览</p><h2 id="dialog-title">林同学 · 前端开发</h2><p>计算机应用技术 · 2027 届</p><h3>项目经历</h3><p>校园活动报名平台：负责组件设计、表单验证与列表性能优化。</p><h3>下一步建议</h3><p>为项目经历补充加载时间、使用人数和你承担的具体职责。</p><p class="demo-note">示例简历，不读取你的真实资料。</p>');
    const nav = e.target.closest('[data-scroll]');
    if (nav) {
      const target = document.getElementById(nav.dataset.scroll);
      if (target) { target.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }); document.querySelectorAll('[data-scroll]').forEach(n => { n.classList.remove('active'); n.removeAttribute('aria-current'); }); nav.classList.add('active'); nav.setAttribute('aria-current', 'location'); }
    }
  });
  document.addEventListener('submit', e => {
    if (e.target.id === 'setup-form') {
      e.preventDefault();
      const role = e.target.elements.role.value;
      const mode = e.target.elements.mode.value;
      content.innerHTML = `<p class="eyebrow">${escape(mode)} · 第一题</p><h2 id="dialog-title">${escape(role)}</h2><p>请介绍一个你最近参与的项目，你负责什么，遇到了哪些挑战？</p><form id="answer-form"><label for="answer">你的回答</label><textarea id="answer" name="answer" rows="5" required minlength="10" placeholder="可以按照背景、任务、行动、结果来组织回答。"></textarea><button class="button primary" type="submit">查看示例反馈 →</button></form><p class="demo-note">本地交互预览，不会录音或上传回答。</p>`;
      content.querySelector('textarea').focus();
    } else if (e.target.id === 'answer-form') {
      e.preventDefault();
      content.innerHTML = '<p class="eyebrow">示例反馈</p><h2 id="dialog-title">让项目经历更具体</h2><p>补充你的个人职责、一个关键技术决策，以及可以量化的结果。</p><p class="demo-note">此反馈为固定示例，未对你的回答进行 AI 分析。</p><button class="button primary" data-close>完成预览</button>';
      content.querySelector('[data-close]').addEventListener('click', close);
      content.querySelector('button').focus();
    } else if (e.target.id === 'task-form') {
      e.preventDefault();
      const title = e.target.elements.task.value.trim();
      if (!title) return;
      const card = document.createElement('article');
      card.className = 'task-card'; card.draggable = true;
      card.innerHTML = `<span class="task-tag">自主练习</span><h3>${escape(title)}</h3><p>刚刚添加 · 本次预览有效</p><button class="text-button" data-move>移至下一阶段 →</button>`;
      document.querySelector('[data-column="0"] .task-list').append(card); updateCounts(); close();
    }
  });
  // Keyboard-accessible stage buttons complement pointer drag-and-drop.
  const columns = [...document.querySelectorAll('[data-column]')];
  function updateCounts() { columns.forEach(c => { c.querySelector('.column-count').textContent = c.querySelectorAll('.task-card').length; }); }
  document.querySelector('[data-add-task]')?.addEventListener('click', () => open('<p class="eyebrow">练习计划</p><h2 id="dialog-title">添加一项任务</h2><form id="task-form"><label for="task">任务名称</label><input id="task" name="task" required maxlength="60" placeholder="例如：练习事件循环的讲解"><button type="submit" class="button primary">添加到待练习</button></form>'));
  document.addEventListener('click', e => {
    const move = e.target.closest('[data-move]');
    if (!move) return;
    const card = move.closest('.task-card'); const current = card.closest('[data-column]');
    const next = columns[(Number(current.dataset.column) + 1) % columns.length];
    next.querySelector('.task-list').append(card); updateCounts(); move.focus();
    document.getElementById('board-status').textContent = `已将「${card.querySelector('h3').textContent}」移至${next.querySelector('h2').textContent}`;
  });
  let dragged;
  document.addEventListener('dragstart', e => { const card = e.target.closest('.task-card'); if (!card) return; dragged = card; e.dataTransfer.setData('text/plain', card.querySelector('h3').textContent); });
  columns.forEach(column => {
    column.addEventListener('dragover', e => { e.preventDefault(); column.classList.add('drag-over'); });
    column.addEventListener('dragleave', () => column.classList.remove('drag-over'));
    column.addEventListener('drop', e => { e.preventDefault(); column.classList.remove('drag-over'); if (dragged) { column.querySelector('.task-list').append(dragged); updateCounts(); document.getElementById('board-status').textContent = `已将任务移至${column.querySelector('h2').textContent}`; dragged = null; } });
  });
  updateCounts();
})();
