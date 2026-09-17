const button = document.querySelector('#audit-button');
const query = document.querySelector('#query');
const result = document.querySelector('#audit-result');

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}

button?.addEventListener('click', async () => {
  const text = query.value.trim();
  if (!text) {
    query.focus();
    return;
  }
  button.disabled = true;
  button.textContent = '审查中…';
  try {
    const response = await fetch('/api/agent', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})
    });
    const report = await response.json();
    if (response.status === 401) {
      window.location.assign('/login');
      return;
    }
    const labels = report.risks.map(item => item.category).join('、') || '未发现风险';
    result.hidden = false;
    result.className = `audit-result ${report.decision === '拦截' ? 'blocked' : report.decision === '复核' ? 'review' : ''}`;
    const escaped = value => String(value).replace(/[&<>'"]/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[char]));
    const sources = (report.sources || []).map(source => `<li><a href="${escaped(source.url)}" target="_blank" rel="noopener">${escaped(source.title || source.url)}</a><span>${escaped(source.snippet)}</span></li>`).join('');
    result.innerHTML = `<b>AI 智能体 · ${escaped(report.decision)} · ${escaped(report.audit_id)}</b><br>${escaped(report.answer)}<br><span>安全判定：${escaped(labels)}${report.handoff ? '，已转人工/安全处置流程。' : '，已通过受控答复。'}</span>${report.pii_types.length ? `<br>已脱敏：${escaped(report.redacted_text)}` : ''}${sources ? `<ul class="sources"><b>公开检索来源</b>${sources}</ul>` : ''}`;
  } catch (error) {
    result.hidden = false;
    result.className = 'audit-result blocked';
    result.textContent = '安全审查服务暂不可用，请稍后重试。';
  } finally {
    button.disabled = false;
    button.innerHTML = '向智能体提问 <b>→</b>';
  }
});
