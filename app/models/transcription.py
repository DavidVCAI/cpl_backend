from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class TranscriptSegment(BaseModel):
    """Individual transcript segment"""
    speaker_id: Optional[str] = None
    text: str
    language: str = "es"
    confidence: float
    timestamp: datetime
    start_time: float = Field(..., description="Seconds from event start")
    end_time: float


class Transcription(BaseModel):
    """Event transcription model"""
    id: Optional[str] = Field(alias="_id", default=None)
    event_id: str
    room_name: str
    segments: List[TranscriptSegment] = Field(default_factory=list)
    full_transcript: str = ""
    languages_detected: List[str] = Field(default_factory=lambda: ["es"])
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
