import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.checked=false;this.disabled=false;}
  append(...items){for(const item of items){this.children.push(item);item.parent=this;}}
  setAttribute(name,value){this[name]=value;}
  set value(value){this._value=value;}
  get value(){return this._value??(this.tag==='select'?this.children[0]?.value:'')??'';}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return (this.text||'')+this.children.map(c=>c.textContent).join('');}
  querySelector(selector){return this.children.find(c=>selector===`[value="${c.value}"]`);}
  get firstChild(){return this.children[0];}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('translation panel trusts server packets, queues device speech, and cancels on exit',async()=>{
  const body=new Element('body'),handlers={},utterances=[],requests=[];let cleared=false;
  const context={console,URL,TextDecoder,TextEncoder,JSON,Math,Date,Promise,Set,ArrayBuffer,DataView,Int16Array,crypto,
    setTimeout,clearTimeout,setInterval:()=>1,clearInterval:()=>{cleared=true;},
    document:{body,createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('text');e.textContent=text;return e;}},
    localStorage:{getItem:()=>JSON.stringify({public_id:'ME'})},
    SpeechSynthesisUtterance:class{constructor(text){this.text=text;}},
    apiFetch:async(path,options)=>{requests.push({path,options});return Response.json(options?{}:{available:true,enabled:true,active_languages:['en'],segments:[],audio_seconds_used:0,meeting_audio_limit_seconds:300,spoken_service_available:false});},
    window:{speechSynthesis:{getVoices:()=>[{lang:'en-US'}],speak:u=>utterances.push(u),cancel:()=>{}}}};
  vm.createContext(context);vm.runInContext(await readFile(new URL('../../web/translation-client.js',import.meta.url),'utf8'),context);
  context.window.MeetVaultTranslation.connect({room:{on:(event,fn)=>{handlers[event]=fn;}},meetingId:'MEETING',isHost:true,microphone:{getAudioTracks:()=>[]}});await settle();
  const panel=body.children[0],form=panel.children[0].children[1];
  const selects=form.children.filter(c=>c.tag==='label').map(c=>c.children.find(v=>v.tag==='select')).filter(Boolean);
  const [,target,output]=selects;target.value='en';await target.onchange();output.value='device';output.onchange();
  const send=(id,participant)=>handlers.dataReceived(new TextEncoder().encode(JSON.stringify({meeting_id:'MEETING',segment_id:id,speaker_id:'OTHER',speaker_name:'Speaker',source_language:'ta',original_text:'வணக்கம்',translations:{en:'Hello '+id}})),participant,0,'meetvault.translation.v1');
  send('forged',{identity:'ordinary-user'});await settle();assert.equal(utterances.length,0);
  send('one');send('two');send('one');await settle();assert.equal(utterances.length,1);assert.equal(utterances[0].text,'Hello one');
  utterances[0].onend();await settle();assert.equal(utterances.length,2);assert.equal(utterances[1].text,'Hello two');
  context.window.MeetVaultTranslation.stop();await settle();assert.equal(body.children.length,0);assert.equal(cleared,true);
  assert.ok(requests.some(r=>r.options?.method==='PUT'));
});
