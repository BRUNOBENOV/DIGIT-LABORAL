/* Read ordinary salary list pages with the operator's existing REOP session. */
(() => {
  "use strict";
  const origin = "https://regobpat.mtess.gov.py", path = "/liquidacion_salario_list.php";
  const months = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","setiembre","octubre","noviembre","diciembre"];
  const plain = s => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/\s+/g," ").trim();
  const fold = s => plain(s).toLowerCase();
  const account = /usuario\b.{0,65}?\bcon\s+(?:nro\.?|n[°º]|numero)\s*patronal\s*:?\s*(\d{1,20})\b/;
  const num = s => Number(s.replaceAll(".",""));
  function parsePage(text, patronal) {
    const raw = plain(text), t = raw.toLowerCase();
    if (t.match(account)?.[1] !== patronal) throw new Error("La patronal abierta en REOP no coincide.");
    const range = t.match(/mostrando\s+([\d.]+)\s*[-–a]\s*([\d.]+)\s+de\s+([\d.]+)/);
    const starts = [...t.matchAll(/n(?:[°ºo]|ro)\.?\s*(?:de\s+)?liquidacion salario\s*:\s*(\d+)\b/g)];
    if (!range && !starts.length && /\b(no (?:hay|se encontraron) registros|ningun registro encontrado|sin registros)\b/.test(t)) {
      return {first:0, last:0, total:0, rows:[]};
    }
    if (!range) throw new Error("REOP no mostró el total de liquidaciones. Revisá la sesión y los filtros.");
    const [first,last,total] = range.slice(1).map(num);
    if (total > 100000 || last > total || (total && first < 1) || starts.length !== (total ? last-first+1 : 0)) {
      throw new Error("REOP devolvió una página incompleta.");
    }
    const rows = starts.map((start,i) => {
      const card = t.slice(start.index + start[0].length, starts[i+1]?.index);
      const document = card.match(/\bempleado\s*:\s*([a-z0-9.]+(?:-[0-9]+)*)\s*-\s*\S/)?.[1];
      const employer = card.match(/\bnumero patronal\s*:\s*(\d+)\b/)?.[1];
      const name = card.match(/\bperiodo (?:de )?liquidacion\s*:\s*([a-z]+)/)?.[1];
      const month = months.indexOf(name === "septiembre" ? "setiembre" : name) + 1;
      const year = card.match(/\bano\s*:\s*(20\d{2})\b/)?.[1];
      const income = card.match(/monto total ingresos\s*:\s*(?:gs\.?\s*|₲\s*)?(\d{1,3}(?:\.\d{3})+|\d+)(?=\s|$)/)?.[1];
      const status = card.match(/\bestado\s*:\s*(.+?)(?=\s+(?:ano|usuario gestion|origen dato|fecha insertado|cantidad|monto |horas |constancia|periodo )\s*:?|$)/)?.[1];
      if (!document || !month || !year || income === undefined || !status || status.length > 80 || employer !== patronal) {
        throw new Error("REOP no mostró todos los datos de cada liquidación. La consulta quedó sin verificar.");
      }
      const rawCard = raw.slice(start.index + start[0].length, starts[i+1]?.index);
      const receipt = rawCard.match(/\bconstancia\s*:\s*((?=[a-z0-9/-]*\d)[a-z0-9][a-z0-9/-]{0,99})(?=\s|$)/i)?.[1] || "";
      return {number:start[1], document:document.toUpperCase(), patronal, period:year+"-"+String(month).padStart(2,"0"),
        income:num(income), status:status[0].toUpperCase()+status.slice(1), receipt};
    });
    return {first,last,total,rows};
  }

  async function collect(readPage, patronal, period) {
    const seen = new Set(), records = [];
    let total;
    for (let page=1; page<=500; page++) {
      const data = await readPage(page);
      if (total === undefined) total = data.total;
      if (data.total !== total || (total && (data.first !== seen.size+1 || data.last < data.first))) {
        throw new Error("El listado cambió durante la consulta. Volvé a verificar.");
      }
      for (const row of data.rows) {
        if (seen.has(row.number)) throw new Error("REOP repitió una liquidación al paginar.");
        seen.add(row.number);
        if (row.period === period) records.push(row);
      }
      if (data.last === total && seen.size === total) return {source:"REOP", complete:true, patronal, period, total, inspected:seen.size, records};
      if (!data.hasNext) break;
    }
    throw new Error("La consulta no cubrió todas las páginas del listado.");
  }

  function listingText(doc) {
    const text = [], walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const parent = walker.currentNode.parentElement;
      if (parent && !parent.closest("script,style,template,noscript,[hidden]")) text.push(walker.currentNode.nodeValue);
    }
    return text.join(" ");
  }

  async function read(patronal, period) {
    if (location.origin !== origin || location.pathname !== path || !/^\d{1,20}$/.test(patronal)
        || !/^20\d{2}-(0[1-9]|1[0-2])$/.test(period) || fold(document.body.innerText).match(account)?.[1] !== patronal) {
      throw new Error("Abrí Liquidación Salario en la patronal seleccionada.");
    }
    let url = new URL(path + "?goto=1", origin);
    return collect(async page => {
      const response = await fetch(url, {credentials:"same-origin", cache:"no-store", redirect:"error", signal:AbortSignal.timeout(30000)});
      if (!response.ok) throw new Error("REOP no devolvió el listado. Verificá tu sesión.");
      const doc = new DOMParser().parseFromString(await response.text(),"text/html");
      const reset = [...doc.querySelectorAll('a[href*="a=showall"],[data-itemtype="search_reset"]')].some(el =>
        !el.closest('[hidden],.rnr-hidden,.r-hidden,[style*="display: none"],[style*="display:none"]') &&
        /mostrar todo|quitar filtro|limpiar busqueda/.test(fold(el.textContent)));
      if (reset || doc.querySelector('input[id^="ctlSearchFor"]')?.value.trim()) throw new Error("Quitá los filtros del listado en REOP.");
      const data = parsePage(listingText(doc),patronal);
      const next = [...doc.querySelectorAll("a[href]")].map(a => {
        try { return new URL(a.getAttribute("href"),url); } catch (_) { return null; }
      }).find(l => l?.origin === origin && l.pathname === path && [...l.searchParams.keys()].every(k=>k==="goto")
        && l.searchParams.get("goto") === String(page+1));
      // Some versions render the pager as a JavaScript button. The next range
      // and the distinct liquidation numbers still have to prove continuity.
      url = next || new URL(path + "?goto=" + (page + 1), origin);
      return {...data, hasNext:data.last < data.total};
    },patronal,period);
  }
  globalThis.DigitSalaryList = {read, parsePage, collect};
})();
