/* Native Worker integration: authenticated LiveKit rooms, private direct
 * recording uploads, and evidence-backed cross-meeting answers. */
(() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  async function checked(response){const data=await response.json();if(!response.ok)throw new Error(data.detail||`Request failed (${response.status})`);return data;}
  let creating=false,asking=false,liveRoom=null,sdkPromise=null;
  const oldCreate=createNewMeeting;
  createNewMeeting=async function(){if(creating)return;creating=true;try{await oldCreate();}finally{creating=false;}};
  doJoin=async function(value){
    let code=String(value||document.getElementById('join-code')?.value||'').trim();
    if(!code){showToast('Enter a meeting code or invite link.');return;}
    try{const link=new URL(code,location.origin);const found=link.hash.match(/^#\/join\/([^/?]+)/);if(found)code=decodeURIComponent(found[1]);}catch{}
    code=code.toUpperCase();
    if(!/^[A-Z0-9-]{4,80}$/.test(code)){showToast('Enter a valid meeting code or invite link.');return;}
    try{
      const joined=await checked(await apiFetch('/meetings/join',{method:'POST',body:JSON.stringify({invite_code:code})}));
      currentMeetingId=joined.meeting_id;currentRoomCode=code;isMeetingHost=joined.participant?.role==='HOST';
      await checked(await apiFetch(`/meetings/${encodeURIComponent(currentMeetingId)}/room/join`,{method:'POST'}));
      await startCall(code);
    }catch(e){showToast(e.message);}
  };
  copyCurrentRoomLink=function(){navigator.clipboard.writeText(`${location.origin}/index.html#/join/${encodeURIComponent(currentRoomCode)}`).then(()=>showToast('Meeting link copied')).catch(()=>showToast('Copy the meeting code shown above.'));};
  const invite=location.hash.match(/^#\/join\/([^/?]+)/)?.[1]||sessionStorage.getItem('mv_pending_invite');
  if(invite){sessionStorage.setItem('mv_pending_invite',invite);const input=document.getElementById('join-code');if(input)input.value=decodeURIComponent(invite);}

  vaultSearch=async function(){
    if(asking)return;
    const question=document.getElementById('vault-q')?.value.trim(),result=document.getElementById('vault-result');if(!question||!result)return;
    const scope=document.getElementById('vault-scope')?.value||'all';
    const ids=[...document.querySelectorAll('[data-vault-meeting]:checked')].map(e=>e.value);
    if(scope==='selected_meetings'&&!ids.length){showToast('Select meetings below before asking.');return;}
    asking=true;result.style.display='block';result.textContent='Checking saved meeting evidence…';result.setAttribute('aria-busy','true');
    try{
      const answer=await checked(await apiFetch('/cross-meeting/query',{method:'POST',body:JSON.stringify({question,scope,meeting_ids:scope==='selected_meetings'?ids:null,limit:20})}));
      result.replaceChildren();
      const notice=document.createElement('p');notice.style.fontWeight='700';notice.textContent=answer.insufficient_evidence?'Not enough saved evidence':answer.ai_available===false?'Saved evidence · AI temporarily unavailable':'Cross-meeting answer';result.append(notice);
      const content=document.createElement('div');content.style.whiteSpace='pre-wrap';content.textContent=answer.synthesis;result.append(content);
      for(const citation of answer.evidence_citations||[]){
        const details=document.createElement('details'),summary=document.createElement('summary'),quote=document.createElement('p');
        summary.textContent=`[${citation.citation_id}] ${citation.meeting_title||citation.meeting_id}${citation.start_time!=null?' · '+Math.floor(citation.start_time/60)+':'+String(Math.floor(citation.start_time%60)).padStart(2,'0'):''}`;
        quote.textContent=citation.text||'';details.append(summary,quote);result.append(details);
      }
      if(answer.statements?.length){
        const stmtDetails=document.createElement('details'),stmtSummary=document.createElement('summary'),stmtList=document.createElement('ul');
        stmtSummary.textContent=`Attributed statements (${answer.statements.length})`;
        for(const st of answer.statements){
          const li=document.createElement('li');
          const badge=st.is_verified_user?' (confirmed identity)':' (unverified speaker)';
          li.textContent=`${st.speaker_name}${badge}: "${st.text}"`;
          stmtList.append(li);
        }
        stmtDetails.append(stmtSummary,stmtList);result.append(stmtDetails);
      }
      if(answer.insufficient_evidence){const help=document.createElement('p');help.textContent='Finish a recorded meeting or upload a recording to create transcripts, then ask again.';result.append(help);}
    }catch(error){result.textContent=error.message;}finally{asking=false;result.removeAttribute('aria-busy');}
  };
  const oldVault=renderVaultMeetings;
  renderVaultMeetings=async function(){
    await oldVault();const container=document.getElementById('vault-meetings-list');if(!container||fetchHistoryError)return;
    const items=[...container.children];cachedCloudMeetings.forEach((m,i)=>{
      const row=items[i];if(!row)return;
      const label=document.createElement('label');label.style.cssText='display:flex;align-items:center;gap:6px;font-size:0.8rem;margin-right:8px;';
      const input=document.createElement('input');input.type='checkbox';input.value=m.meeting_id;input.dataset.vaultMeeting='true';input.setAttribute('aria-label',`Include ${m.title||'meeting'} in analysis`);label.append(input,document.createTextNode('Include in analysis'));row.prepend(label);
      const view=document.createElement('button');view.type='button';view.className='btn-blue-action';view.style.cssText='border-radius:8px;padding:8px 12px;font-size:0.8rem;';view.textContent='Transcript & summary';
      view.addEventListener('click',()=>showIntelligence(m));row.append(view);
    });
  };
  async function showIntelligence(meeting){
    const result=document.getElementById('vault-result');result.style.display='block';result.textContent='Loading saved intelligence…';
    try{
      const [transcript,analysis]=await Promise.all([
        apiFetch(`/transcripts/meetings/${encodeURIComponent(meeting.meeting_id)}`).then(checked),
        apiFetch(`/meetings/${encodeURIComponent(meeting.meeting_id)}/full-analysis`).then(checked)]);
      result.replaceChildren();const title=document.createElement('h3');title.textContent=meeting.title;result.append(title);
      const summary=document.createElement('p');summary.style.whiteSpace='pre-wrap';summary.textContent=analysis.summary?.summary_text||'No summary yet.';result.append(summary);
      const details=document.createElement('details'),heading=document.createElement('summary'),transcriptText=document.createElement('p');heading.textContent='Transcript';transcriptText.style.whiteSpace='pre-wrap';
      transcriptText.textContent=(transcript.segments||[]).map(s=>{
        const time=`${Math.floor(s.start_time/60)}:${String(Math.floor(s.start_time%60)).padStart(2,'0')}`;
        const isVerified=['verified','confirmed'].includes(s.attribution_status);
        const badge=isVerified?' [confirmed]':s.speaker_label&&s.speaker_label!=='SPEAKER_UNASSIGNED'?' [unverified]':' [unassigned]';
        const speaker=s.speaker_name||s.speaker_label||'SPEAKER_UNASSIGNED';
        return `${time} ${speaker}${badge}: ${s.text}`;
      }).join('\n')||'No transcript saved yet.';details.append(heading,transcriptText);result.append(details);
      if(meeting.my_role==='HOST'){
        const analyze=document.createElement('button');analyze.className='btn-blue-action';analyze.textContent='Generate summary';analyze.disabled=!transcript.segments?.length;
        analyze.onclick=async()=>{analyze.disabled=true;try{await checked(await apiFetch(`/meetings/${encodeURIComponent(meeting.meeting_id)}/analyze`,{method:'POST'}));await showIntelligence(meeting);}catch(e){showToast(e.message);analyze.disabled=false;}};
        const upload=document.createElement('input');upload.type='file';upload.accept='audio/*,video/webm,video/mp4';upload.setAttribute('aria-label','Upload meeting recording');
        upload.onchange=async()=>{const file=upload.files[0];if(!file)return;upload.disabled=true;try{await saveRecording(meeting.meeting_id,{blob:file,duration:0});showToast('Recording saved. AI processing is queued.');}catch(e){showToast(e.message);}finally{upload.disabled=false;}};
        result.append(analyze,document.createElement('br'),document.createTextNode('Upload a recording (up to 20 MB): '),upload);
      }
    }catch(e){result.textContent=e.message;}
  }
  async function saveRecording(meetingId,recording,sessionId=null){
    if(recording.blob.size>20971520)throw new Error('Recording exceeds the 20 MB free upload limit. Use a shorter recording.');
    const base=`/meetings/${encodeURIComponent(meetingId)}/recordings`;
    const signed=await checked(await apiFetch(`${base}/upload-url`,{method:'POST',body:JSON.stringify({size:recording.blob.size,filename:recording.blob.name||'recording.webm',content_type:recording.blob.type||'audio/webm',duration_seconds:recording.duration,session_id:sessionId})}));
    const uploaded=await fetch(signed.upload_url,{method:'PUT',headers:{'content-type':recording.blob.type||'audio/webm'},body:recording.blob});
    if(!uploaded.ok)throw new Error('Private recording upload failed. Please retry.');
    return checked(await apiFetch(`${base}/complete`,{method:'POST',body:JSON.stringify({recording_id:signed.recording_id})}));
  }
  uploadMeetingRecording=async function(recording){
    if(!recording?.blob||!currentMeetingId||!isMeetingHost)return;
    const id=currentMeetingId,sessionId=currentRecordingSessionId;
    showToast('Saving private recording…');
    try{await saveRecording(id,recording,sessionId);showToast('Recording saved. Transcription and summary are queued.');}
    catch(e){showToast(e.message);console.warn('Recording finalization failed');}
  };

  function sdk(){
    if(window.LivekitClient)return Promise.resolve(window.LivekitClient);
    if(!sdkPromise)sdkPromise=new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='https://cdn.jsdelivr.net/npm/livekit-client@2.23.0/dist/livekit-client.umd.js';
      script.onload=()=>window.LivekitClient?resolve(window.LivekitClient):reject(new Error('Meeting SDK did not initialize'));
      script.onerror=()=>{sdkPromise=null;reject(new Error('Meeting SDK could not load'));};document.head.append(script);
    });return sdkPromise;
  }
  function syncRemote(participant,LK){
    const old=activePeerCallsMap[participant.identity];const remoteStream=old?.remoteStream||new MediaStream();
    const tracks=[];let camera=null,screen=null;
    for(const publication of participant.trackPublications.values()){
      const track=publication.track?.mediaStreamTrack;if(!track)continue;
      if(track.kind==='audio')tracks.push(track);
      else if(publication.source===LK.Track.Source.ScreenShare)screen=track;else camera=track;
    }
    if(screen||camera)tracks.push(screen||camera);
    for(const t of remoteStream.getTracks())if(!tracks.includes(t))remoteStream.removeTrack(t);
    for(const t of tracks)if(!remoteStream.getTracks().includes(t))remoteStream.addTrack(t);
    activePeerCallsMap[participant.identity]={remoteStream,remoteName:escape(participant.name||'Participant'),close(){}};
    includeStreamInMeetingRecording(remoteStream);updateRoomParticipants();
  }
  initP2PCall=async function(){
    try{
      const LK=await sdk();const connection=await checked(await apiFetch(`/meetings/${encodeURIComponent(currentMeetingId)}/room/connect`,{method:'POST'}));
      isMeetingHost=connection.participant?.role==='HOST';
      const room=new LK.Room({adaptiveStream:true,dynacast:true});liveRoom=room;
      const refresh=(_,publication,participant)=>{if(participant)syncRemote(participant,LK);};
      room.on(LK.RoomEvent.TrackSubscribed,refresh);room.on(LK.RoomEvent.TrackUnsubscribed,refresh);
      room.on(LK.RoomEvent.ParticipantConnected,p=>syncRemote(p,LK));
      room.on(LK.RoomEvent.ParticipantDisconnected,p=>{delete activePeerCallsMap[p.identity];updateRoomParticipants();});
      room.on(LK.RoomEvent.DataReceived,(bytes,participant)=>{
        if(!participant||bytes.byteLength>8192)return;
        try{const data=JSON.parse(new TextDecoder().decode(bytes));
          if(data.type==='live_caption')handleLiveCaption({...data,speaker:participant.name||'Participant'},participant.identity);
          if(data.type==='room_ended'&&JSON.parse(participant.metadata||'{}').role==='HOST'){showToast('The host ended this meeting');endCall(false);}
        }catch{}
      });
      room.on(LK.RoomEvent.Disconnected,()=>{if(liveRoom===room)showToast('Meeting connection closed. Leave and rejoin to reconnect.');});
      await room.connect(connection.livekit_url,connection.token);
      if(stream)for(const track of stream.getTracks())await room.localParticipant.publishTrack(track,{source:track.kind==='audio'?LK.Track.Source.Microphone:LK.Track.Source.Camera});
      for(const p of room.remoteParticipants.values())syncRemote(p,LK);
      window.MeetVaultTranslation?.connect({room,meetingId:currentMeetingId,isHost:isMeetingHost,microphone:stream});
      showToast('Connected to meeting');
    }catch(e){showToast(`Unable to connect: ${e.message}`);await endCall();}
  };
  const oldStop=stopStream;
  stopStream=function(){window.MeetVaultTranslation?.stop();const room=liveRoom;liveRoom=null;meetingConnections=[];if(room)room.disconnect();oldStop();};
  broadcastLiveCaption=function(caption){if(liveRoom)liveRoom.localParticipant.publishData(new TextEncoder().encode(JSON.stringify({...caption,type:'live_caption'})),{reliable:false}).catch(()=>{});};
  const oldEnd=endCall;
  endCall=async function(endForEveryone=false){
    if(endForEveryone&&isMeetingHost&&liveRoom)await liveRoom.localParticipant.publishData(new TextEncoder().encode(JSON.stringify({type:'room_ended'})),{reliable:true}).catch(()=>{});
    await oldEnd(endForEveryone);
  };
  const oldMic=toggleMic,oldCam=toggleCam;
  toggleMic=function(){oldMic();if(liveRoom)liveRoom.localParticipant.setMicrophoneEnabled(micOn).catch(()=>showToast('Microphone could not be changed'));};
  toggleCam=function(){oldCam();if(liveRoom)liveRoom.localParticipant.setCameraEnabled(camOn).catch(()=>showToast('Camera could not be changed'));};
  shareScreen=async function(){
    if(!liveRoom)return;
    if(isScreenSharing){stopScreenShare();return;}
    try{
      await liveRoom.localParticipant.setScreenShareEnabled(true,{audio:true});
      const LK=await sdk(),tracks=[];
      for(const source of [LK.Track.Source.ScreenShare,LK.Track.Source.ScreenShareAudio]){
        const track=liveRoom.localParticipant.getTrackPublication(source)?.track?.mediaStreamTrack;if(track)tracks.push(track);
      }
      screenStream=new MediaStream(tracks);isScreenSharing=true;
      if(tracks[0])tracks[0].addEventListener('ended',()=>stopScreenShare(),{once:true});
      document.getElementById('btn-screenshare')?.classList.add('active');
      const bar=document.getElementById('presentation-top-bar');if(bar)bar.style.display='flex';
      renderMeetGrid();showToast('Screen sharing started');
    }
    catch{showToast('Screen sharing was cancelled or is unavailable');}
  };
  stopScreenShare=function(){if(liveRoom)liveRoom.localParticipant.setScreenShareEnabled(false).catch(()=>{});isScreenSharing=false;screenStream=null;document.getElementById('btn-screenshare')?.classList.remove('active');const bar=document.getElementById('presentation-top-bar');if(bar)bar.style.display='none';renderMeetGrid();};
})();
