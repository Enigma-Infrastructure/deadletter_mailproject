import{W as S}from"./index-_2AospXH.js";function h(n,o=""){if(!n)return o;if(typeof n=="string"){if(n.startsWith("i_")||n.startsWith("h_")||n.startsWith("m_"))return n.slice(2).trim()||o;try{const e=S.parse(n);return e.type==="input"?e.value||o:e.id||o}catch{return n||o}}if(typeof n=="object"&&n!==null){const e=n;for(const t of["en-US","en","custom","text","value"]){const s=e[t];if(typeof s=="string"&&s.trim())return s.trim()}}return o}function u(n){return String(n??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}function w(n,o){const e=new Map;for(const t of Object.values(n.packs??{}))if(!(!t||typeof t!="object"||!t.designs)){for(const s of Object.values(t.designs))if(!(!s||typeof s!="object")){for(const[c,l]of Object.entries(s))if(l&&typeof l=="object"&&"name"in l){const m=o(l.name);m&&e.set(c,m)}}}return e}function g(n,o,e,t="Unnamed"){if(!n||typeof n!="object")return t;const s=n,c=s.customName??s.name,l=c?e(c):"",m=s.design;if(m&&typeof m=="object"){const p=m;if(p.custom&&typeof p.custom=="object"&&"name"in p.custom){const r=e(p.custom.name);if(l&&r&&l!==r)return`${l} (${r})`;if(r)return l||r}if(typeof p.uid=="string"){const d=p.uid.split(":")[2]??p.uid,f=o.get(d);if(f)return l||f}if(typeof p.id=="string"&&o.has(p.id))return l||o.get(p.id)}return l||(typeof s.label=="string"&&s.label?s.label:t)}function j(n,o=h){const e=n.pointBuy,t=w(n,o),s={};for(const[i,a]of Object.entries(e.aptitudes??{}))s[i.toUpperCase()]=Number(a??0);const c=[];for(const[i,a]of Object.entries(e.skillPacks??{}))a&&c.push({slot:i,name:g(a,t,o,i)});const l=new Map,m=i=>{if(!i||typeof i!="object")return;const a=i,b=g(a,t,o,"Skill"),$=Number(a.points??a.rating??0),y=a.specialization?o(a.specialization):"",v=`${b.toLowerCase()}::${y.toLowerCase()}`,k=l.get(v);k?k.rating+=$:l.set(v,{name:b,rating:$,spec:y})};for(const i of Object.values(e.skillPacks??{}))if(i&&typeof i=="object"&&"skills"in i&&i.skills)for(const a of Object.values(i.skills))m(a);for(const i of Object.values(e.skills??{}))m(i);const p=[...l.values()].filter(i=>i.rating>0).sort((i,a)=>a.rating-i.rating||i.name.localeCompare(a.name)),r=Object.values(e.morphs??{}).map(i=>g(i,t,o,"Morph")),d=Object.values(e.egoTraits??{}).map(i=>g(i,t,o,"Trait")),f=Object.values(e.sleights??{}).map(i=>g(i,t,o,"Sleight")),x=Object.values(e.reputations??{}).map(i=>{const a=i;return{name:g(a,t,o,"Rep"),score:Number(a.score??a.points??0)}}),O=Array.isArray(e.languages)?e.languages.map(i=>o(i)).filter(Boolean):[],P=Object.values(e.motivations??{}).map(i=>{const a=i;return{cause:o(a.cause,"Motivation"),stance:a.stance?String(a.stance):""}}),N=Object.values(e.gear??{}).map(i=>g(i,t,o,"Gear"));return{name:o(e.name,"Unnamed Ego"),fullName:o(e.fullName,""),concept:o(e.concept,""),egos:o(e.egoType,""),flexPoints:Number(e.flexPoints??1),aptitudes:s,skillPacks:c,morphs:r,skills:p,traits:d,sleights:f,reputations:x,languages:O,motivations:P,gear:N}}function C(n,o=h){const e=j(n,o),t=[`# ${e.name} — Eclipse Phase 2e Character Sheet`,"","- **System:** Point-Buy v2 (Spacemarches / MeshNet)"];if(e.fullName&&t.push(`- **Full Name:** ${e.fullName}`),e.concept&&t.push(`- **Concept:** ${e.concept}`),e.egos&&t.push(`- **Ego Type:** ${e.egos}`),t.push(`- **Ego Flex:** ${e.flexPoints}`),t.push(""),Object.keys(e.aptitudes).length){t.push("## Aptitudes");for(const[s,c]of Object.entries(e.aptitudes))t.push(`- **${s}:** ${c}`);t.push("")}if(e.skillPacks.length){t.push("## Origin Skill Packs");for(const s of e.skillPacks)t.push(`- **${s.slot.toUpperCase()}:** ${s.name}`);t.push("")}if(e.morphs.length){t.push("## Morphs");for(const s of e.morphs)t.push(`- ${s}`);t.push("")}if(e.skills.length){t.push("## Skills");for(const s of e.skills){const c=s.spec?` (${s.spec})`:"";t.push(`- **${s.name}${c}:** ${s.rating}`)}t.push("")}if(e.traits.length){t.push("## Ego Traits");for(const s of e.traits)t.push(`- ${s}`);t.push("")}if(e.sleights.length){t.push("## Psi Sleights");for(const s of e.sleights)t.push(`- ${s}`);t.push("")}if(e.reputations.length){t.push("## Reputation Networks");for(const s of e.reputations)t.push(`- **${s.name}:** ${s.score}`);t.push("")}if(e.languages.length&&(t.push(`## Languages
- ${e.languages.join(", ")}`),t.push("")),e.motivations.length){t.push("## Motivations");for(const s of e.motivations)t.push(`- ${s.stance?`${s.stance}: `:""}${s.cause}`);t.push("")}if(e.gear.length){t.push("## Gear & Assets");for(const s of e.gear)t.push(`- ${s}`);t.push("")}return`${t.join(`
`).trim()}
`}function L(n,o=h){const e=j(n,o),t=["COG","INT","REF","SAV","SOM","WIL"].map(r=>`<div class="stat-box"><div class="stat-k">${r}</div><div class="stat-v">${u(e.aptitudes[r]??15)}</div></div>`).join(""),s=r=>r.length?`<ul>${r.map(d=>`<li>${u(d)}</li>`).join("")}</ul>`:'<p class="muted">None recorded</p>',c=e.skills.length?`<table><thead><tr><th>Skill</th><th>Specialization</th><th>Points</th></tr></thead><tbody>${e.skills.map(r=>`<tr><td>${u(r.name)}</td><td>${u(r.spec||"—")}</td><td class="num">${u(r.rating)}</td></tr>`).join("")}</tbody></table>`:'<p class="muted">No skills allocated yet.</p>',l=e.skillPacks.map(r=>`${r.slot.toUpperCase()}: ${r.name}`),m=e.reputations.map(r=>`${r.name}: ${r.score}`),p=e.motivations.map(r=>`${r.stance?`${r.stance} — `:""}${r.cause}`);return`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${u(e.name)} — EP2e Character Sheet</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; color: #111827; background: #ffffff; margin: 0; padding: 2rem; line-height: 1.45; }
    .sheet { max-width: 880px; margin: 0 auto; border: 1px solid #cbd5e1; border-radius: 8px; padding: 1.75rem 2rem; }
    header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 1rem; border-bottom: 2px solid #0f172a; padding-bottom: 0.75rem; margin-bottom: 1.25rem; }
    h1 { margin: 0; font-size: 1.6rem; letter-spacing: -0.02em; }
    .meta { color: #475569; font-size: 0.88rem; }
    .apt-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0.6rem; margin-bottom: 1.25rem; }
    .stat-box { border: 1px solid #cbd5e1; border-radius: 6px; padding: 0.5rem; text-align: center; background: #f8fafc; }
    .stat-k { font-family: monospace; font-size: 0.75rem; font-weight: 700; color: #475569; }
    .stat-v { font-size: 1.25rem; font-weight: 700; font-variant-numeric: tabular-nums; }
    .cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.25rem; }
    section { margin-bottom: 1rem; }
    h2 { font-size: 0.92rem; text-transform: uppercase; letter-spacing: 0.06em; color: #334155; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.25rem; margin: 0 0 0.5rem; }
    ul { margin: 0; padding-left: 1.2rem; font-size: 0.92rem; }
    li { margin-bottom: 0.25rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { padding: 0.35rem 0.5rem; border-bottom: 1px solid #e2e8f0; text-align: left; }
    th { font-size: 0.76rem; text-transform: uppercase; color: #475569; }
    td.num { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
    .muted { color: #64748b; font-size: 0.86rem; margin: 0; }
    @media print { body { padding: 0; } .sheet { border: none; padding: 0; } }
  </style>
</head>
<body>
  <article class="sheet">
    <header>
      <div>
        <h1>${u(e.name)}</h1>
        ${e.fullName?`<div class="meta">Full Name: ${u(e.fullName)}</div>`:""}
        ${e.concept?`<div class="meta">Concept: ${u(e.concept)}</div>`:""}
      </div>
      <div class="meta">
        <div><strong>Ego Flex:</strong> ${u(e.flexPoints)}</div>
        ${e.egos?`<div><strong>Ego Type:</strong> ${u(e.egos)}</div>`:""}
      </div>
    </header>
    <div class="apt-grid">${t}</div>
    <div class="cols">
      <div>
        <section><h2>Identity &amp; Origin Packs</h2>${s(l)}</section>
        <section><h2>Morphs</h2>${s(e.morphs)}</section>
        <section><h2>Ego Traits</h2>${s(e.traits)}</section>
        <section><h2>Reputation Networks</h2>${s(m)}</section>
        <section><h2>Languages</h2>${s(e.languages)}</section>
      </div>
      <div>
        <section><h2>Skills</h2>${c}</section>
        ${e.sleights.length?`<section><h2>Psi Sleights</h2>${s(e.sleights)}</section>`:""}
        <section><h2>Motivations</h2>${s(p)}</section>
        <section><h2>Gear &amp; Assets</h2>${s(e.gear)}</section>
      </div>
    </div>
  </article>
</body>
</html>`}function E(n){return n.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"")||"character"}function M(n,o,e){const t=new Blob([o],{type:e}),s=URL.createObjectURL(t),c=document.createElement("a");c.href=s,c.download=n,c.style.display="none",document.body.appendChild(c),c.click(),c.remove(),window.setTimeout(()=>URL.revokeObjectURL(s),1e3)}export{C as a,L as g,E as s,M as t};
