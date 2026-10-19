import json
from livekit.api import AccessToken, VideoGrants
from datetime import datetime, timedelta, timezone


from app.core.config import settings
from app.models.meeting import Meeting, MeetingParticipant
from app.models.user import User


def _validate_livekit_config() -> None:
    """Validate that LiveKit is properly configured (not using placeholder values)."""
    # Development and tests can inspect signed tokens without a running LiveKit
    # server. Production must use real credentials so clients can connect.
    if settings.ENVIRONMENT.lower() == "development":
        return
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


def _get_livekit_http_url() -> str:
    """Convert wss:// or ws:// LiveKit URL to https:// or http:// for REST API."""
    url = settings.LIVEKIT_URL or ""
    if url.startswith("wss://"):
        return "https://" + url[6:]
    elif url.startswith("ws://"):
        return "http://" + url[5:]
    return url


async def start_room_composite_audio_egress(
    room_name: str,
    output_filepath: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Attempt to start a LiveKit Room Composite Egress (Audio Only).
    Returns (egress_id, error_message).
    Gracefully handles environments without egress pods configured.
    """
    if settings.ENVIRONMENT.lower() == "development" or not settings.LIVEKIT_URL or settings.LIVEKIT_URL == "wss://your-livekit-url":
        return None, "LiveKit Egress not enabled in development/placeholder environment"

    from livekit.api import LiveKitAPI, RoomCompositeEgressRequest, EncodedFileOutput

    http_url = _get_livekit_http_url()
    try:
        api = LiveKitAPI(http_url, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        req = RoomCompositeEgressRequest(
            room_name=room_name,
            audio_only=True,
            file_outputs=[
                EncodedFileOutput(
                    filepath=output_filepath,
                )
            ],
        )
        egress_info = await api.egress.start_room_composite_egress(req)
        await api.aclose()
        egress_id = getattr(egress_info, "egress_id", None)
        return egress_id, None
    except Exception as exc:
        return None, f"LiveKit Egress startup failed: {exc}"


async def stop_livekit_egress(egress_id: str) -> tuple[bool, Optional[str]]:
    """Attempt to stop a running LiveKit egress job."""
    if not egress_id or settings.ENVIRONMENT.lower() == "development":
        return False, "Invalid egress ID or dev environment"

    from livekit.api import LiveKitAPI

    http_url = _get_livekit_http_url()
    try:
        api = LiveKitAPI(http_url, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        await api.egress.stop_egress(egress_id)
        await api.aclose()
        return True, None
    except Exception as exc:
        return False, f"LiveKit stop egress failed: {exc}"


def verify_livekit_webhook(body_bytes: bytes, auth_header: str):
    """
    Verify and parse incoming LiveKit webhook event.
    Returns the parsed WebhookEvent object or raises ValueError.
    """
    from livekit.api import WebhookReceiver, TokenVerifier

    if not auth_header:
        raise ValueError("Missing authorization header in webhook request")

    verifier = TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    receiver = WebhookReceiver(verifier)
    return receiver.receive(body_bytes.decode("utf-8", errors="replace"), auth_header)
