import json
from livekit.api import AccessToken, VideoGrants
from datetime import datetime, timedelta, timezone


from app.core.config import settings
from app.models.meeting import Meeting, MeetingParticipant
from app.models.user import User


def _validate_livekit_config() -> None:
    """Validate that LiveKit is properly configured (not using placeholder values)."""
    if not settings.LIVEKIT_URL or settings.LIVEKIT_URL == "wss://your-livekit-url":
        raise RuntimeError(
            "LIVEKIT_URL is not configured. Please set a valid LiveKit server URL in .env"
        )
    if not settings.LIVEKIT_API_KEY or settings.LIVEKIT_API_KEY == "your_livekit_api_key":
        raise RuntimeError(
            "LIVEKIT_API_KEY is not configured. Please set a valid LiveKit API key in .env"
        )
    if not settings.LIVEKIT_API_SECRET or settings.LIVEKIT_API_SECRET == "your_livekit_api_secret":
        raise RuntimeError(
            "LIVEKIT_API_SECRET is not configured. Please set a valid LiveKit API secret in .env"
        )


def room_name_for_meeting(meeting: Meeting) -> str:
    return f"meeting-{meeting.public_id}"


def participant_identity(user: User, participant: MeetingParticipant) -> str:
    return f"{user.public_id}:{participant.id}"


def generate_meeting_token(
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
