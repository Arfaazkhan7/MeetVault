from enum import Enum

class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE      = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class MeetingType(str, Enum):
    PERSONAL  = "PERSONAL"
    WORKSPACE = "WORKSPACE"

class ParticipantStatus(str, Enum):
    INVITED = "INVITED"
    JOINED  = "JOINED"
    LEFT    = "LEFT"
    ABSENT  = "ABSENT"

class MeetingRole(str, Enum):
    HOST     = "HOST"
    ATTENDEE = "ATTENDEE"

class RecordingProcessingStatus(str, Enum):
    STARTING   = "STARTING"
    RECORDING  = "RECORDING"
    FINALIZING = "FINALIZING"
    UPLOADED   = "UPLOADED"
    QUEUED     = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"
