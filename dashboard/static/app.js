const $ = (id) => document.getElementById(id);
const fmtMoney = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--';
const fmt = (v) => Number.isFinite(Number(v)) ? Number(v).toFixed(2) : '--';
const pct = (v) => Number.isFinite(Number(v)) ? `${(Number(v) * 100).toFixed(2)}%` : '--';
const dayPct = (v) => Number.isFinite(Number(v)) ? `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%` : '--';
const clsByNum = (v) => Number(v) >= 0 ? 'up' : 'down';
let askExpanded = false;
let candidatesExpanded = false;
let activeMainTab = 'positions';
let expandedReturnDate = '';
let activeReturnPeriod = 'month';
let activeReturnType = 'daily';
let activeReturnValue = 'amount';
let activeStockView = 'heat';
let activeReturnMonth = '';
let bloggerDrawerOpen = false;
let latestBloggerPosts = [];
let latestBloggerRuntime = {};
const renderCache = {};
const seenBloggerAlerts = new Set(JSON.parse(localStorage.getItem('seenBloggerAlerts') || '[]'));

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function rowEmpty(text) { return `<div class="empty">${text}</div>`; }

function updateHtmlIfChanged(id, html, signature = html) {
  if (renderCache[id] === signature) return;
  renderCache[id] = signature;
  $(id).innerHTML = html;
}

function setAskExpanded(expanded) {
  askExpanded = expanded;
  const section = $('askSection');
  const panel = $('askPanel');
  const content = $('askContent');
  const btn = $('askToggleBtn');
  if (!panel || !content || !btn) return;
  if (section) {
    section.hidden = !expanded;
    section.classList.toggle('is-collapsed', !expanded);
  }
  panel.classList.toggle('is-collapsed', !expanded);
  content.hidden = !expanded;
  btn.textContent = expanded ? '收起问股' : 'AI问股';
  btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
}

function setCandidatesExpanded(expanded) {
  candidatesExpanded = expanded;
  const layout = $('mainLayout');
  const panel = $('candidatePanel');
  const btn = $('candidateToggleBtn');
  if (!layout || !panel || !btn) return;
  panel.hidden = !expanded;
  layout.classList.toggle('candidates-collapsed', !expanded);
  btn.textContent = expanded ? '收起候选' : '候选池';
  btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
}

