(() => {
  'use strict';
  const concepts = [
    { id:'01', file:'01-studio.html', name:'企业工作台', tag:'蓝白 · 侧栏 · 产品感', description:'清晰的导航，克制的蓝色，适合日常高频使用。', bg:'#f2f5fc', accent:'#3e63d4' },
    { id:'02', file:'02-editorial.html', name:'编辑杂志', tag:'纸色 · 衬线 · 分栏', description:'以个人成长手记为线索，像阅读一本关于自己的刊物。', bg:'#f0e8d8', accent:'#9a7249' },
    { id:'03', file:'03-terminal.html', name:'终端控制台', tag:'暗绿 · 等宽 · 高密度', description:'方形面板与诊断日志，将训练过程呈现为可读的数据控制台。', bg:'#162019', accent:'#a9ce81' },
    { id:'04', file:'04-brutal.html', name:'先锋粗野主义', tag:'酸黄 · 硬边 · 巨字', description:'硬边、偏移阴影和直接的表达，强调立即行动。', bg:'#eeefe6', accent:'#c5e93e' },
    { id:'05', file:'05-zen.html', name:'自然极简', tag:'鼠尾草 · 留白 · 日程', description:'自然色调与从容留白，把注意力放回每天可以完成的练习。', bg:'#f0f2e9', accent:'#75865c' },
    { id:'06', file:'06-glass.html', name:'午夜玻璃', tag:'深青 · 通透 · 悬浮', description:'悬浮图标导航与不对称玻璃面板，形成沉浸的个人训练空间。', bg:'#142f2d', accent:'#85d7b5' },
    { id:'07', file:'07-playful.html', name:'柔彩创意', tag:'蜜桃 · 圆角 · 图形', description:'友善的图形和柔和彩色，让练习更轻松、更有陪伴感。', bg:'#fff1e7', accent:'#b982a0' },
    { id:'08', file:'08-swiss.html', name:'瑞士国际主义', tag:'朱红 · 网格 · 数字', description:'严格网格与醒目数字，以简练的视觉秩序表达成长。', bg:'#faf8f2', accent:'#c93f31' },
    { id:'09', file:'09-board.html', name:'计划看板', tag:'淡紫 · 任务 · 工作流', description:'把准备拆成待练习、练习中、已复盘，任务可以拖动和推进。', bg:'#f3eff8', accent:'#987dbc' },
    { id:'10', file:'10-academy.html', name:'经典学院', tag:'酒红 · 目录 · 研习', description:'以课程目录和能力评估组织页面，体现专业与长期积累。', bg:'#f5efe4', accent:'#79483f' },
  ];
  const $ = selector => document.querySelector(selector);
  let favorites = new Set();
  try { const stored = JSON.parse(localStorage.getItem('interview-design-favorites') || '[]'); if (Array.isArray(stored)) favorites = new Set(stored.filter(id => concepts.some(c => c.id === id))); } catch { /* Storage can be unavailable for local files or private browsing. */ }
  let selected = 0;
  let comparing = false;
  let comparisonIndex = 1;
  let viewport = 'desktop';
  function renderCards() {
    $('#concept-list').innerHTML = concepts.map((c, i) => `<button class="concept-card" data-concept="${i}" aria-pressed="${i === selected}" aria-label="预览方案 ${c.id}：${c.name}" style="--concept-bg:${c.bg};--concept-accent:${c.accent}" ${$('#favorites-only').checked && !favorites.has(c.id) ? 'hidden' : ''}><span class="concept-swatch" aria-hidden="true"><span class="swatch-sidebar"></span><span class="swatch-main"><b></b><i></i></span></span><span class="concept-label"><strong>${c.name}</strong><small>${c.tag}</small></span><span class="concept-id">${c.id}</span>${favorites.has(c.id) ? '<span class="concept-star" aria-hidden="true">★</span>' : ''}</button>`).join('');
    $('#favorite-count').textContent = favorites.size;
    $('#empty-favorites').hidden = !$('#favorites-only').checked || favorites.size > 0;
  }
  function updateFavorite() {
    const active = favorites.has(concepts[selected].id);
    $('#favorite-button').setAttribute('aria-pressed', active);
    $('#favorite-button').textContent = active ? '★ 已收藏' : '☆ 收藏方案';
  }
  function updateComparisonOptions() {
    if (comparisonIndex === selected) comparisonIndex = (selected + 1) % concepts.length;
    $('#compare-select').innerHTML = concepts.map((c, i) => `<option value="${i}" ${i === selected ? 'disabled' : ''} ${i === comparisonIndex ? 'selected' : ''}>${c.id} · ${c.name}</option>`).join('');
  }
  function updateComparison() {
    updateComparisonOptions();
    const c = concepts[comparisonIndex];
    $('#left-label').textContent = `${concepts[selected].id} · ${concepts[selected].name}`;
    $('#right-label').textContent = `${c.id} · ${c.name}`;
    $('#comparison-controls').hidden = !comparing;
    $('#second-wrap').hidden = !comparing;
    $('#left-label').hidden = !comparing;
    $('#preview-stage').classList.toggle('comparing', comparing);
    $('#compare-button').setAttribute('aria-pressed', comparing);
    $('#compare-button').textContent = comparing ? '⇄ 退出比较' : '⇄ 并排比较';
    if (comparing && $('#comparison').getAttribute('src') !== c.file) $('#comparison').src = c.file;
    $('#comparison').title = `${c.id} ${c.name}对比预览`;
  }
  function select(index, updateHash = true) {
    selected = (index + concepts.length) % concepts.length;
    const c = concepts[selected];
    $('#selected-number').textContent = c.id;
    $('#selected-name').textContent = c.name;
    $('#selected-description').textContent = c.description;
    $('#page-position').textContent = `${c.id} / 10`;
    $('#open-page').href = c.file;
    $('#preview').title = `${c.id} ${c.name}设计预览`;
    if ($('#preview').getAttribute('src') !== c.file) $('#preview').src = c.file;
    const focusedIndex = document.activeElement?.dataset?.concept;
    renderCards(); updateFavorite(); updateComparison();
    if (focusedIndex !== undefined) document.querySelector(`[data-concept="${focusedIndex}"]`)?.focus({preventScroll:true});
    if (updateHash) { try { history.replaceState(null, '', `#${c.id}`); } catch { /* file:// environments may restrict history. */ } }
    $('#lab-status').textContent = `正在预览方案 ${c.id}，${c.name}`;
  }
  $('#concept-list').addEventListener('click', e => { const b = e.target.closest('[data-concept]'); if (b) select(Number(b.dataset.concept)); });
  $('#previous').addEventListener('click', () => select(selected - 1));
  $('#next').addEventListener('click', () => select(selected + 1));
  $('#favorite-button').addEventListener('click', () => {
    const id = concepts[selected].id;
    if (favorites.has(id)) favorites.delete(id); else favorites.add(id);
    try { localStorage.setItem('interview-design-favorites', JSON.stringify([...favorites])); } catch { /* Session-only favorites still work. */ }
    renderCards(); updateFavorite();
    $('#lab-status').textContent = `${concepts[selected].name}${favorites.has(id) ? '已收藏' : '已取消收藏'}`;
  });
  $('#favorites-only').addEventListener('change', renderCards);
  $('#compare-button').addEventListener('click', () => { comparing = !comparing; updateComparison(); });
  $('#compare-select').addEventListener('change', e => { comparisonIndex = Number(e.target.value); updateComparison(); });
  document.querySelectorAll('[data-viewport]').forEach(button => button.addEventListener('click', () => {
    viewport = button.dataset.viewport; $('#preview-stage').dataset.viewport = viewport;
    document.querySelectorAll('[data-viewport]').forEach(b => b.setAttribute('aria-pressed', b === button));
    $('#lab-status').textContent = `已切换至${button.textContent.trim()}预览`;
  }));
  // Only numerical hashes identify a design; regular section anchors keep working.
  function readHash() { const index = concepts.findIndex(c => `#${c.id}` === location.hash); if (index >= 0) select(index, false); }
  window.addEventListener('hashchange', readHash);
  select(0, false); readHash();
})();
