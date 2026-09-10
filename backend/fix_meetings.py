import re

with open('app/api/v1/meetings.py', 'r') as f:
    text = f.read()

match = re.search(r'# -- Join by Invite Code ------------------------------------------------------\n(.*)', text, re.DOTALL)
if match:
    join_block = match.group(0)
    text = text.replace(join_block, '')
    
    insert_pos = text.find('@router.get("/meetings/{meeting_id}", response_model=MeetingResponse)')
    if insert_pos != -1:
        text = text[:insert_pos] + join_block + '\n\n' + text[insert_pos:]

endpoints = '''
from app.schemas.meeting import MeetingStartResponse

@router.post("/meetings/{meeting_id}/start", response_model=MeetingStartResponse)
def start_meeting_route(
    meeting_id: str,
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.meeting_service import start_meeting
    return start_meeting(db, meeting, current_user)

@router.post("/meetings/{meeting_id}/end", response_model=MeetingStartResponse)
def end_meeting_route(
    meeting_id: str,
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.meeting_service import end_meeting
    return end_meeting(db, meeting, current_user)

'''

text += endpoints

text = text.replace('payload: dict,  # {"invite_code": "MTG-ABC123"}', 'payload: JoinByInviteCodeRequest,')
text = text.replace('invite_code = payload.get("invite_code", "").strip().upper()', 'invite_code = payload.invite_code.strip().upper()')
text = text.replace('MeetingConnectionResponse,\n)', 'MeetingConnectionResponse,\n    JoinByInviteCodeRequest,\n)')

with open('app/api/v1/meetings.py', 'w') as f:
    f.write(text)
