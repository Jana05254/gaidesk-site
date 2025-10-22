(function(){
  const q = new URLSearchParams(location.search);
  const device = q.get('device') || '';
  const limit  = window.DASH_LIMIT || 50;

  const el = id => document.getElementById(id);
  const rows = el?.('rows');
  const mTemp = el?.('m-temp'), mCo2 = el?.('m-co2'), mPresence = el?.('m-presence'), mCount = el?.('m-count');

  let chart, timer;

  function fmtTs(v){
    const d = new Date(Number(v));
    return isNaN(d) ? String(v) : d.toLocaleString('ar-SA');
    }

  function toNum(v){ const n = Number(v); return isNaN(n) ? null : n; }

  async function loadData(){
    if(!rows) return;
    const url = `${window.API_BASE}/api/data?limit=${limit}${device ? `&device=${encodeURIComponent(device)}`:''}`;
    const r = await fetch(url, {cache:'no-store'});
    const data = await r.json();

    rows.innerHTML = '';
    data.forEach(item=>{
      const v = item.value || {};
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${fmtTs(v.ts || item.key)}</td>
        <td>${v.t ?? v.temp ?? v.T ?? '—'}</td>
        <td>${v.co2 ?? '—'}</td>
        <td>${v.presence ?? v.p ?? '—'}</td>
        <td>${v.risk ?? v.r ?? 0}</td>`;
      rows.appendChild(tr);
    });
    mCount && (mCount.textContent = data.length);
    if(data.length){
      const last = data[0].value || {};
      mTemp && (mTemp.textContent = last.t ?? last.temp ?? last.T ?? '—');
      mCo2 && (mCo2.textContent  = last.co2 ?? '—');
      mPresence && (mPresence.textContent = last.presence ?? last.p ?? '—');
    }

    const labels = data.map(i=>fmtTs(i.value?.ts || i.key)).reverse();
    const temps  = data.map(i=>toNum(i.value?.t ?? i.value?.temp ?? i.value?.T)).reverse();
    const co2s   = data.map(i=>toNum(i.value?.co2)).reverse();

    const ctx = document.getElementById('chart')?.getContext('2d');
    if(ctx){
      if(chart) chart.destroy();
      chart = new Chart(ctx, {type:'line', data:{
        labels, datasets:[
          {label:'°C', data:temps, borderWidth:2, pointRadius:0, tension:.3},
          {label:'CO₂', data:co2s, borderWidth:2, pointRadius:0, tension:.3}
        ]}, options:{responsive:true, interaction:{mode:'index', intersect:false}}});
    }
  }

  function start(){ stop(); timer=setInterval(loadData, 5000); }
  function stop(){ if(timer) clearInterval(timer); timer=null; }

  document.getElementById('autoRefresh')?.addEventListener('change', e=> e.target.checked ? start() : stop());
  document.getElementById('btnRefresh')?.addEventListener('click', loadData);

  loadData(); start();
})();
