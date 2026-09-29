const keys=['cardio','duo','front','rear','sram'];
const names={cardio:'COOSPO H808S',duo:'DuoTrap S',front:'Ion Pro RT · front',rear:'Flare RT · rear',sram:'SRAM Force AXS · 2×12'};
const cards={ble:{},ant:{}};
const sramBatteryOrder=['front derailleur','rear derailleur','left shifter','right shifter'];
function fieldRank(card,label){
 const lower=label.toLowerCase();
 if(!lower.includes('battery'))return 0;
 if(card.key!=='sram')return 100;
 const component=sramBatteryOrder.findIndex(name=>lower.includes(name));
 return component<0?105:101+component;
}
function el(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n}
for(const protocol of ['ble','ant'])for(const key of keys){const card=el('section','sensor'),head=el('div','sensor-head'),title=el('h3','',names[key]),metrics=el('span','metrics'),signal=el('span','signal');head.append(title,metrics);const status=el('div','status','Waiting…'),table=el('table','fields'),error=el('div','error');card.append(head,status,signal,table,error);document.querySelector(`#${protocol}-cards`).append(card);cards[protocol][key]={card,key,metrics,signal,status,table,error,rows:new Map()}}
let last=null,lastAt=0,online=false;
const fmt=v=>v==null?'—':v.toFixed(1);
function renderSection(c,s,elapsed,active){if(!s)return;c.status.textContent=s.status||'Waiting…';c.error.textContent=s.error||'';
 const heartRate=s.fields?.find(f=>f.label==='Heart rate');
 if(c.key==='cardio'){
  const strength=s.rssi==null?'RSSI unavailable':`${s.rssi} dBm`;
  const age=heartRate?`${Math.floor(heartRate.age_s+elapsed)} s ago`:'—';
  c.signal.textContent=`${strength} · HR reading ${age}`;
 }else if(c.key==='duo'){
  const strength=s.rssi==null?'RSSI unavailable':`${s.rssi} dBm`;
  const reading=s.fields?.find(f=>f.label==='Wheel · cumulative revolutions'||f.label==='Crank · cumulative revolutions');
  const age=reading?`${Math.floor(reading.age_s+elapsed)} s ago`:'—';
  c.signal.textContent=`${strength} · reading ${age}`;
 }else if(s.packet_age_s!=null){
  c.signal.textContent=`RSSI unavailable · reading ${Math.floor(s.packet_age_s+elapsed)} s ago`;
 }else c.signal.textContent=s.rssi==null?'':`${s.rssi} dBm · advertisement ${Math.floor((s.advertisement_age_s||0)+elapsed)} s ago`;
 const fields=(s.fields||[]).filter(f=>!(c.key==='cardio'&&f.label==='Heart rate'));
 fields.sort((a,b)=>fieldRank(c,a.label)-fieldRank(c,b.label));
 const labels=new Set(fields.map(f=>f.label));for(const [label,row] of c.rows)if(!labels.has(label)){row.value.parentElement.remove();c.rows.delete(label)}
 for(const f of fields){let row=c.rows.get(f.label);if(!row){const tr=el('tr'),label=el('td','',f.label),value=el('td'),age=el('td');tr.append(label,value,age);row={value,age};c.rows.set(f.label,row)}row.value.textContent=f.value;row.value.className=f.changed&&active&&elapsed<2?'changed':'';row.age.textContent=`${Math.floor((f.age_s||0)+elapsed)} s`;c.table.append(row.value.parentElement)}
 c.card.classList.toggle('stale',!active||(s.packet_age_s!=null&&s.packet_age_s+elapsed>10))}
function draw(){const elapsed=(performance.now()-lastAt)/1000,active=online&&last&&last.state==='running'&&elapsed<4;
 const badge=document.querySelector('#connection');badge.textContent=active?'● Live':online?'Collector inactive':'Disconnected';badge.className='pill '+(active?'ok':'warn');
 const banner=document.querySelector('#banner'),error=!online?'Connection to Raspberry lost. Reconnecting…':last?.error||(last?.state==='stopped'?'Collection stopped.':'');banner.textContent=error;banner.style.display=error?'block':'none';
 const ble=last?.sections_ble||last?.sections||{},ant=last?.sections_ant||{};
 for(const key of keys){renderSection(cards.ble[key],ble[key],elapsed,active);renderSection(cards.ant[key],ant[key],elapsed,online)}
 const bpm=(sections)=>{const s=sections.cardio,f=s?.fields?.find(f=>f.label==='Heart rate');return s?.status==='connected'&&f&&f.age_s+elapsed<10?f.value.replace(/\s*bpm$/,''):'—'};
 cards.ble.cardio.metrics.textContent=`${active?bpm(ble):'—'} bpm`;
 cards.ant.cardio.metrics.textContent=`${online?bpm(ant):'—'} bpm`;
 cards.ble.duo.metrics.textContent=`${active?fmt(ble.duo?.speed_kmh):'—'} km/h · ${active?fmt(ble.duo?.cadence_rpm):'—'} rpm`;
 cards.ant.duo.metrics.textContent=`${online?fmt(ant.duo?.speed_kmh):'—'} km/h · ${online?fmt(ant.duo?.cadence_rpm):'—'} rpm`;
 const shift=ant.sram?.fields?.find(f=>f.label==='Gear');
 cards.ant.sram.metrics.textContent=online&&shift&&shift.age_s+elapsed<10?shift.value:'—';
 document.querySelector('#recording').textContent=last?.log?`${active?'Recording':'Last log'}: ${last.log}`:'Waiting for collection…';
 if(last?.wheel_circumference_m)document.querySelector('#wheel').textContent=`Wheel circumference: ${last.wheel_circumference_m.toFixed(3)} m`;
}
async function poll(){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);try{const response=await fetch('/api/state',{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error(response.status);last=await response.json();lastAt=performance.now();online=true}catch(e){online=false}finally{clearTimeout(timer);draw();setTimeout(poll,500)}}
poll();setInterval(()=>{if(last)draw()},1000);
