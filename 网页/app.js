/* global window, document */
/*
  AI 日报 · 每日看板 —— 页面逻辑
  Author: wr

  职责：把 Python 生成的数据渲染成页面，并处理搜索、筛选、收藏、已读、
        主题切换、历史归档、导出 Markdown 这些交互。

  注意：收藏、已读、主题这些只存在浏览器本地（localStorage），
        不会上传到任何地方，换台电脑或清了浏览器数据就会没有。
*/

(function () {
  'use strict';

  // ============================================================
  // 1. 数据与状态
  // ============================================================
  var LS = {
    read: 'ai-info.read',
    star: 'ai-info.star',
    theme: 'ai-info.theme',
    hideRead: 'ai-info.hideRead'
  };

  var DATA = window.__AI_INFO_DATA__ || {};
  var INDEX = window.__AI_INFO_INDEX__ || [];

  var state = {
    date: '',
    query: '',
    category: '全部',
    vendor: '',
    onlyStarred: false,
    hideRead: false,
    shown: 30,
    data: null
  };

  var readSet = loadSet(LS.read);
  var starSet = loadSet(LS.star);

  // 常用元素
  var $ = function (id) { return document.getElementById(id); };
  var el = {
    skeleton: $('skeleton'),
    brandSub: $('brand-sub'),
    modeChip: $('mode-chip'),
    briefingText: $('briefing-text'),
    briefingStats: $('briefing-stats'),
    promoSection: $('promo-section'),
    promoRail: $('promo-rail'),
    promoHint: $('promo-hint'),
    categorySeg: $('category-seg'),
    feed: $('feed'),
    feedEmpty: $('feed-empty'),
    btnMore: $('btn-more'),
    forumSection: $('forum-section'),
    forumGrid: $('forum-grid'),
    vendorSection: $('vendor-section'),
    vendorTabs: $('vendor-tabs'),
    vendorFeed: $('vendor-feed'),
    timelineSection: $('timeline-section'),
    timeline: $('timeline'),
    healthList: $('health-list'),
    healthHint: $('health-hint'),
    keywordCloud: $('keyword-cloud'),
    archiveList: $('archive-list'),
    footerStat: $('footer-stat'),
    footerTime: $('footer-time'),
    starredCount: $('starred-count'),
    topbar: $('topbar'),
    toTop: $('to-top')
  };

  // ============================================================
  // 2. 小工具
  // ============================================================
  function loadSet(key) {
    try {
      var raw = localStorage.getItem(key);
      return new Set(raw ? JSON.parse(raw) : []);
    } catch (e) {
      return new Set();
    }
  }

  function saveSet(key, set) {
    try {
      // 只保留最近用过的，避免本地存储无限膨胀
      var arr = Array.from(set).slice(-4000);
      localStorage.setItem(key, JSON.stringify(arr));
    } catch (e) { /* 存不进去就算了，不影响使用 */ }
  }

  function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** 把命中的关注词高亮出来（先转义再高亮，避免把 HTML 当代码执行） */
  function highlight(text, words) {
    var safe = escapeHtml(text || '');
    if (!words || !words.length) return safe;
    words.slice(0, 6).forEach(function (w) {
      if (!w) return;
      var re = new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
      safe = safe.replace(re, function (m) { return '<mark>' + m + '</mark>'; });
    });
    return safe;
  }

  function truncate(text, len) {
    var s = String(text || '').trim();
    return s.length > len ? s.slice(0, len) + '…' : s;
  }

  /** 把 ISO 时间变成「3 小时前」这种人话 */
  function timeAgo(iso) {
    if (!iso) return '时间未知';
    var then = new Date(iso);
    if (isNaN(then.getTime())) return '时间未知';
    var diff = Date.now() - then.getTime();
    if (diff < 0) diff = 0;
    var min = Math.floor(diff / 60000);
    if (min < 1) return '刚刚';
    if (min < 60) return min + ' 分钟前';
    var hour = Math.floor(min / 60);
    if (hour < 24) return hour + ' 小时前';
    var day = Math.floor(hour / 24);
    if (day < 30) return day + ' 天前';
    var d = then;
    return (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }

  function dateKey(iso) {
    return String(iso || '').slice(0, 10) || '未知日期';
  }

  function heatOf(item) {
    var h = item.heat || {};
    return {
      replies: Number(h.replies || 0),
      participants: Number(h.participants || 0),
      likes: Number(h.likes || 0)
    };
  }

  function starsOf(score) {
    var n = Math.max(1, Math.min(5, Number(score) || 3));
    return '★★★★★'.slice(0, n);
  }

  // ============================================================
  // 3. 数据加载
  // ============================================================
  function availableDates() {
    if (INDEX && INDEX.length) return INDEX.slice();
    return Object.keys(DATA).sort().reverse();
  }

  function loadDate(dateStr, callback) {
    if (DATA[dateStr]) { callback(true); return; }
    var script = document.createElement('script');
    script.src = 'data/数据-' + dateStr + '.js';
    script.onload = function () { callback(true); };
    script.onerror = function () { callback(false); };
    document.head.appendChild(script);
  }

  function switchDate(dateStr) {
    loadDate(dateStr, function (ok) {
      if (!ok) {
        alert('没能载入 ' + dateStr + ' 的数据，可能这个归档已经被清理掉了。');
        return;
      }
      state.date = dateStr;
      state.shown = 30;
      state.vendor = '';
      state.category = '全部';
      renderAll();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // ============================================================
  // 4. 渲染
  // ============================================================
  function currentData() {
    return DATA[state.date] || null;
  }

  function renderAll() {
    var data = currentData();
    if (!data || !data.items) { showNoData(); return; }
    state.data = data;

    renderBriefing(data);
    renderPromo(data);
    renderCategories(data);
    renderFeed();
    renderForums(data);
    renderVendors(data);
    renderTimeline(data);
    renderHealth(data);
    renderKeywords(data);
    renderArchive();
    renderFooter(data);
    updateStarBadge();
  }

  function showNoData() {
    hideSkeleton();
    el.brandSub.textContent = '还没有数据';
    el.briefingText.innerHTML =
      '还没有抓到任何数据。<br>请回到项目根目录，双击 <code>一键刷新.bat</code> 跑一次抓取，' +
      '然后刷新这个页面。';
    el.briefingStats.innerHTML = '';
    el.feedEmpty.hidden = false;
  }

  function hideSkeleton() {
    if (el.skeleton) el.skeleton.classList.add('hidden');
  }

  function renderBriefing(data) {
    var s = data.stats || {};
    el.brandSub.textContent = data.date + ' · 更新于 ' + timeAgo(data.generated_at);

    el.modeChip.textContent = data.mode === 'ai' ? 'AI 智能摘要' : '规则模式';
    el.modeChip.className = 'chip ' + (data.mode === 'ai' ? 'chip-ai' : 'chip-rule');

    el.briefingText.textContent = data.briefing || '暂无简报。';

    var cards = [
      { label: '今日汇总', value: s.total || 0, cls: '' },
      { label: '优惠活动', value: s.promo || 0, cls: 'promo' },
      { label: '数据源', value: (s.sources_ok || 0) + ' / ' + ((s.sources_ok || 0) + (s.sources_fail || 0)), cls: '' }
    ];
    el.briefingStats.innerHTML = cards.map(function (c) {
      return '<div class="bstat ' + c.cls + '"><b>' + c.value + '</b><span>' + c.label + '</span></div>';
    }).join('');
  }

  function renderPromo(data) {
    var promos = data.items.filter(function (i) { return i.is_promo; }).slice(0, 12);
    if (!promos.length) { el.promoSection.hidden = true; return; }
    el.promoSection.hidden = false;
    el.promoHint.textContent = '共 ' + promos.length + ' 条，命中「免费 / 限免 / 折扣」等词';

    el.promoRail.innerHTML = promos.map(function (item) {
      var kw = (item.promo_keywords || []).slice(0, 2)
        .map(function (w) { return '<span class="tag tag-promo">' + escapeHtml(w) + '</span>'; }).join('');
      return '' +
        '<a class="promo-card" href="' + escapeHtml(item.url || '#') + '" target="_blank" rel="noopener" data-id="' + escapeHtml(item.id) + '">' +
          '<div class="promo-top">' +
            '<span class="promo-flag">优惠</span>' +
            (item.vendor ? '<span class="tag tag-vendor">' + escapeHtml(item.vendor) + '</span>' : '') +
          '</div>' +
          '<div class="promo-title">' + highlight(truncate(item.title, 46), item.matched_keywords) + '</div>' +
          '<div class="promo-summary">' + escapeHtml(truncate(item.summary_ai || item.summary_raw, 70)) + '</div>' +
          '<div class="promo-foot">' + kw + '<span class="meta-sep">·</span><span>' + timeAgo(item.published_at) + '</span></div>' +
        '</a>';
    }).join('');
  }

  function renderCategories(data) {
    var cats = Object.keys((data.stats && data.stats.categories) || {});
    var list = ['全部'].concat(cats);
    el.categorySeg.innerHTML = list.map(function (c) {
      return '<button role="tab" data-cat="' + escapeHtml(c) + '"' +
        (c === state.category ? ' class="active"' : '') + '>' +
        escapeHtml(c) + ((data.stats.categories && data.stats.categories[c]) ? ' ' + data.stats.categories[c] : '') +
        '</button>';
    }).join('');
  }

  function getFilteredItems() {
    var data = state.data;
    if (!data) return [];
    var q = state.query.trim().toLowerCase();

    return data.items.filter(function (item) {
      if (state.category !== '全部' && item.category !== state.category) return false;
      if (item.category === '更新日志' || item.category === '开源项目') {
        // 这两类在时间线里单独展示，主列表里不重复出现
        if (state.category === '全部') return false;
      }
      if (state.onlyStarred && !starSet.has(item.id)) return false;
      if (state.hideRead && readSet.has(item.id)) return false;
      if (q) {
        var hay = [item.title, item.summary_ai, item.summary_raw, item.vendor, item.source_name,
                   (item.tags || []).join(' ')].join(' ').toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
  }

  function renderFeed() {
    var items = getFilteredItems();
    var slice = items.slice(0, state.shown);

    el.feedEmpty.hidden = items.length > 0;
    el.btnMore.hidden = items.length <= state.shown;

    el.feed.innerHTML = slice.map(function (item, index) {
      var heat = heatOf(item);
      var isRead = readSet.has(item.id);
      var isStar = starSet.has(item.id);

      var tags = '';
      tags += '<span class="tag tag-source">' + escapeHtml(item.source_name || '未知来源') + '</span>';
      if (item.vendor) tags += '<span class="tag tag-vendor">' + escapeHtml(item.vendor) + '</span>';
      if (heat.replies) tags += '<span class="tag tag-heat">' + heat.replies + ' 回复</span>';
      if (heat.participants) tags += '<span class="tag">' + heat.participants + ' 人参与</span>';
      if (item.cluster_size > 1) tags += '<span class="tag tag-more">' + item.cluster_size + ' 个源报道</span>';
      (item.matched_keywords || []).slice(0, 3).forEach(function (w) {
        tags += '<span class="tag tag-kw">' + escapeHtml(w) + '</span>';
      });

      return '' +
        '<article class="item' + (isRead ? ' read' : '') + (isStar ? ' starred' : '') + '" data-id="' + escapeHtml(item.id) + '" style="animation-delay:' + Math.min(index * 12, 240) + 'ms">' +
          '<div class="score"><span class="stars">' + starsOf(item.score) + '</span><span class="num">' + (item.score || 3) + '</span></div>' +
          '<div class="item-main">' +
            '<a class="item-title" href="' + escapeHtml(item.url || '#') + '" target="_blank" rel="noopener" data-act="open">' +
              highlight(item.title, item.matched_keywords) +
            '</a>' +
            '<div class="item-summary">' + escapeHtml(item.summary_ai || item.summary_raw || '') + '</div>' +
            '<div class="item-meta">' + tags + '<span class="meta-sep">·</span><span>' + timeAgo(item.published_at) + '</span></div>' +
          '</div>' +
          '<div class="item-actions">' +
            '<button class="mini-btn' + (isStar ? ' on' : '') + '" data-act="star" title="收藏">' + (isStar ? '★' : '☆') + '</button>' +
            '<button class="mini-btn" data-act="read" title="标记为已读">' + (isRead ? '✓' : '◯') + '</button>' +
          '</div>' +
        '</article>';
    }).join('');
  }

  function renderForums(data) {
    // 论坛类内容按来源分组，每个来源一栏
    var forumItems = data.items.filter(function (i) {
      return i.category === '论坛热议' || heatOf(i).replies > 0;
    });
    if (!forumItems.length) { el.forumSection.hidden = true; return; }
    el.forumSection.hidden = false;

    var groups = {};
    forumItems.forEach(function (item) {
      var name = item.source_name || '其他';
      if (!groups[name]) groups[name] = [];
      groups[name].push(item);
    });

    var html = Object.keys(groups).map(function (name) {
      var list = groups[name].sort(function (a, b) { return heatOf(b).replies - heatOf(a).replies; }).slice(0, 8);
      var rows = list.map(function (item, i) {
        var h = heatOf(item);
        return '' +
          '<a class="forum-row' + (readSet.has(item.id) ? ' read' : '') + '" href="' + escapeHtml(item.url || '#') + '" target="_blank" rel="noopener" data-id="' + escapeHtml(item.id) + '">' +
            '<span class="forum-rank">' + (i + 1) + '</span>' +
            '<span class="forum-title">' + highlight(truncate(item.title, 40), item.matched_keywords) + '</span>' +
            '<span class="forum-replies">' + (h.replies ? h.replies + ' 帖' : '') + '</span>' +
          '</a>';
      }).join('');
      return '<div class="forum-card"><h4>' + escapeHtml(name) + '<span>' + groups[name].length + ' 条</span></h4><div class="forum-list">' + rows + '</div></div>';
    }).join('');

    el.forumGrid.innerHTML = html;
  }

  function renderVendors(data) {
    var vendors = (data.vendors || []).filter(Boolean);
    if (!vendors.length) { el.vendorSection.hidden = true; return; }
    el.vendorSection.hidden = false;

    var counts = {};
    data.items.forEach(function (i) {
      if (i.vendor) counts[i.vendor] = (counts[i.vendor] || 0) + 1;
    });

    el.vendorTabs.innerHTML = vendors.map(function (v) {
      return '<button class="vendor-tab' + (v === state.vendor ? ' active' : '') + (counts[v] ? '' : ' empty') +
        '" data-vendor="' + escapeHtml(v) + '">' + escapeHtml(v) + (counts[v] ? ' · ' + counts[v] : '') + '</button>';
    }).join('');

    if (!state.vendor) {
      el.vendorFeed.innerHTML = '<div class="empty-sub" style="padding:12px 4px">点上面的厂商名字，看它今天有什么动静。</div>';
      return;
    }

    var list = data.items.filter(function (i) { return i.vendor === state.vendor; }).slice(0, 12);
    el.vendorFeed.innerHTML = list.length
      ? list.map(function (item) {
          return '' +
            '<article class="item" data-id="' + escapeHtml(item.id) + '">' +
              '<div class="score"><span class="stars">' + starsOf(item.score) + '</span></div>' +
              '<div class="item-main">' +
                '<a class="item-title" href="' + escapeHtml(item.url || '#') + '" target="_blank" rel="noopener" data-act="open">' + highlight(item.title, item.matched_keywords) + '</a>' +
                '<div class="item-meta"><span class="tag tag-source">' + escapeHtml(item.source_name || '') + '</span><span class="meta-sep">·</span><span>' + timeAgo(item.published_at) + '</span></div>' +
              '</div>' +
              '<div class="item-actions"><button class="mini-btn' + (starSet.has(item.id) ? ' on' : '') + '" data-act="star">' + (starSet.has(item.id) ? '★' : '☆') + '</button></div>' +
            '</article>';
        }).join('')
      : '<div class="empty-sub" style="padding:12px 4px">这家今天没有新动静。</div>';
  }

  function renderTimeline(data) {
    var logs = data.items.filter(function (i) {
      return i.category === '更新日志' || i.category === '开源项目';
    });
    if (!logs.length) { el.timelineSection.hidden = true; return; }
    el.timelineSection.hidden = false;

    var byDay = {};
    logs.forEach(function (item) {
      var key = dateKey(item.published_at);
      if (!byDay[key]) byDay[key] = [];
      byDay[key].push(item);
    });

    var today = data.date;
    var html = Object.keys(byDay).sort().reverse().map(function (day) {
      var rows = byDay[day].slice(0, 12).map(function (item) {
        return '' +
          '<a class="tl-item" href="' + escapeHtml(item.url || '#') + '" target="_blank" rel="noopener">' +
            (item.vendor ? '<span class="tl-vendor">' + escapeHtml(item.vendor) + '</span>' : '') +
            escapeHtml(truncate(item.title, 60)) +
          '</a>';
      }).join('');
      return '<div class="tl-day' + (day === today ? ' today' : '') + '">' +
        '<div class="tl-date">' + escapeHtml(day) + (day === today ? ' · 今天' : '') + '</div>' +
        '<div class="tl-items">' + rows + '</div></div>';
    }).join('');

    el.timeline.innerHTML = html;
  }

  function renderHealth(data) {
    var list = data.sources_health || [];
    if (!list.length) { el.healthList.innerHTML = '<li class="empty-sub">暂无数据</li>'; return; }

    var ok = list.filter(function (h) { return h.status === 'ok'; }).length;
    el.healthHint.textContent = ok + ' / ' + list.length + ' 正常';

    el.healthList.innerHTML = list.map(function (h) {
      var good = h.status === 'ok';
      return '<li class="health-row' + (good ? '' : ' fail') + '"' + (good ? '' : ' title="' + escapeHtml(h.error || '抓取失败') + '"') + '>' +
        '<span class="hdot ' + (good ? 'ok' : 'fail') + '"></span>' +
        '<span class="hname">' + escapeHtml(h.name) + '</span>' +
        '<span class="hcount">' + (good ? h.count + ' 条' : '失败') + '</span>' +
      '</li>';
    }).join('');
  }

  function renderKeywords(data) {
    var counter = {};
    data.items.forEach(function (item) {
      (item.matched_keywords || []).forEach(function (w) {
        counter[w] = (counter[w] || 0) + 1;
      });
    });
    var words = Object.keys(counter).sort(function (a, b) { return counter[b] - counter[a]; }).slice(0, 18);
    if (!words.length) {
      el.keywordCloud.innerHTML = '<span class="empty-sub" style="font-size:12px">今天没有命中任何关注词。</span>';
      return;
    }
    var max = counter[words[0]];
    el.keywordCloud.innerHTML = words.map(function (w) {
      var hot = counter[w] >= max * 0.6 ? ' hot' : '';
      return '<span class="kw' + hot + '" data-kw="' + escapeHtml(w) + '">' + escapeHtml(w) + ' · ' + counter[w] + '</span>';
    }).join('');
  }

  function renderArchive() {
    var dates = availableDates();
    if (!dates.length) { el.archiveList.innerHTML = '<span class="empty-sub" style="font-size:12px">暂无归档</span>'; return; }
    el.archiveList.innerHTML = dates.slice(0, 30).map(function (d) {
      var data = DATA[d];
      var count = data && data.items ? data.items.length : '';
      return '<button class="archive-item' + (d === state.date ? ' active' : '') + '" data-date="' + escapeHtml(d) + '">' +
        '<span>' + escapeHtml(d) + '</span><span class="arch-stat">' + (count ? count + ' 条' : '') + '</span></button>';
    }).join('');
  }

  function renderFooter(data) {
    var s = data.stats || {};
    el.footerStat.textContent = '共 ' + (s.total || 0) + ' 条 · 数据源 ' +
      (s.sources_ok || 0) + ' 正常 / ' + (s.sources_fail || 0) + ' 失败';
    el.footerTime.textContent = '生成于 ' + (data.generated_at || '').replace('T', ' ').slice(0, 19);
  }

  function updateStarBadge() {
    var n = starSet.size;
    if (n > 0) {
      el.starredCount.hidden = false;
      el.starredCount.textContent = n > 99 ? '99+' : String(n);
    } else {
      el.starredCount.hidden = true;
    }
    $('btn-starred').classList.toggle('active', state.onlyStarred);
  }

  // ============================================================
  // 5. 交互
  // ============================================================
  function toggleStar(id, btn) {
    if (starSet.has(id)) starSet.delete(id); else starSet.add(id);
    saveSet(LS.star, starSet);
    var on = starSet.has(id);
    if (btn) {
      btn.classList.toggle('on', on);
      btn.textContent = on ? '★' : '☆';
    }
    var card = document.querySelector('.item[data-id="' + cssEscape(id) + '"]');
    if (card) card.classList.toggle('starred', on);
    updateStarBadge();
    if (state.onlyStarred) renderFeed();
  }

  function toggleRead(id, btn) {
    if (readSet.has(id)) readSet.delete(id); else readSet.add(id);
    saveSet(LS.read, readSet);
    var on = readSet.has(id);
    var card = document.querySelector('.item[data-id="' + cssEscape(id) + '"]');
    if (card) card.classList.toggle('read', on);
    if (btn) btn.textContent = on ? '✓' : '◯';
    if (state.hideRead) renderFeed();
  }

  /** 给 CSS 选择器用的转义，防止 id 里有特殊字符导致查询报错 */
  function cssEscape(value) {
    return String(value).replace(/["\\]/g, '\\$&');
  }

  function bindEvents() {
    // 搜索（防抖 200ms，避免每敲一个字就重排页面）
    var timer = null;
    $('search').addEventListener('input', function (e) {
      var v = e.target.value;
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.query = v;
        state.shown = 30;
        renderFeed();
      }, 200);
    });

    // 分类切换
    el.categorySeg.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-cat]');
      if (!btn) return;
      state.category = btn.getAttribute('data-cat');
      state.shown = 30;
      renderCategories(state.data);
      renderFeed();
    });

    // 主列表里的按钮（事件委托，几百条卡片也只挂一个监听器）
    el.feed.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var card = e.target.closest('.item');
      if (!card) return;
      var id = card.getAttribute('data-id');
      var act = btn.getAttribute('data-act');
      if (act === 'star') { e.preventDefault(); toggleStar(id, btn); }
      if (act === 'read') { e.preventDefault(); toggleRead(id, btn); }
      if (act === 'open') { markReadSilently(id); }
    });

    el.vendorFeed.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var card = e.target.closest('.item');
      if (!card) return;
      if (btn.getAttribute('data-act') === 'star') { e.preventDefault(); toggleStar(card.getAttribute('data-id'), btn); }
    });

    // 论坛区点击即标记已读
    el.forumGrid.addEventListener('click', function (e) {
      var row = e.target.closest('.forum-row');
      if (row) markReadSilently(row.getAttribute('data-id'));
    });

    function markReadSilently(id) {
      if (!id || readSet.has(id)) return;
      readSet.add(id);
      saveSet(LS.read, readSet);
      var card = document.querySelector('.item[data-id="' + cssEscape(id) + '"]');
      if (card) card.classList.add('read');
    }

    // 厂商标签
    el.vendorTabs.addEventListener('click', function (e) {
      var btn = e.target.closest('.vendor-tab');
      if (!btn) return;
      state.vendor = btn.getAttribute('data-vendor');
      renderVendors(state.data);
    });

    // 关注词：点一下就当搜索
    el.keywordCloud.addEventListener('click', function (e) {
      var kw = e.target.closest('.kw');
      if (!kw) return;
      var word = kw.getAttribute('data-kw');
      $('search').value = word;
      state.query = word;
      state.shown = 30;
      renderFeed();
      window.scrollTo({ top: el.feed.offsetTop - 120, behavior: 'smooth' });
    });

    // 历史归档
    el.archiveList.addEventListener('click', function (e) {
      var btn = e.target.closest('.archive-item');
      if (!btn) return;
      switchDate(btn.getAttribute('data-date'));
    });

    // 显示更多
    el.btnMore.addEventListener('click', function () {
      state.shown += 30;
      renderFeed();
    });

    // 隐藏已读
    $('hide-read').addEventListener('change', function (e) {
      state.hideRead = e.target.checked;
      try { localStorage.setItem(LS.hideRead, state.hideRead ? '1' : '0'); } catch (err) { /* 忽略 */ }
      renderFeed();
    });

    // 只看收藏
    $('btn-starred').addEventListener('click', function () {
      state.onlyStarred = !state.onlyStarred;
      renderFeed();
      updateStarBadge();
    });

    // 主题切换
    $('btn-theme').addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      setTheme(next);
    });

    // 说明弹层
    var modal = $('help-modal');
    $('btn-help').addEventListener('click', function () { modal.hidden = false; });
    modal.addEventListener('click', function (e) {
      if (e.target.hasAttribute('data-close')) modal.hidden = true;
    });

    // 导出 Markdown
    $('btn-export').addEventListener('click', exportMarkdown);

    // 清除已读
    $('btn-clear-read').addEventListener('click', function () {
      if (!confirm('确定要清除所有已读记录吗？收藏不会被清除。')) return;
      readSet.clear();
      saveSet(LS.read, readSet);
      renderAll();
    });

    // 恢复默认
    $('btn-reset').addEventListener('click', function () {
      if (!confirm('会清除收藏、已读记录和主题设置，恢复到初始状态。确定吗？')) return;
      readSet.clear(); starSet.clear();
      saveSet(LS.read, readSet); saveSet(LS.star, starSet);
      state.onlyStarred = false; state.hideRead = false; state.query = ''; state.category = '全部'; state.vendor = '';
      $('search').value = '';
      $('hide-read').checked = false;
      setTheme('dark');
      renderAll();
    });

    // 回到顶部
    el.toTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // 滚动效果
    var ticking = false;
    window.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        var y = window.scrollY || 0;
        el.topbar.classList.toggle('scrolled', y > 8);
        el.toTop.hidden = y < 600;
        ticking = false;
      });
    }, { passive: true });

    // 快捷键
    document.addEventListener('keydown', function (e) {
      var tag = (e.target.tagName || '').toLowerCase();
      var typing = tag === 'input' || tag === 'textarea';

      if (e.key === '/' && !typing) { e.preventDefault(); $('search').focus(); return; }
      if (e.key === 'Escape') {
        if (typing) { $('search').value = ''; state.query = ''; renderFeed(); $('search').blur(); }
        else if (!modal.hidden) { modal.hidden = true; }
        return;
      }
      if ((e.key === 's' || e.key === 'S') && !typing && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        $('btn-starred').click();
      }
    });
  }

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    $('theme-glyph').textContent = theme === 'dark' ? '☾' : '☀';
    try { localStorage.setItem(LS.theme, theme); } catch (e) { /* 忽略 */ }
  }

  // ============================================================
  // 6. 导出 Markdown
  // ============================================================
  function exportMarkdown() {
    var data = state.data;
    if (!data) return;
    var items = getFilteredItems();

    var lines = [];
    lines.push('# AI 日报 · ' + data.date);
    lines.push('');
    lines.push('> ' + (data.briefing || ''));
    lines.push('');
    lines.push('- 共 ' + items.length + ' 条（全量 ' + (data.stats.total || 0) + ' 条）');
    lines.push('- 生成时间：' + (data.generated_at || ''));
    lines.push('- 处理模式：' + (data.mode === 'ai' ? 'AI 智能摘要' : '规则模式'));
    lines.push('');

    var promos = items.filter(function (i) { return i.is_promo; });
    if (promos.length) {
      lines.push('## 优惠活动');
      lines.push('');
      promos.forEach(function (i) {
        lines.push('- **' + (i.vendor ? '[' + i.vendor + '] ' : '') + i.title + '**');
        lines.push('  - ' + (i.url || ''));
      });
      lines.push('');
    }

    lines.push('## 全部条目');
    lines.push('');
    items.forEach(function (i, n) {
      var heat = heatOf(i);
      var score = '★'.repeat(Math.max(1, Math.min(5, Number(i.score) || 3)));
      lines.push('### ' + (n + 1) + '. ' + i.title);
      lines.push('');
      lines.push('- 重要度：' + score + '　来源：' + (i.source_name || '') + (i.vendor ? '　厂商：' + i.vendor : ''));
      if (heat.replies) lines.push('- 热度：' + heat.replies + ' 帖 / ' + heat.participants + ' 人');
      lines.push('- 时间：' + (i.published_at || '未知'));
      if (i.summary_ai || i.summary_raw) lines.push('- 摘要：' + (i.summary_ai || i.summary_raw));
      lines.push('- 链接：' + (i.url || ''));
      lines.push('');
    });

    lines.push('---');
    lines.push('');
    lines.push('由 AI 日报看板生成 · Author: wr');

    download(data.date + '-AI日报.md', lines.join('\n'));
  }

  function download(filename, text) {
    var blob = new Blob(['\ufeff' + text], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  // ============================================================
  // 7. 启动
  // ============================================================
  function init() {
    // 主题
    var savedTheme = null;
    try { savedTheme = localStorage.getItem(LS.theme); } catch (e) { /* 忽略 */ }
    setTheme(savedTheme || 'dark');

    try { state.hideRead = localStorage.getItem(LS.hideRead) === '1'; } catch (e) { /* 忽略 */ }
    $('hide-read').checked = state.hideRead;

    var dates = availableDates();
    state.date = dates[0] || Object.keys(DATA)[0] || '';

    bindEvents();

    if (!state.date || !DATA[state.date]) {
      showNoData();
      return;
    }

    renderAll();
    hideSkeleton();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
