"""Генерация HTML-страницы с событиями по датам (output/index.html)."""
import html
import json
from datetime import date, datetime
from pathlib import Path

OUT = Path(__file__).parent / "output" / "index.html"
WD = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MON = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
       "сентября", "октября", "ноября", "декабря"]


def _day_label(d):
    today = date.today()
    delta = (d - today).days
    prefix = {0: "Сегодня · ", 1: "Завтра · "}.get(delta, "")
    return f"{prefix}{WD[d.weekday()]}, {d.day} {MON[d.month]}"


def _source_name(url):
    return url.replace("https://t.me/", "@").split("/")[0] if "t.me/" in url else \
        url.split("//")[-1].split("/")[0]


def render(con):
    today = date.today().isoformat()
    rows = con.execute(
        "SELECT * FROM events WHERE COALESCE(end_date, date) >= ? ORDER BY date, time IS NULL, time",
        (today,)).fetchall()
    cats = sorted({r["category"] for r in rows})

    # то, что началось раньше и ещё идёт (выставки) — в отдельный блок наверху
    ongoing = [r for r in rows if r["date"] < today]
    days, cur = ([("ongoing", ongoing)] if ongoing else []), None
    for r in rows:
        if r["date"] < today:
            continue
        if r["date"] != cur:
            cur = r["date"]
            days.append((cur, []))
        days[-1][1].append(r)

    e = html.escape
    parts = []
    for d, evs in days:
        label = "Идёт сейчас" if d == "ongoing" else _day_label(date.fromisoformat(d))
        cards = []
        for r in evs:
            srcs = json.loads(r["sources"])
            links = " ".join(f'<a href="{e(u)}" target="_blank" rel="noopener">{e(_source_name(u))}</a>'
                             for u in srcs)
            meta = []
            if r["time"]:
                meta.append(f'<span class="time">{e(r["time"])}</span>')
            if r["end_date"]:
                ed = date.fromisoformat(r["end_date"])
                meta.append(f"до {ed.day} {MON[ed.month]}")
            if r["venue"]:
                meta.append(f"📍 {e(r['venue'])}")
            if r["price"]:
                meta.append(e(r["price"]))
            desc = e(r["description"] or "")
            buy = (f'<a class="buy" href="{e(r["ticket_url"])}" target="_blank" rel="noopener">Купить билет →</a>'
                   if r["ticket_url"] else "")
            cards.append(f"""
      <article class="card" data-start="{r['date']}" data-end="{r['end_date'] or r['date']}" data-cat="{e(r['category'])}" data-text="{e((r['title'] + ' ' + (r['description'] or '') + ' ' + (r['venue'] or '')).lower())}">
        <div class="cat">{e(r['category'])}</div>
        <h3>{e(r['title'])}</h3>
        <div class="meta">{' · '.join(meta)}</div>
        <details><summary>Подробнее</summary><p>{desc}</p></details>
        <div class="src">{buy}Источник: {links}</div>
      </article>""")
        parts.append(f'<section class="day" data-date="{d}"><h2>{label}</h2>{"".join(cards)}</section>')

    chips = "".join(f'<button class="chip" data-cat="{e(c)}">{e(c)}</button>' for c in cats)
    page = TEMPLATE.replace("{{BODY}}", "".join(parts) or '<p class="empty">Пока ничего не найдено.</p>') \
                   .replace("{{CHIPS}}", chips) \
                   .replace("{{COUNT}}", str(len(rows))) \
                   .replace("{{TODAY}}", today) \
                   .replace("{{UPDATED}}", datetime.now().strftime("%d.%m.%Y %H:%M"))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    return OUT, len(rows)


TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Афиша Ташкента</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e6e4df;--acc:#c2410c;--chip:#efece6}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e21;--ink:#f1f1f3;--mute:#9a9aa1;--line:#2c2c30;--acc:#fb923c;--chip:#2a2a2e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{max-width:820px;margin:0 auto;padding:32px 16px 8px}
h1{margin:0 0 4px;font-size:28px}
.sub{color:var(--mute);font-size:14px}
.tools{position:sticky;top:0;background:var(--bg);z-index:2;max-width:820px;margin:0 auto;padding:12px 16px;border-bottom:1px solid var(--line)}
input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font-size:15px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.chip{border:0;background:var(--chip);color:var(--ink);padding:5px 12px;border-radius:999px;font-size:13px;cursor:pointer}
.chip.on{background:var(--acc);color:#fff}
.search{position:relative}
.search input{padding-left:42px}
.qbtn{position:absolute;left:4px;top:50%;transform:translateY(-50%);width:34px;height:34px;border:0;border-radius:8px;
  background:transparent;color:var(--mute);display:flex;align-items:center;justify-content:center;cursor:default;padding:0}
.qbtn .ico-clear{display:none}
.search.filled .qbtn{cursor:pointer;color:var(--ink)}
.search.filled .qbtn:hover{background:var(--chip)}
.search.filled .ico-search{display:none}
.search.filled .ico-clear{display:block}
.chip .cnt{opacity:.55;font-size:12px;margin-left:2px}
.chip.on .cnt{opacity:.85}
.empty{margin:24px 0}
main{max-width:820px;margin:0 auto;padding:8px 16px 48px;display:flex;flex-direction:column}
.also{display:none;font-size:15px;margin:32px 0 0;padding-top:16px;border-top:1px dashed var(--line);color:var(--mute);order:1}
.also.on{display:block}
.day h2{font-size:17px;margin:28px 0 10px;color:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px}
.cat{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
.card h3{margin:2px 0 6px;font-size:17px;line-height:1.3}
.meta{font-size:14px;color:var(--ink)}
.time{font-weight:600}
details{margin-top:6px;font-size:14px;color:var(--mute)}
details p{white-space:pre-wrap;margin:6px 0 0}
summary{cursor:pointer}
.src{margin-top:8px;font-size:13px;color:var(--mute)}
.src a{color:var(--acc);text-decoration:none;margin-right:6px}
.src a.buy{display:inline-block;background:var(--acc);color:#fff;padding:4px 12px;border-radius:999px;margin:0 10px 0 0;font-weight:500}
.src a.buy:hover{opacity:.9}
.empty{color:var(--mute)}
.hidden{display:none}
/* календарь */
.calwrap{max-width:820px;margin:0 auto;padding:8px 16px 4px;display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.cal{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;width:100%;max-width:340px}
.calhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.calhead b{font-size:15px}
.nav{border:0;background:var(--chip);color:var(--ink);width:32px;height:32px;border-radius:8px;font-size:16px;cursor:pointer}
.nav:disabled{opacity:.3;cursor:default}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;text-align:center}
.wd{font-size:11px;color:var(--mute);padding:2px 0}
.wd.we{color:var(--acc)}
.d{position:relative;border:0;background:transparent;color:var(--ink);height:40px;border-radius:8px;font-size:14px;cursor:pointer;padding:0}
.d:hover:not(:disabled){background:var(--chip)}
.d:disabled{color:var(--mute);opacity:.35;cursor:default}
.d.has{font-weight:600}
.d.has::after{content:attr(data-n);position:absolute;left:0;right:0;bottom:2px;font-size:9px;font-weight:500;color:var(--acc)}
.d.today{box-shadow:inset 0 0 0 1.5px var(--acc)}
.d.sel{background:var(--acc);color:#fff}
.d.sel::after{color:#fff}
.quick{display:flex;flex-direction:column;gap:6px;min-width:150px}
.quick .chip{text-align:left;padding:8px 14px;font-size:14px}
.selbar{display:none;margin-top:10px;font-size:14px;align-items:center;gap:8px}
.selbar.on{display:flex}
.selbar button{border:0;background:var(--chip);color:var(--ink);border-radius:999px;padding:3px 10px;cursor:pointer;font-size:13px}
@media (max-width:560px){.quick{flex-direction:row;flex-wrap:wrap;min-width:0}.quick .chip{padding:6px 12px;font-size:13px}.cal{max-width:none}
  /* телефон: категории в одну строку с горизонтальной прокруткой — панель сверху ниже */
  .tools{padding:8px 16px}
  #cats{flex-wrap:nowrap;overflow-x:auto;margin:8px -16px 0;padding:0 16px 2px;scrollbar-width:none;
    -webkit-overflow-scrolling:touch;mask-image:linear-gradient(90deg,#000 85%,transparent)}
  #cats::-webkit-scrollbar{display:none}
  #cats .chip{flex:0 0 auto;white-space:nowrap}
  .selbar{margin-top:6px}}
</style></head><body>
<header><h1>Афиша Ташкента</h1>
<div class="sub">Событий: {{COUNT}} · обновлено {{UPDATED}} · собрано автоматически из Telegram и сайтов</div></header>
<div class="calwrap">
  <div class="cal">
    <div class="calhead"><button class="nav" id="prev" aria-label="Предыдущий месяц">‹</button><b id="mon"></b><button class="nav" id="next" aria-label="Следующий месяц">›</button></div>
    <div class="grid" id="grid"></div>
  </div>
  <div class="quick">
    <button class="chip qd on" data-q="all">Все даты</button>
    <button class="chip qd" data-q="today">Сегодня</button>
    <button class="chip qd" data-q="tomorrow">Завтра</button>
    <button class="chip qd" data-q="weekend">Выходные</button>
    <button class="chip qd" data-q="week">Эта неделя</button>
  </div>
</div>
<div class="tools"><div class="search">
<button id="qclear" class="qbtn" aria-label="Очистить поиск" title="Очистить поиск" tabindex="-1">
<svg class="ico-search" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
<svg class="ico-clear" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
</button><input id="q" placeholder="Поиск: джаз, Ильхом, бесплатно…" autocomplete="off"></div>
<div class="chips" id="cats"><button class="chip on" data-cat="">Все</button>{{CHIPS}}</div>
<div class="selbar" id="selbar"><span id="seltext"></span><button id="selreset">× сбросить дату</button></div></div>
<main><p class="empty hidden" id="none">Ничего не найдено. Попробуйте другую дату, категорию или запрос.</p>{{BODY}}<h2 class="also" id="also">Также идут в эти дни</h2></main>
<script>
const TODAY="{{TODAY}}";
const MONTHS=["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const MON_G=["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
const cards=[...document.querySelectorAll('.card')];
const q=document.getElementById('q');
let cat="", from=null, to=null;

// даты в формате YYYY-MM-DD без сдвигов часового пояса
const pad=n=>String(n).padStart(2,'0');
const iso=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
const parse=s=>{const [y,m,d]=s.split('-').map(Number);return new Date(y,m-1,d)};
const addDays=(s,n)=>{const d=parse(s);d.setDate(d.getDate()+n);return iso(d)};
const human=s=>{const d=parse(s);return d.getDate()+' '+MON_G[d.getMonth()]};

let maxDate=TODAY;
cards.forEach(c=>{if(c.dataset.start>maxDate) maxDate=c.dataset.start});

// подходит ли карточка под категорию и поиск (без учёта даты)
const okCat=(c,k)=>!k||c.dataset.cat===k;
const okText=(c,s)=>!s||c.dataset.text.includes(s);
const okDate=c=>!from||(c.dataset.start<=to&&c.dataset.end>=from);
const query=()=>q.value.trim().toLowerCase();

// числа в календаре — с учётом выбранной категории и поиска
function calCounts(){
  const counts={}, starts={}, s=query();
  cards.forEach(c=>{
    if(!okCat(c,cat)||!okText(c,s)) return;
    let d=c.dataset.start<TODAY?TODAY:c.dataset.start;
    for(let i=0;d<=c.dataset.end&&i<62;i++){counts[d]=(counts[d]||0)+1;d=addDays(d,1)}   // идёт в этот день
    if(c.dataset.start>=TODAY) starts[c.dataset.start]=(starts[c.dataset.start]||0)+1;  // начинается в этот день
  });
  return {counts,starts};
}

const t0=parse(TODAY), tMax=parse(maxDate);
let view=new Date(t0.getFullYear(),t0.getMonth(),1);
const minView=new Date(t0.getFullYear(),t0.getMonth(),1), maxView=new Date(tMax.getFullYear(),tMax.getMonth(),1);

function drawCal(){
  document.getElementById('mon').textContent=MONTHS[view.getMonth()]+' '+view.getFullYear();
  document.getElementById('prev').disabled=view<=minView;
  document.getElementById('next').disabled=view>=maxView;
  const g=document.getElementById('grid'); g.innerHTML='';
  ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].forEach((w,i)=>{const el=document.createElement('div');el.className='wd'+(i>4?' we':'');el.textContent=w;g.appendChild(el)});
  const {counts,starts}=calCounts();
  const first=(view.getDay()+6)%7, days=new Date(view.getFullYear(),view.getMonth()+1,0).getDate();
  for(let i=0;i<first;i++) g.appendChild(document.createElement('div'));
  for(let d=1;d<=days;d++){
    const s=iso(new Date(view.getFullYear(),view.getMonth(),d));
    const b=document.createElement('button'); b.className='d'; b.textContent=d;
    const n=counts[s]||0;
    if(s<TODAY||!n) b.disabled=true;
    if(starts[s]){b.classList.add('has');b.dataset.n=starts[s]}
    if(s===TODAY) b.classList.add('today');
    if(from&&s>=from&&s<=to) b.classList.add('sel');
    b.title=n?('Событий: '+n):'Нет событий';
    b.onclick=()=>{ if(from===s&&to===s){setRange(null,null)} else setRange(s,s); markQuick(null) };
    g.appendChild(b);
  }
}
document.getElementById('prev').onclick=()=>{view.setMonth(view.getMonth()-1);drawCal()};
document.getElementById('next').onclick=()=>{view.setMonth(view.getMonth()+1);drawCal()};

function setRange(a,b){
  from=a;to=b;
  if(a){const d=parse(a);view=new Date(d.getFullYear(),d.getMonth(),1)}
  const bar=document.getElementById('selbar');
  bar.classList.toggle('on',!!a);
  if(a) document.getElementById('seltext').textContent='Показаны события: '+(a===b?human(a):human(a)+' — '+human(b));
  apply();
  if(a) toResults(true);
}
// прокрутить к началу результатов так, чтобы их не закрывала закреплённая панель сверху.
// force=false — только если пользователь уже пролистал ниже начала списка
function toResults(force){
  const tools=document.querySelector('.tools'), main=document.querySelector('main');
  const top=main.getBoundingClientRect().top+window.scrollY-tools.offsetHeight;
  if(force||window.scrollY>top) window.scrollTo({top:Math.max(top,0),behavior:'smooth'});
}
function markQuick(k){document.querySelectorAll('.qd').forEach(x=>x.classList.toggle('on',x.dataset.q===(k||(from?'':'all'))))}
document.querySelectorAll('.qd').forEach(b=>b.onclick=()=>{
  const k=b.dataset.q, wd=(t0.getDay()+6)%7;   // 0=пн … 6=вс
  if(k==='all') setRange(null,null);
  if(k==='today') setRange(TODAY,TODAY);
  if(k==='tomorrow'){const s=addDays(TODAY,1);setRange(s,s)}
  if(k==='weekend'){const sat=wd===6?addDays(TODAY,-1):addDays(TODAY,5-wd);setRange(sat<TODAY?TODAY:sat,addDays(sat,1))}
  if(k==='week') setRange(TODAY,addDays(TODAY,6-wd));
  markQuick(k);
});
document.getElementById('selreset').onclick=()=>{setRange(null,null);markQuick('all')};

const chips=[...document.querySelectorAll('#cats .chip')];
chips.forEach(b=>b.dataset.name=b.textContent);

function apply(){
  const s=query();
  // сколько событий в каждой категории при текущих дате и поиске; пустые категории прячем
  const per={}; let all=0;
  cards.forEach(c=>{if(okDate(c)&&okText(c,s)){per[c.dataset.cat]=(per[c.dataset.cat]||0)+1;all++}});
  if(cat&&!per[cat]) cat='';                  // выбранная категория опустела — показываем все
  chips.forEach(b=>{
    const k=b.dataset.cat, n=k?(per[k]||0):all;
    b.innerHTML=b.dataset.name+' <span class="cnt">'+n+'</span>';
    b.classList.toggle('hidden',!!k&&!n);
    b.classList.toggle('on',k===cat);
  });
  let shown=0;
  cards.forEach(c=>{
    const ok=okDate(c)&&okCat(c,cat)&&okText(c,s);
    if(ok) shown++;
    c.classList.toggle('hidden',!ok)});
  document.getElementById('none').classList.toggle('hidden',shown>0);
  let anyAlso=false;
  document.querySelectorAll('.day').forEach(d=>{
    const vis=!!d.querySelector('.card:not(.hidden)');
    d.classList.toggle('hidden',!vis);
    // при выбранной дате: сначала дни из диапазона, ниже — то, что началось раньше и ещё идёт
    const inRange=!from||(d.dataset.date>=from&&d.dataset.date<=to);
    d.style.order=inRange?0:2;
    if(vis&&!inRange) anyAlso=true;
  });
  document.getElementById('also').classList.toggle('on',anyAlso);
  // если в открытом месяце календаря ничего не подходит — перелистываем на первый месяц с находками
  if(!from&&(s||cat)){
    const days=Object.keys(calCounts().counts).filter(d=>d>=TODAY).sort();
    const vm=iso(view).slice(0,7);
    if(days.length&&!days.some(d=>d.slice(0,7)===vm)){const d=parse(days[0]);view=new Date(d.getFullYear(),d.getMonth(),1)}
  } else if(!from&&!s&&!cat) view=new Date(minView);   // фильтры сброшены — снова текущий месяц
  drawCal();
}
chips.forEach(b=>b.onclick=()=>{
  cat=b.dataset.cat;apply();toResults(false);
  // на телефоне строка категорий прокручивается вбок — подвинем её так, чтобы выбранная была видна
  const row=document.getElementById('cats');
  if(row.scrollWidth>row.clientWidth) row.scrollTo({left:b.offsetLeft-row.offsetLeft-row.clientWidth/2+b.offsetWidth/2,behavior:'smooth'});
});

// поиск: крестик слева и Esc стирают всё написанное
const searchBox=document.querySelector('.search');
function onSearch(){searchBox.classList.toggle('filled',q.value.length>0);apply();toResults(false)}
q.oninput=onSearch;
q.onkeydown=ev=>{if(ev.key==='Escape'&&q.value){q.value='';onSearch()}};
document.getElementById('qclear').onclick=()=>{if(!q.value){q.focus();return}q.value='';onSearch();q.focus()};
apply();
</script></body></html>"""
