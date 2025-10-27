from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId


class GeoLocation(BaseModel):
    """GeoJSON Point"""
    type: str = "Point"
    coordinates: list[float] = Field(..., description="[longitude, latitude]")
    address: Optional[str] = None
    city: str = "Bogotá"


class RoomInfo(BaseModel):
    """Daily.co room information"""
    daily_room_name: Optional[str] = None
    daily_room_url: Optional[str] = None
    max_participants: int = 15
    current_participants: int = 0
    is_recording: bool = False


class Participant(BaseModel):
    """Event participant"""
    user_id: str
    joined_at: datetime
    is_active: bool = True


class EventMetadata(BaseModel):
    """Event metadata"""
    views: int = 0
    total_minutes: int = 0
    peak_participants: int = 0


class Event(BaseModel):
    """Event model"""
    id: Optional[str] = Field(alias="_id", default=None)
    title: str
    description: str
    category: str = Field(..., description="cultura, emergencia, entretenimiento")
    creator_id: str
    location: GeoLocation
    status: str = Field(default="active", description="active, ended, cancelled")
    room: RoomInfo = Field(default_factory=RoomInfo)
    participants: List[Participant] = Field(default_factory=list)
    collectibles_dropped: List[str] = Field(default_factory=list)
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    starts_at: datetime = Field(default_factory=datetime.now)
    ends_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class EventCreate(BaseModel):
    """Event creation model"""
    title: str
    description: str
    category: str
    creator_id: str
    coordinates: list[float] = Field(..., description="[longitude, latitude]")
    address: Optional[str] = None


class EventResponse(BaseModel):
    """Event response model"""
    id: str
    title: str
    description: str
    category: str
    creator_id: str
    location: GeoLocation
    status: str
    room: RoomInfo
    participants_count: int
    created_at: datetime