function setMainTab(tab) {
  activeMainTab = tab === 'returns' ? 'returns' : 'positions';
  document.querySelectorAll('[data-main-tab]').forEach((btn) => {
    const active = btn.getAttribute('data-main-tab') === activeMainTab;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const positionsPanel = $('positionsTabPanel');
  const returnsPanel = $('returnsTabPanel');
  const dashboard = $('dashboardPage');
  if (dashboard) dashboard.classList.toggle('returns-active', activeMainTab === 'returns');
  if (positionsPanel) positionsPanel.hidden = activeMainTab !== 'positions';
  if (returnsPanel) returnsPanel.hidden = activeMainTab !== 'returns';
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function rememberBloggerAlert(id) {
  if (!id) return;
  seenBloggerAlerts.add(id);
  localStorage.setItem('seenBloggerAlerts', JSON.stringify([...seenBloggerAlerts].slice(-160)));
}

function ensureAlertStack() {
  let stack = $('alertStack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'alertStack';
    stack.className = 'alert-stack';
    document.body.appendChild(stack);
  }
  return stack;
}

function showBloggerPopup(alertItem) {
  const post = alertItem?.post || {};
  const id = String(post.stable_id || post.id || alertItem?.time || '');
  if (!id || seenBloggerAlerts.has(id)) return;
  rememberBloggerAlert(id);
  const stack = ensureAlertStack();
  const card = document.createElement('button');
  card.type = 'button';
  card.className = 'post-popup';
  const stocks = (post.stocks || []).slice(0, 4).map(code => `<span>${escapeHtml(code)}</span>`).join('');
  card.innerHTML = `
    <div class="post-popup-head">
      <strong>博主新动态</strong>
      <small>${escapeHtml(post.time || alertItem.time || '')}</small>
    </div>
    <div class="post-popup-text">${escapeHtml(post.text || post.title || '同花顺圈子有新帖')}</div>
    ${stocks ? `<div class="post-popup-stocks">${stocks}</div>` : ''}
  `;
  card.onclick = () => {
    if (post.url) window.open(post.url, '_blank', 'noopener');
    card.remove();
  };
  stack.appendChild(card);
  setTimeout(() => card.classList.add('is-visible'), 20);
  setTimeout(() => {
    card.classList.remove('is-visible');
    setTimeout(() => card.remove(), 260);
  }, 15000);
}

function consumeBloggerAlerts(alerts) {
  for (const item of alerts || []) showBloggerPopup(item);
}

function setBloggerDrawerOpen(open) {
  bloggerDrawerOpen = open;
  const drawer = $('bloggerDrawer');
  const btn = $('bloggerToggleBtn');
  if (!drawer || !btn) return;
  drawer.hidden = !open;
  drawer.classList.toggle('is-open', open);
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  btn.textContent = open ? '收起动态' : '动态';
  if (open) renderBloggerDrawer();
}

function renderBloggerDrawer() {
  const meta = $('bloggerDrawerMeta');
  const list = $('bloggerDrawerList');
  if (!list) return;
  const rt = latestBloggerRuntime || {};
  if (meta) {
    meta.textContent = rt.blogger_last_error
      ? `异常：${rt.blogger_last_error}`
      : `最近检查 ${rt.blogger_last_check_at || '--'}`;
  }
  if (!latestBloggerPosts.length) {
    list.innerHTML = rowEmpty('暂无可显示动态。');
    return;
  }
  list.innerHTML = latestBloggerPosts.slice().reverse().map((post) => {
    const stocks = (post.stocks || []).slice(0, 4).map(code => `<span>${escapeHtml(code)}</span>`).join('');
    return `
      <button class="blogger-post-item" type="button" data-post-url="${escapeHtml(post.url || '')}">
        <small>${escapeHtml(post.time || '')}</small>
        <strong>${escapeHtml(post.text || post.title || '同花顺圈子动态')}</strong>
        ${stocks ? `<em>${stocks}</em>` : ''}
      </button>`;
  }).join('');
}

function renderCandidates(rows) {
  if (!rows?.length) return rowEmpty('暂无行情，点击“立即决策”或等待刷新。');
  return rows.slice(0, 12).map(r => `
    <div class="row">
      <span class="mono">${r.symbol}</span>
      <b>${r.name || ''}</b>
      <span class="${Number(r.pct_chg) >= 0 ? 'up' : 'down'}">${fmt(r.pct_chg)}%</span>
      <span>${fmt(r.price)}</span>
      <span class="badge">${fmt(r.score)}</span>
      <span class="reason">卖一 ${fmt(r.ask1)} / 买一 ${fmt(r.bid1)} / spread ${fmt(r.spread_pct)}%</span>
    </div>`).join('');
}

function renderRuleCandidateRows(rows, emptyText) {
  if (!rows?.length) return rowEmpty(emptyText);
  return rows.slice(0, 12).map((r) => {
    const tags = (r.risk_tags || []).slice(0, 3).map(tag => `<small>${escapeHtml(tag)}</small>`).join('');
    const reason = r.reason ? `<div class="rule-reason">${escapeHtml(r.reason)}</div>` : '';
    return `
      <div class="rule-candidate-row">
        <div>
          <b>${escapeHtml(r.symbol || '')}</b>
          <span>${escapeHtml(r.name || '')}</span>
        </div>
        <strong>${fmt(r.score)}</strong>
        <em class="${Number(r.pct_chg) >= 0 ? 'up' : 'down'}">${fmt(r.pct_chg)}%</em>
        <span>开盘后 ${Number.isFinite(Number(r.relative_open_gain)) ? pct(r.relative_open_gain) : '--'}</span>
        <span>${escapeHtml(r.score_basis || '')}</span>
        <div class="rule-tags">${tags}</div>
        ${reason}
      </div>`;
  }).join('');
}

function renderRuleCandidatePools(st) {
  const strictRows = st.strategy_signals || [];
  const watchRows = st.strategy_watchlist || [];
  const rightRows = st.right_side_watchlist || [];
  const aiRows = st.ai_buy_candidates || [];
  const diag = st.strategy_diagnostics || {};
  const risks = Object.values(st.announcement_risks || {}).filter(item => item?.blocked);
  return `
    <div class="rule-pool-summary">
      <span>严格符合 <b>${strictRows.length}</b></span>
      <span>观察池 <b>${watchRows.length}</b></span>
      <span>右侧 <b>${rightRows.length}</b></span>
      <span>AI可买 <b>${aiRows.length}</b></span>
      <span>检查 <b>${diag.checked || 0}</b></span>
    </div>
    <div class="rule-pool-section">
      <h3>严格符合规则</h3>
      ${renderRuleCandidateRows(strictRows, '当前没有严格通过原 N 字规则的票。')}
    </div>
    <div class="rule-pool-section">
      <h3>N字观察池</h3>
      ${renderRuleCandidateRows(watchRows, '当前没有 N 字观察票。')}
    </div>
    <div class="rule-pool-section">
      <h3>右侧候选池 · ${rightRows.length}只 · 观察池</h3>
      ${renderRuleCandidateRows(rightRows, '当前没有热门龙头右侧观察票。')}
    </div>
    <div class="rule-pool-section">
      <h3>AI可买池 · ${aiRows.length}只 · 已过教练</h3>
      ${renderRuleCandidateRows(aiRows, '当前 AI 可买池为空。')}
    </div>
    ${risks.length ? `
      <div class="rule-pool-section">
        <h3>公告风险拦截</h3>
        <div class="diag-pool announcement-risk-list">
          ${risks.slice(0, 6).map(item => `
            <span class="diag-pool-item sell">
              <b>${escapeHtml(item.symbol || '')}</b>
              ${escapeHtml(item.reason || '')}
            </span>`).join('')}
        </div>
      </div>` : ''}
  `;
}

function renderStrategyDiagnostics(diag, aiPool, announcementRisks) {
  if (!diag || !Number(diag.checked)) return rowEmpty('N字诊断等待行情扫描。');
  const reasons = diag.top_reasons || [];
  const pool = aiPool || [];
  const riskRows = Object.values(announcementRisks || {}).filter(item => item?.blocked);
  const limits = diag.strict_limits || {};
  const limitText = [
    Number.isFinite(Number(limits.max_pct_chg)) ? `涨幅<=${fmt(limits.max_pct_chg)}%` : '',
    Number.isFinite(Number(limits.max_open_ext)) ? `离开盘<=${fmt(Number(limits.max_open_ext) * 100)}%` : '',
    Number.isFinite(Number(limits.max_prev_ext)) ? `离昨收<=${fmt(Number(limits.max_prev_ext) * 100)}%` : '',
  ].filter(Boolean).join(' · ');
  return `
    <div class="diag-head">
      <strong>N字诊断</strong>
      <span>${diag.time || '--'} · 检查 ${diag.checked || 0} 只 · 严格 ${diag.passed || 0} 只 · AI池 ${pool.length} 只</span>
    </div>
    <div class="reason">${limitText}</div>
    ${pool.length ? `
      <div class="diag-pool">
        ${pool.slice(0, 6).map(item => `
          <span class="diag-pool-item">
            <b>${escapeHtml(item.symbol || '')}</b>
            ${escapeHtml(item.name || '')}
            <em>${fmt(item.pct_chg)}%</em>
            ${(item.risk_tags || []).slice(0, 2).map(tag => `<small>${escapeHtml(tag)}</small>`).join('')}
          </span>`).join('')}
      </div>` : ''}
    ${riskRows.length ? `
      <div class="diag-pool announcement-risk-list">
        ${riskRows.slice(0, 6).map(item => `
          <span class="diag-pool-item sell">
            <b>${escapeHtml(item.symbol || '')}</b>
            ${escapeHtml(item.reason || '')}
          </span>`).join('')}
      </div>` : ''}
    <div class="diag-list">
      ${reasons.length ? reasons.map(item => `
        <div class="diag-row">
          <span>${escapeHtml(item.reason || '')}</span>
          <b>${item.count || 0}</b>
          <em>${escapeHtml((item.examples || []).join('、'))}</em>
        </div>`).join('') : rowEmpty('当前没有失败项。')}
    </div>`;
}

function renderTSignalsForPosition(symbol, signals) {
  const rows = (signals || []).filter(item => String(item.symbol || '') === String(symbol || ''));
  if (!rows.length) return '';
  return `<div class="t-signal-list">
    ${rows.map(item => `
      <div class="t-signal ${String(item.type || '').toLowerCase()}">
        <span>${escapeHtml(item.type || 'T')}</span>
        <b>${escapeHtml(item.action_hint || '')}</b>
        <em>${item.qty || 0}股 · ${fmt(item.trigger_price)} · ${escapeHtml(item.reason || '')}</em>
      </div>
    `).join('')}
  </div>`;
}

function renderPositions(rows, tSignals = []) {
  if (!rows?.length) return rowEmpty('暂无持仓');
  return `
    <div class="position-list-head">
      <span>股票</span>
      <span>现价</span>
      <span>涨幅</span>
      <span>收益率</span>
      <span>盈亏</span>
    </div>
    ${rows.map(p => `
      <div class="position-card">
        <div class="position-main">
          <b>${escapeHtml(p.name || '')}</b>
          <span class="mono">${escapeHtml(p.symbol || '')}</span>
          <small>${p.qty}股 · 成本 ${fmt(p.avg_cost)} · ${escapeHtml((p.quote_time || '').slice(11, 19) || '--')}</small>
        </div>
        <strong>${fmt(p.last_price)}</strong>
        <em class="${clsByNum(p.pct_chg)}">${dayPct(p.pct_chg)}</em>
        <em class="${clsByNum(p.pnl)}">${pct(p.pnl_pct)}</em>
        <div class="position-pnl ${clsByNum(p.pnl)}">
          <strong>${fmtMoney(p.pnl)}</strong>
          <em class="${clsByNum(p.symbol_total_pnl)}">累计 ${fmtMoney(p.symbol_total_pnl)}</em>
        </div>
        ${renderTSignalsForPosition(p.symbol, tSignals)}
      </div>
    `).join('')}`;
}

function renderOrders(rows) {
  if (!rows?.length) return rowEmpty('暂无模拟订单');
  return rows.slice().reverse().slice(0, 40).map(o => `
    <div class="row">
      <span class="badge ${String(o.side).toUpperCase() === 'SELL' ? 'sell' : 'buy'}">${o.side}</span>
      <span class="mono">${o.symbol}</span>
      <b>${o.name || ''}</b>
      <span>${o.qty}股</span>
      <span>${fmt(o.price)}</span>
      <span>${o.price_source || ''}</span>
      <span class="reason">${o.reason || ''}<br>${o.time || ''}</span>
    </div>`).join('');
}

function renderDecisions(rows) {
  if (!rows?.length) return rowEmpty('暂无AI决策');
  return rows.slice().reverse().slice(0, 18).map(d => {
    const actions = d.actions || [];
    return `
      <div class="decision">
        <div class="decision-head">
          <strong>${escapeHtml(d.time || '')}</strong>
          <span>${escapeHtml(d.source || 'AI')} · ${actions.length || 0} 笔动作</span>
        </div>
        <div class="decision-actions">
          ${actions.length ? actions.map(a => `
            <span class="decision-action ${String(a.action || '').toLowerCase()}">
              <b>${escapeHtml(a.action || 'HOLD')}</b>
              ${escapeHtml(a.symbol || '')}
              ${a.qty ? `<small>${a.qty}股</small>` : ''}
            </span>`).join('') : '<span class="decision-action hold"><b>HOLD</b> 无动作</span>'}
        </div>
        <div class="reason">${escapeHtml(d.summary || '')}</div>
      </div>`;
  }).join('');
}

function reviewHasT1IntradayOnly(review) {
  const rows = review?.intraday_rows || [];
  return rows.length > 0 && !rows.some(row => row?.can_sell_today === true);
}

function sanitizeT1ReviewText(text) {
  return String(text || '')
    .replaceAll('弱市环境下冲高未及时移动止盈导致利润回吐', '今日新仓受T+1限制无法盘中卖出，弱市冲高回落导致浮盈回吐，需明日可卖后按移动止盈/止损处理')
    .replaceAll('没有把盘中浮盈转化为移动止盈/分批止盈', '今日新仓T+1不可卖，盘中浮盈只能作为明日可卖后的风险处理依据')
    .replaceAll('未能把盘中浮盈转化为移动止盈/分批止盈', '今日新仓T+1不可卖，盘中浮盈只能作为明日可卖后的风险处理依据')
    .replaceAll('未在高点部分止盈', '今日新仓T+1不可卖，不能要求当日高点止盈')
    .replaceAll('未及时移动止盈', '今日新仓T+1不可卖，不能归责为当日未移动止盈；明日可卖后再执行移动止盈')
    .replaceAll('未及时止盈', '今日新仓T+1不可卖，不能归责为当日未止盈；明日可卖后再执行止盈')
    .replaceAll('应执行移动止盈规则', '明日可卖后应执行移动止盈规则')
    .replaceAll('必须移动止盈或分批止盈', '若为可卖持仓才移动止盈或分批止盈；今日新仓只能记录冲高回落风险')
    .replaceAll('启动移动止盈或分批止盈', '明日可卖后启动移动止盈或分批止盈')
    .replaceAll('至少锁定一部分利润', '可卖后至少锁定一部分利润')
    .replaceAll('不能归责为当日未止盈；明日可卖后再执行止盈，明日可卖后应执行移动止盈规则', '不能归责为当日未止盈；明日可卖后再执行移动止盈规则');
}

function sanitizeReviewForDisplay(review) {
  if (!reviewHasT1IntradayOnly(review)) return review || {};
  return {
    ...(review || {}),
    summary: sanitizeT1ReviewText(review?.summary || ''),
    wins: (review?.wins || []).map(sanitizeT1ReviewText),
    losses: (review?.losses || []).map(sanitizeT1ReviewText),
    next_rules: (review?.next_rules || []).map(sanitizeT1ReviewText),
  };
}

function renderReviews(rows) {
  if (!rows?.length) return rowEmpty('暂无复盘');
  const latest = sanitizeReviewForDisplay([...rows].reverse()[0]);
  const confidence = Number.isFinite(Number(latest.confidence)) ? Number(latest.confidence).toFixed(2) : '--';
  const dayPnl = Number.isFinite(Number(latest.day_pnl)) ? Number(latest.day_pnl) : Number(latest.realized_pnl || 0) + Number(latest.unrealized_pnl || 0);
  return `
    <div class="review-card">
      <strong>${latest.review_date || ''} · ${latest.review_source || 'local'} · 当日综合 ${fmtMoney(dayPnl)} / ${pct(latest.day_pnl_pct)} · 已实现 ${fmtMoney(latest.realized_pnl)} · 持仓浮盈 ${fmtMoney(latest.unrealized_pnl)}</strong>
      <div class="reason">${latest.summary || ''}</div>
      <div class="review-grid">
        <span class="badge ${Number(latest.total_pnl) >= 0 ? 'buy' : 'sell'}">总盈亏 ${fmtMoney(latest.total_pnl)}</span>
        <span class="badge ${Number(latest.realized_pnl) >= 0 ? 'buy' : 'sell'}">已实现 ${fmtMoney(latest.realized_pnl)}</span>
        <span class="badge ${Number(latest.unrealized_pnl) >= 0 ? 'buy' : 'sell'}">持仓浮盈 ${fmtMoney(latest.unrealized_pnl)}</span>
        <span class="badge ${dayPnl >= 0 ? 'buy' : 'sell'}">当日综合 ${fmtMoney(dayPnl)}</span>
        <span class="badge">${latest.trade_count || 0} 笔</span>
        <span class="badge">${confidence}</span>
      </div>
      <div class="reason">做得好：${(latest.wins || []).join(' · ') || '无'}</div>
      <div class="reason">需要改：${(latest.losses || []).join(' · ') || '无'}</div>
      <div class="reason">下次规则：${(latest.next_rules || []).join(' · ') || '无'}</div>
    </div>`;
}

function parseReturnDate(value) {
  const parts = String(value || '').slice(0, 10).split('-').map(Number);
  if (parts.length !== 3 || parts.some(n => !Number.isFinite(n))) return null;
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  return date.getFullYear() === parts[0] && date.getMonth() === parts[1] - 1 && date.getDate() === parts[2] ? date : null;
}

function monthKeyFromDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function returnAmountClass(value) {
  const n = Number(value || 0);
  if (n > 0) return 'is-profit';
  if (n < 0) return 'is-loss';
  return 'is-flat';
}

function selectedReturnMonth(rows) {
  if (activeReturnMonth) return activeReturnMonth;
  const selected = parseReturnDate(expandedReturnDate);
  if (selected) return monthKeyFromDate(selected);
  const dates = (rows || []).map(row => parseReturnDate(row.date)).filter(Boolean).sort((a, b) => a - b);
  return monthKeyFromDate(dates[dates.length - 1] || new Date());
}

function latestReturnDate(rows) {
  return (rows || []).map(row => parseReturnDate(row.date)).filter(Boolean).sort((a, b) => a - b).at(-1) || new Date();
}

function filteredReturnRows(rows, monthKey) {
  const latest = latestReturnDate(rows);
  const latestTime = latest.getTime();
  return (rows || []).filter(row => {
    const date = parseReturnDate(row.date);
    if (!date) return false;
    if (activeReturnPeriod === 'today') return date.getTime() === latestTime;
    if (activeReturnPeriod === 'month') return monthKeyFromDate(date) === monthKey;
    if (activeReturnPeriod === 'quarter') {
      const start = new Date(latest.getFullYear(), latest.getMonth() - 2, 1);
      return date >= start && date <= latest;
    }
    if (activeReturnPeriod === 'year') return date.getFullYear() === latest.getFullYear();
    return true;
  });
}

function renderToggleTabs(items, active, attrName, extraClass = '') {
  return items.map(item => `
    <button class="${item.value === active ? 'is-active' : ''} ${extraClass}" type="button" ${attrName}="${item.value}">
      ${item.label}
    </button>`).join('');
}

function renderReturnCalendar(rows, monthKey) {
  const byDate = new Map((rows || []).map(row => [String(row.date || '').slice(0, 10), row]));
  const [year, month] = monthKey.split('-').map(Number);
  const first = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells = [];
  for (let i = 0; i < first.getDay(); i += 1) cells.push({ type: 'blank' });
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    cells.push({ type: 'day', day, date, row: byDate.get(date) });
  }
  while (cells.length % 7 !== 0) cells.push({ type: 'blank' });
  return `
    <div class="returns-calendar-head">${['日', '一', '二', '三', '四', '五', '六'].map(day => `<span>${day}</span>`).join('')}</div>
    <div class="returns-calendar-grid">
      ${cells.map(cell => {
        if (cell.type === 'blank') return '<div class="calendar-cell is-blank"></div>';
        const pnlValue = Number(cell.row?.pnl || 0);
        return `
          <button class="calendar-cell ${returnAmountClass(pnlValue)} ${expandedReturnDate === cell.date ? 'is-active' : ''}" type="button" data-return-date="${escapeHtml(cell.date)}">
            <span>${String(cell.day).padStart(2, '0')}</span>
            ${cell.row ? `<strong>${activeReturnValue === 'rate' ? pct(cell.row.return_pct) : `${pnlValue >= 0 ? '+' : ''}${Math.round(pnlValue)}`}</strong>` : '<em></em>'}
          </button>`;
      }).join('')}
    </div>`;
}

function aggregateStockRows(rows) {
  const bySymbol = new Map();
  for (const row of rows || []) {
    for (const item of row.details || []) {
      const symbol = String(item.symbol || '');
      if (!symbol) continue;
      const existing = bySymbol.get(symbol) || { symbol, name: item.name || '', pnl: 0, count: 0 };
      existing.name = existing.name || item.name || '';
      existing.pnl += Number(item.pnl || 0);
      existing.count += 1;
      bySymbol.set(symbol, existing);
    }
  }
  return [...bySymbol.values()].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
}

function renderStockProfitList(stocks) {
  if (!stocks.length) return rowEmpty('当前区间还没有可拆到个股的盈亏。');
  return `
    <div class="stock-profit-list">
      ${stocks.map(item => `
        <div class="stock-profit-row">
          <div><b>${escapeHtml(item.name || item.symbol)}</b><span>${escapeHtml(item.symbol)}</span></div>
          <strong class="${clsByNum(item.pnl)}">${item.pnl >= 0 ? '+' : ''}${fmtMoney(item.pnl)}</strong>
        </div>`).join('')}
    </div>`;
}

function renderAllTimeStockLedger(rows) {
  if (!rows?.length) return rowEmpty('暂无按股票累计盈亏。');
  return `
    <div class="stock-profit-list">
      ${rows.slice(0, 18).map(item => `
        <div class="stock-profit-row">
          <div>
            <b>${escapeHtml(item.name || '')}</b>
            <span class="mono">${escapeHtml(item.symbol || '')}</span>
          </div>
          <small>当前${item.current_qty || 0}股 · 买${item.buy_count || 0}次 / 卖${item.sell_count || 0}次</small>
          <strong class="${clsByNum(item.total_pnl)}">${Number(item.total_pnl || 0) >= 0 ? '+' : ''}${fmtMoney(item.total_pnl)}</strong>
        </div>`).join('')}
    </div>`;
}

function renderStockHeatmap(stocks) {
  if (!stocks.length) return rowEmpty('当前区间还没有可拆到个股的盈亏。');
  const maxAbs = Math.max(...stocks.map(item => Math.abs(item.pnl)), 1);
  return stocks.slice(0, 16).map(item => {
    const weight = Math.max(108, Math.min(360, 118 + Math.abs(item.pnl) / maxAbs * 260));
    const height = Math.max(78, Math.min(186, weight * 0.52));
    return `
      <div class="stock-heat-cell ${returnAmountClass(item.pnl)}" style="flex-basis:${weight}px; min-height:${height}px">
        <strong>${escapeHtml(item.name || item.symbol)}</strong>
        <span>${escapeHtml(item.symbol)}</span>
        <em>${item.pnl >= 0 ? '+' : ''}${fmtMoney(item.pnl)}</em>
      </div>`;
  }).join('');
}

function groupReturnRows(rows, mode) {
  const groups = new Map();
  for (const row of rows || []) {
    const date = parseReturnDate(row.date);
    if (!date) continue;
    const key = mode === 'year'
      ? `${date.getFullYear()}年`
      : (mode === 'stage' ? '当前区间' : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`);
    const existing = groups.get(key) || { key, pnl: 0, count: 0 };
    existing.pnl += Number(row.pnl || 0);
    existing.count += 1;
    groups.set(key, existing);
  }
  return [...groups.values()];
}

function renderAggregateReturns(rows) {
  const mode = activeReturnType === 'year' ? 'year' : (activeReturnType === 'stage' ? 'stage' : 'month');
  const groups = groupReturnRows(rows, mode);
  if (!groups.length) return rowEmpty('当前区间暂无收益数据。');
  return `
    <div class="returns-aggregate-grid">
      ${groups.map(item => `
        <div class="returns-aggregate-card ${returnAmountClass(item.pnl)}">
          <span>${escapeHtml(item.key)}</span>
          <strong>${item.pnl >= 0 ? '+' : ''}${activeReturnValue === 'rate' ? pct(item.pnl / 100000) : fmtMoney(item.pnl)}</strong>
          <em>${item.count}天</em>
        </div>`).join('')}
    </div>`;
}

function periodStatsForKey(stats, period) {
  const periods = stats?.periods || {};
  if (period === 'today') return periods.daily || null;
  if (period === 'month') return periods.monthly || null;
  if (period === 'year') return periods.yearly || null;
  if (period === 'all') return periods.total || null;
  return null;
}

function renderDailyReturns(rows, stats = {}, stockLedger = []) {
  if (!rows?.length) return rowEmpty('暂无每日收益。');
  const monthKey = selectedReturnMonth(rows);
  if (!activeReturnMonth) activeReturnMonth = monthKey;
  const [year, month] = monthKey.split('-').map(Number);
  const periodRows = filteredReturnRows(rows, monthKey);
  const authoritativePeriod = periodStatsForKey(stats, activeReturnPeriod);
  const periodPnl = authoritativePeriod ? Number(authoritativePeriod.pnl || 0) : periodRows.reduce((sum, row) => sum + Number(row.pnl || 0), 0);
  const periodReturnPct = authoritativePeriod ? Number(authoritativePeriod.return_pct || 0) : periodPnl / 100000;
  const summaryLabel = authoritativePeriod?.label === '总收益' ? '总收益' : `${authoritativePeriod?.label || '区间'}收益`;
  const selectedRow = rows.find(row => String(row.date || '').slice(0, 10) === expandedReturnDate);
  const details = selectedRow?.details || [];
  const stockRows = aggregateStockRows(periodRows);
  const periodTabs = [
    { label: '当日', value: 'today' },
    { label: '本月', value: 'month' },
    { label: '近三月', value: 'quarter' },
    { label: '今年', value: 'year' },
    { label: '全部', value: 'all' },
  ];
  const typeTabs = [
    { label: '日收益', value: 'daily' },
    { label: '月收益', value: 'month' },
    { label: '年收益', value: 'year' },
    { label: '阶段收益', value: 'stage' },
  ];
  return `
    <div class="returns-analysis">
      <div class="returns-period-tabs">${renderToggleTabs(periodTabs, activeReturnPeriod, 'data-return-period')}</div>
      <div class="returns-type-tabs">
        ${renderToggleTabs(typeTabs, activeReturnType, 'data-return-type')}
        <button class="${activeReturnValue === 'rate' ? 'is-active' : ''}" type="button" data-return-value="rate">收益率</button>
      </div>
      <section class="returns-calendar">
        <div class="returns-month-title">
          <button type="button" data-return-month="prev">‹</button>
          <strong>${year}年 ${month}月</strong>
          <button type="button" data-return-month="next">›</button>
        </div>
        ${activeReturnType === 'daily' ? renderReturnCalendar(rows, monthKey) : renderAggregateReturns(periodRows)}
        <div class="returns-month-summary">
          <strong>${escapeHtml(summaryLabel)}：<em class="${clsByNum(periodPnl)}">${periodPnl >= 0 ? '+' : ''}${activeReturnValue === 'rate' ? pct(periodReturnPct) : fmtMoney(periodPnl)}</em></strong>
          <span>${authoritativePeriod ? `总账口径 · ${escapeHtml(authoritativePeriod.start_date || '初始')} 至 ${escapeHtml(authoritativePeriod.end_date || '')}` : `交易日 ${periodRows.length} 天`}</span>
        </div>
      </section>
      ${expandedReturnDate ? `
        <section class="returns-day-detail">
          <h3>${escapeHtml(expandedReturnDate)} 个股盈亏</h3>
          <div class="return-details">
            ${details.length ? details.map(item => {
              const itemPnl = Number(item.pnl || 0);
              return `
                <div class="return-detail-row">
                  <div>
                    <b>${escapeHtml(item.name || '')}</b>
                    <span class="mono">${escapeHtml(item.symbol || '')}</span>
                  </div>
                  <small>${escapeHtml(item.type || '')} · ${item.qty || 0}股</small>
                  <strong class="${clsByNum(itemPnl)}">${fmtMoney(itemPnl)}</strong>
                  <i class="${clsByNum(itemPnl)}">${pct(item.return_pct)}</i>
                </div>`;
            }).join('') : rowEmpty('这一天没有可拆到个股的盈亏明细。')}
          </div>
        </section>` : ''}
      <section class="monthly-stock-heat">
        <div class="monthly-stock-head">
          <h3>区间个股盈亏</h3>
          <div>
            <button class="${activeStockView === 'heat' ? 'is-active' : ''}" type="button" data-stock-view="heat">热力图</button>
            <button class="${activeStockView === 'list' ? 'is-active' : ''}" type="button" data-stock-view="list">列表</button>
          </div>
        </div>
        <div class="stock-heat-grid">${activeStockView === 'list' ? renderStockProfitList(stockRows) : renderStockHeatmap(stockRows)}</div>
      </section>
      <section class="monthly-stock-heat">
        <div class="monthly-stock-head">
          <h3>全部个股累计盈亏</h3>
        </div>
        <div class="stock-heat-grid">${renderAllTimeStockLedger(stockLedger)}</div>
      </section>
    </div>`;
}

function renderAskHistory(rows) {
  if (!rows?.length) return rowEmpty('还没问过股票。');
  return rows.slice().reverse().slice(0, 8).map(item => {
    const symbols = (item.symbol_context || []).map(row => {
      const cls = row.guardrail_ok ? 'buy' : 'sell';
      const pool = row.in_ai_buy_pool ? 'AI池' : (row.n_shape_watch ? 'N观察' : (row.strict_n_shape ? '严格N' : '池外'));
      const vwap = Number.isFinite(Number(row.vwap_deviation_pct)) ? ` · VWAP ${fmt(row.vwap_deviation_pct)}%` : '';
      return `
        <span class="ask-symbol">
          <b>${escapeHtml(row.symbol || '')}</b>
          ${escapeHtml(row.name || '')}
          <em class="${Number(row.pct_chg) >= 0 ? 'up' : 'down'}">${fmt(row.pct_chg)}%</em>
          <small>${pool}</small>
          <small class="${cls}">${row.guardrail_ok ? '风控过' : escapeHtml(row.guardrail_reason || '风控未过')}</small>
          ${vwap ? `<small>${escapeHtml(vwap)}</small>` : ''}
        </span>`;
    }).join('');
    const risks = (item.risk_points || []).map(x => `<span class="badge sell">${escapeHtml(x)}</span>`).join('');
    const steps = (item.analysis_steps || []).map((step, idx) => `
      <div class="ask-step">
        <span>${idx + 1}</span>
        <div>
          <b>${escapeHtml(step.title || '分析')}</b>
          <em>${escapeHtml(step.detail || '')}</em>
        </div>
      </div>
    `).join('');
    return `
      <div class="ask-card">
        <div class="ask-card-head">
          <strong>${escapeHtml(item.time || '')} · ${escapeHtml(item.source || 'local')} · ${escapeHtml(item.verdict || '观察')}</strong>
        </div>
        <div class="ask-question">${escapeHtml(item.question || '')}</div>
        ${steps ? `<div class="ask-steps"><h4>分析过程</h4>${steps}</div>` : ''}
        <div class="reason">${escapeHtml(item.answer || '')}</div>
        ${symbols ? `<div class="ask-symbols">${symbols}</div>` : ''}
        ${risks ? `<div class="ask-risks">${risks}</div>` : ''}
      </div>`;
  }).join('');
}

function renderLogs(rows) {
  if (!rows?.length) return rowEmpty('暂无日志');
  return rows.slice().reverse().slice(0, 24).map(item => `
    <div class="log-item">
      <strong>${item.time || ''}</strong>
      <div class="reason">${item.msg || ''}</div>
    </div>`).join('');
}

async function refresh() {
  const data = await api('/api/status');
  const rt = data.runtime || {};
  const acc = data.account || {};
  const st = data.state || {};
  const returns = data.return_stats || {};

  const marketOpen = !!rt.market_open;
  const marketSession = rt.market_session || (marketOpen ? 'open' : 'closed');
  $('liveDot').className = `dot ${marketOpen ? (rt.running ? 'busy' : 'live') : ''}`;
  $('watchState').textContent = marketSession === 'lunch'
    ? '午休'
    : (!marketOpen ? '休市' : (rt.running ? 'AI决策中' : (rt.watching ? '盯盘中' : '已暂停')));
  const buyLockText = rt.ai_buy_blocked_no_sellable ? ' · 满仓且无可卖，AI买入暂停' : '';
  $('runtimeMeta').textContent = marketOpen
    ? `行情${data.quote_interval_sec}s / AI${data.ai_interval_sec}s · 可卖${rt.sellable_position_count || 0}只${buyLockText} · 主板${rt.market_scan_cursor || 0}/${rt.market_scan_total || '--'} · 下次复盘 ${rt.next_review_at || '--'} · Nautilus ${rt.nautilus_ok ? rt.nautilus_version : '未检测'} · DeepSeek ${rt.deepseek_enabled ? '已接入' : '未配置'}${rt.last_error ? ` · ${rt.last_error}` : ''}`
    : `${marketSession === 'lunch' ? '午休' : '休市'} · 可卖${rt.sellable_position_count || 0}只${buyLockText} · 下次开盘 ${rt.market_next_open_at || '--'} · 下次复盘 ${rt.next_review_at || '--'} · 主板${rt.market_scan_cursor || 0}/${rt.market_scan_total || '--'} · DeepSeek ${rt.deepseek_enabled ? '已接入' : '未配置'}`;

  $('totalValue').textContent = fmtMoney(acc.total_value);
  $('cash').textContent = fmtMoney(acc.cash);
  $('marketValue').textContent = fmtMoney(acc.market_value);
  $('pnl').textContent = `${fmtMoney(acc.total_pnl)} / ${pct(acc.total_pnl_pct)}`;
  $('pnl').className = clsByNum(acc.total_pnl);
  $('returnsMeta').textContent = returns.as_of || '--';
  if (activeMainTab === 'returns') {
    updateHtmlIfChanged('dailyReturns', renderDailyReturns(returns.daily_rows || [], returns, acc.stock_pnl_ledger || []), JSON.stringify([
      returns.daily_rows || [],
      returns.periods || {},
      acc.stock_pnl_ledger || [],
      expandedReturnDate,
      activeReturnPeriod,
      activeReturnType,
      activeReturnValue,
      activeStockView,
      activeReturnMonth,
    ]));
  }

  $('quoteTime').textContent = rt.last_quote_at || '--';
  $('marketProgress').textContent = `${rt.market_scan_cursor || 0}/${rt.market_scan_total || '--'}`;
  $('posCount').textContent = `${acc.positions?.length || 0}只`;
  $('orderCount').textContent = `${st.orders?.length || 0}条`;
  $('aiSource').textContent = rt.last_decision_at || '--';

  if (candidatesExpanded) {
    updateHtmlIfChanged('candidates', renderRuleCandidatePools(st), JSON.stringify([
      st.strategy_signals || [],
      st.strategy_watchlist || [],
      st.right_side_watchlist || [],
      st.ai_buy_candidates || [],
      st.strategy_diagnostics || {},
      st.announcement_risks || {},
    ]));
    updateHtmlIfChanged('strategyDiagnostics', '', 'hidden');
  }
  $('positions').innerHTML = renderPositions(acc.positions || [], st.t_signals || []);
  updateHtmlIfChanged('orders', renderOrders(st.orders || []), JSON.stringify((st.orders || []).slice(-60)));
  updateHtmlIfChanged('decisions', renderDecisions(st.decisions || []), JSON.stringify((st.decisions || []).slice(-40)));
  updateHtmlIfChanged('reviews', renderReviews(st.reviews || []), JSON.stringify((st.reviews || []).slice(-8)));
  $('reviewMeta').textContent = st.reviews?.length ? (st.reviews[st.reviews.length - 1].review_date || '--') : '--';
  window.__lastAskHistory = st.ai_ask_history || [];
  if (askExpanded) updateHtmlIfChanged('askHistory', renderAskHistory(st.ai_ask_history || []), JSON.stringify((st.ai_ask_history || []).slice(-8)));
  updateHtmlIfChanged('logs', renderLogs(st.logs || []), JSON.stringify((st.logs || []).slice(-24)));

  $('startBtn').disabled = !!rt.watching || !marketOpen;
  $('stopBtn').disabled = !rt.watching;
  $('decideBtn').disabled = !marketOpen;
}

async function refreshBloggerAlerts() {
  const data = await api('/api/blogger-alerts');
  latestBloggerPosts = data.posts || [];
  latestBloggerRuntime = data.runtime || {};
  if (bloggerDrawerOpen) renderBloggerDrawer();
  consumeBloggerAlerts(data.alerts || []);
}

$('startBtn').onclick = async () => { await api('/api/start', { method: 'POST' }); await refresh(); };
$('stopBtn').onclick = async () => { await api('/api/stop', { method: 'POST' }); await refresh(); };
$('decideBtn').onclick = async () => { await api('/api/decide', { method: 'POST' }); await refresh(); };
document.querySelectorAll('[data-main-tab]').forEach((btn) => {
  btn.onclick = () => {
    setMainTab(btn.getAttribute('data-main-tab'));
    refresh();
  };
});
if ($('candidateToggleBtn')) {
  $('candidateToggleBtn').onclick = () => {
    setCandidatesExpanded(!candidatesExpanded);
    if (candidatesExpanded) refresh();
  };
}
if ($('askToggleBtn')) {
  $('askToggleBtn').onclick = () => {
    setAskExpanded(!askExpanded);
    if (askExpanded) {
      $('askHistory').innerHTML = renderAskHistory(window.__lastAskHistory || []);
      $('askInput')?.focus();
    }
  };
}
if ($('bloggerToggleBtn')) {
  $('bloggerToggleBtn').onclick = () => setBloggerDrawerOpen(!bloggerDrawerOpen);
}
if ($('bloggerCloseBtn')) {
  $('bloggerCloseBtn').onclick = () => setBloggerDrawerOpen(false);
}
if ($('bloggerDrawerList')) {
  $('bloggerDrawerList').onclick = (event) => {
    const item = event.target.closest('[data-post-url]');
    const url = item?.getAttribute('data-post-url');
    if (url) window.open(url, '_blank', 'noopener');
  };
}
async function submitAskQuestion() {
  const question = $('askInput').value.trim();
  if (!question) return;
  if ($('askBtn').disabled) return;
  $('askBtn').disabled = true;
  $('askBtn').textContent = '分析中';
  try {
    await api('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    $('askInput').value = '';
    await refresh();
  } catch (err) {
    alert(err.message || '问股失败');
  } finally {
    $('askBtn').disabled = false;
    $('askBtn').textContent = '问一下';
  }
}
if ($('askBtn')) $('askBtn').onclick = submitAskQuestion;
if ($('askInput')) {
  $('askInput').addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    submitAskQuestion();
  });
}
$('dailyReturns').onclick = (event) => {
  const periodBtn = event.target.closest('[data-return-period]');
  const typeBtn = event.target.closest('[data-return-type]');
  const valueBtn = event.target.closest('[data-return-value]');
  const monthBtn = event.target.closest('[data-return-month]');
  const stockBtn = event.target.closest('[data-stock-view]');
  const dateBtn = event.target.closest('[data-return-date]');
  if (periodBtn) {
    activeReturnPeriod = periodBtn.getAttribute('data-return-period') || 'month';
    if (activeReturnPeriod !== 'today') expandedReturnDate = '';
  } else if (typeBtn) {
    activeReturnType = typeBtn.getAttribute('data-return-type') || 'daily';
  } else if (valueBtn) {
    activeReturnValue = activeReturnValue === 'rate' ? 'amount' : 'rate';
  } else if (monthBtn) {
    const current = selectedReturnMonth([]);
    const [year, month] = current.split('-').map(Number);
    const next = new Date(year, month - 1 + (monthBtn.getAttribute('data-return-month') === 'next' ? 1 : -1), 1);
    activeReturnMonth = monthKeyFromDate(next);
    expandedReturnDate = '';
  } else if (stockBtn) {
    activeStockView = stockBtn.getAttribute('data-stock-view') || 'heat';
  } else if (dateBtn) {
    const date = dateBtn.getAttribute('data-return-date') || '';
    expandedReturnDate = expandedReturnDate === date ? '' : date;
    const parsed = parseReturnDate(date);
    if (parsed) activeReturnMonth = monthKeyFromDate(parsed);
  } else {
    return;
  }
  renderCache.dailyReturns = '';
  refresh();
};

setMainTab(activeMainTab);
refresh().catch(console.error);
refreshBloggerAlerts().catch(() => {});
setInterval(() => refresh().catch(() => {}), 1000);
setInterval(() => refreshBloggerAlerts().catch(() => {}), 15000);
