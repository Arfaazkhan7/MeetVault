/* Shared translation: only microphone capture/standard browser voice playback
 * happen locally. ASR and translation run on the authorized server. */
(() => {
  'use strict';
  const languages={en:'English',ta:'Tamil',hi:'Hindi'};
  const topic='meetvault.translation.v1';
  let current=null;
  async function checked(response){const value=await response.json();if(!response.ok)throw Object.assign(new Error(value.detail||'Translation request failed'),{status:response.status});return value;}
  function select(label,options){
    const wrapper=document.createElement('label');wrapper.textContent=label+' ';const input=document.createElement('select');
    input.style.cssText='padding:7px;border-radius:6px;background:#fff;color:#172033;max-width:100%;';
    for(const [value,text] of Object.entries(options)){const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option);}wrapper.append(input);return {wrapper,input};
  }
  function checkbox(text){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';label.append(input,document.createTextNode(' '+text));return {label,input};}
  function wav(chunks){
    const length=chunks.reduce((sum,c)=>sum+c.length,0),bytes=new ArrayBuffer(44+length*2),view=new DataView(bytes);
    const str=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
    str(0,'RIFF');view.setUint32(4,36+length*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,length*2,true);
    let offset=44;for(const c of chunks)for(const sample of c){view.setInt16(offset,sample,true);offset+=2;}return bytes;
  }
  function status(s,message){if(current===s)s.status.textContent=message;}
  async function preferences(s){
    if(current!==s)return;
    await checked(await apiFetch(s.base+'/preferences',{method:'PUT',body:JSON.stringify({source_language:s.source.value,target_language:s.target.value||null,share_audio:s.share.checked})}));
  }
  function resetCapture(s){s.chunks=[];s.pre=null;s.silence=0;}
  async function capture(s){
    const needed=current===s&&s.config?.enabled&&s.share.checked&&s.config.active_languages.length&&s.microphone?.getAudioTracks().length;
    if(!needed){if(s.context){if(s.node)s.node.port.onmessage=null;s.sourceNode?.disconnect();s.node?.disconnect();await s.context.close().catch(()=>{});s.context=null;}resetCapture(s);return;}
    if(s.context)return;
    const AudioContext=window.AudioContext||window.webkitAudioContext;
    if(!AudioContext||!window.AudioWorkletNode){s.share.checked=false;status(s,'This browser cannot capture translation audio. You can still receive captions.');await preferences(s);return;}
    const context=new AudioContext();s.context=context;
    try{
      await context.audioWorklet.addModule('translation-capture.js');if(current!==s||s.context!==context){await context.close().catch(()=>{});return;}
      s.sourceNode=context.createMediaStreamSource(new MediaStream(s.microphone.getAudioTracks()));
      s.node=new AudioWorkletNode(context,'meetvault-translation-capture');s.sourceNode.connect(s.node);s.node.connect(context.destination);await context.resume();
      s.node.port.onmessage=event=>{
        if(current!==s||!s.share.checked||!s.config?.enabled)return;
        const block=new Int16Array(event.data);let sum=0;for(const sample of block)sum+=(sample/32768)**2;
        const voiced=Math.sqrt(sum/block.length)>0.012;
        if(!s.microphone.getAudioTracks().some(t=>t.enabled)){resetCapture(s);return;}
        if(!s.chunks.length){if(!voiced){s.pre=block;return;}if(s.pre)s.chunks.push(s.pre);s.pre=null;}
        s.chunks.push(block);s.silence=voiced?0:s.silence+1;
        if(s.chunks.length>=12||s.silence>=2){const chunks=s.chunks;resetCapture(s);if(s.pending<2)upload(s,wav(chunks));else status(s,'Translation is catching up; a speech segment was skipped.');}
      };
    }catch{await context.close().catch(()=>{});s.context=null;s.share.checked=false;await preferences(s).catch(()=>{});status(s,'Microphone translation could not start. Captions from other speakers remain available.');}
  }
  async function upload(s,bytes){
    s.pending++;
    try{
      const row=await checked(await apiFetch(s.base+'/audio?segment_id='+crypto.randomUUID(),{method:'POST',headers:{'Content-Type':'audio/wav'},body:bytes,signal:AbortSignal.timeout(30000)}));
      if(row.status==='COMPLETED')receive(s,{segment_id:row.id,speaker_id:row.user_id,...row});
    }catch(e){
      if(current!==s)return;
      if([429,503].includes(e.status)){s.share.checked=false;await preferences(s).catch(()=>{});await capture(s);}
      status(s,e.message);
    }finally{s.pending--;}
  }
  function cancelSpeech(s){s.speechVersion++;if(s.utterance)window.speechSynthesis?.cancel();if(s.audio)s.audio.pause();s.finishSpeech?.();}
  async function speak(s,item,text,language,mode,version){
    if(mode==='captions'||!language||current!==s||version!==s.speechVersion)return;
    if(mode==='shared'){
      try{
        const response=await apiFetch(`${s.base}/segments/${encodeURIComponent(item.segment_id||item.id)}/speech/${language}`,{signal:AbortSignal.timeout(20000)});
        if(!response.ok)throw new Error('Shared translated audio is unavailable; captions remain visible.');
        const blob=await response.blob();if(blob.size>2000000)throw new Error('Translated audio is too large');
        if(current!==s||version!==s.speechVersion)return;const url=URL.createObjectURL(blob),audio=new Audio(url);s.audio=audio;s.audioUrl=url;
        await new Promise(resolve=>{
          const timer=setTimeout(()=>finish(),30000),finish=()=>{clearTimeout(timer);audio.pause();URL.revokeObjectURL(url);s.audio=null;s.audioUrl=null;s.finishSpeech=null;resolve();};
          s.finishSpeech=finish;audio.onended=audio.onerror=finish;audio.play().catch(()=>{status(s,'Click the output selector again to allow translated audio.');finish();});
        });
      }catch(e){status(s,e.message);}
    }else if(mode==='device'){
      const voice=window.speechSynthesis?.getVoices().find(v=>v.lang.toLowerCase().split('-')[0]===language);
      if(!voice){status(s,`No ${languages[language]} device voice is installed. Captions remain available.`);return;}
      const utterance=new SpeechSynthesisUtterance(text);utterance.voice=voice;utterance.lang=voice.lang;
      await new Promise(resolve=>{const timer=setTimeout(()=>finish(),30000),finish=()=>{clearTimeout(timer);s.utterance=null;s.finishSpeech=null;resolve();};utterance.onend=utterance.onerror=finish;s.finishSpeech=finish;s.utterance=utterance;window.speechSynthesis.speak(utterance);});
    }
  }
  function receive(s,item){
    if(current!==s||!s.target.value)return;const id=item.segment_id||item.id,key=id+':'+s.target.value;
    if(s.seen.has(key))return;s.seen.add(key);if(s.seen.size>200)s.seen.delete(s.seen.values().next().value);
    const text=item.translations?.[s.target.value];if(!text)return;
    const line=document.createElement('div'),name=document.createElement('strong'),translated=document.createElement('p'),original=document.createElement('small');
    name.textContent=item.speaker_name||'Participant';translated.textContent=text;original.textContent=`Original (${languages[item.source_language]||item.source_language}): ${item.original_text}`;
    line.style.cssText='padding:8px 0;border-bottom:1px solid #cbd5e1;';translated.style.margin='4px 0';line.append(name,translated,original);s.lines.append(line);while(s.lines.children.length>10)s.lines.firstChild.remove();s.lines.scrollTop=s.lines.scrollHeight;
    const mine=JSON.parse(localStorage.getItem('mv_user')||'{}').public_id;
    if((item.speaker_id||item.user_id)!==mine&&s.speechPending<3){const language=s.target.value,mode=s.output.value,version=s.speechVersion;s.speechPending++;s.speech=s.speech.catch(()=>{}).then(()=>speak(s,item,text,language,mode,version)).finally(()=>s.speechPending--);}
  }
  async function refresh(s){
    if(current!==s||s.refreshing)return;s.refreshing=true;
    try{
      if(++s.polls%3===1)await preferences(s);
      const config=await checked(await apiFetch(s.base));if(current!==s)return;s.config=config;
      s.hostButton&&(s.hostButton.textContent=config.enabled?'Stop meeting translation':'Enable meeting translation');
      s.sharedOption.disabled=!config.spoken_service_available;
      if(s.output.value==='shared'&&!config.spoken_service_available)s.output.value='captions';
      status(s,!config.available?'Translation is not enabled on this deployment.':!config.enabled?'Waiting for the host to enable translation.':`Translation active · ${Math.round(config.audio_seconds_used)}/${config.meeting_audio_limit_seconds} audio seconds used · standard voices`);
      for(const item of config.segments)receive(s,item);
      await capture(s);
    }catch(e){status(s,e.message);}
    finally{s.refreshing=false;}
  }
  function stop(){
    const s=current;if(!s)return;current=null;clearInterval(s.timer);
    if(s.context){s.node&&(s.node.port.onmessage=null);s.sourceNode?.disconnect();s.node?.disconnect();s.context.close().catch(()=>{});}
    cancelSpeech(s);s.panel.remove();
  }
  function connect({room,meetingId,isHost,microphone}){
    stop();
    const s={room,microphone,base:`/meetings/${encodeURIComponent(meetingId)}/translation`,chunks:[],pre:null,pending:0,speechPending:0,speechVersion:0,speech:Promise.resolve(),seen:new Set(),polls:0,silence:0};current=s;
    const panel=document.createElement('section');s.panel=panel;panel.id='meeting-translation';panel.setAttribute('aria-label','Meeting translation');
    panel.style.cssText='position:fixed;right:16px;top:80px;width:min(380px,calc(100vw - 32px));max-height:65vh;overflow:auto;background:#f8fafc;color:#172033;border:1px solid #cbd5e1;border-radius:12px;padding:14px;z-index:110;box-shadow:0 4px 20px #0002;font-size:14px;';
    const details=document.createElement('details'),heading=document.createElement('summary');heading.textContent='Meeting translation';heading.style.fontWeight='700';details.append(heading);panel.append(details);
    const form=document.createElement('div');form.style.cssText='display:grid;gap:12px;padding-top:12px;';details.append(form);
    const source=select('I speak',languages),target=select('Translate captions to',{'':'Off',...languages}),output=select('Output',{captions:'Captions',shared:'Shared standard voice',device:'Device voice (if installed)'}),share=checkbox('Send my microphone audio for translation');
    Object.assign(s,{source:source.input,target:target.input,output:output.input,share:share.input,sharedOption:output.input.querySelector('[value="shared"]')});s.sharedOption.disabled=true;
    const notice=document.createElement('p');notice.textContent='Translation sends consenting speakers’ audio to Cloudflare AI. Captions are stored for delivery; the host can additionally save original speech to Vault. Generated voices are standard voices.';notice.style.cssText='font-size:12px;margin:0;';
    s.status=document.createElement('p');s.status.setAttribute('role','status');s.status.style.cssText='margin:0;font-size:12px;';
    if(isHost){
      const save=checkbox('Save original speech to Vault for meeting analysis');s.hostButton=document.createElement('button');s.hostButton.type='button';s.hostButton.textContent='Loading translation controls…';
      s.hostButton.onclick=async()=>{s.hostButton.disabled=true;try{await checked(await apiFetch(s.base,{method:'POST',body:JSON.stringify({enabled:!s.config?.enabled,save_transcripts:save.input.checked})}));await refresh(s);}catch(e){status(s,e.message);}finally{s.hostButton.disabled=false;}};
      form.append(save.label,s.hostButton);
    }
    form.append(source.wrapper,target.wrapper,output.wrapper,share.label,notice,s.status);
    s.lines=document.createElement('div');s.lines.style.cssText='max-height:180px;overflow:auto;';s.lines.setAttribute('aria-live','polite');form.append(s.lines);document.body.append(panel);
    const change=async()=>{cancelSpeech(s);try{await preferences(s);await refresh(s);}catch(e){status(s,e.message);}};
    source.input.onchange=target.input.onchange=share.input.onchange=change;
    output.input.onchange=()=>{cancelSpeech(s);if(output.input.value!=='captions')status(s,'Use headphones to prevent translated speech feeding back into the microphone.');};
    room.on('dataReceived',(bytes,participant,_kind,packetTopic)=>{if(current!==s||participant||packetTopic!==topic||bytes.byteLength>14000)return;try{const item=JSON.parse(new TextDecoder().decode(bytes));if(item.meeting_id===meetingId)receive(s,item);}catch{}});
    refresh(s);s.timer=setInterval(()=>refresh(s),6000);
  }
  window.MeetVaultTranslation={connect,stop};
})();
