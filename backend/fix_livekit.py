import re

with open('app/services/livekit_service.py', 'r') as f:
    text = f.read()

text = re.sub(r'from jose import jwt\n', '', text)
if 'import json' not in text:
    text = 'import json\nfrom livekit.api import AccessToken, VideoGrants\n' + text

new_func = '''def generate_meeting_token(
    meeting: Meeting,
    user: User,
    participant: MeetingParticipant,
) -> tuple[str, datetime]:
    _validate_livekit_config()
    
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.LIVEKIT_TOKEN_EXPIRE_MINUTES
    )
    room_name = room_name_for_meeting(meeting)
    
    token = AccessToken(
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET
    ).with_identity(
        participant_identity(user, participant)
    ).with_name(
        user.full_name
    ).with_grants(
        VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
    ).with_metadata(
        json.dumps({
            "user_public_id": user.public_id,
            "meeting_id": meeting.public_id,
            "participant_id": str(participant.id),
            "role": participant.role,
        })
    )
    # the TTL for livekit SDK tokens
    token.ttl = timedelta(minutes=settings.LIVEKIT_TOKEN_EXPIRE_MINUTES)
    
    return token.to_jwt(), expires_at
'''

text = re.sub(r'def generate_meeting_token\(.*', new_func, text, flags=re.DOTALL)

with open('app/services/livekit_service.py', 'w') as f:
    f.write(text)
