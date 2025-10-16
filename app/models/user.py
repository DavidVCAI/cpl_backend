from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


class GeoLocation(BaseModel):
    """GeoJSON Point for MongoDB geospatial queries"""
    type: str = "Point"
    coordinates: list[float] = Field(..., description="[longitude, latitude]")


class UserStats(BaseModel):
    """User statistics"""
    events_created: int = 0
    events_attended: int = 0
    collectibles_count: int = 0
    total_video_minutes: int = 0


class User(BaseModel):
    """User model - MVP simplified (phone + name only)"""
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    phone: str = Field(..., description="Phone number (unique identifier)")
    name: str = Field(..., description="User display name")
    stats: UserStats = Field(default_factory=UserStats)
    current_location: Optional[GeoLocation] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class UserCreate(BaseModel):
    """User registration model"""
    phone: str
    name: str


class UserResponse(BaseModel):
    """User response model"""
    id: str
    phone: str
    name: str
    stats: UserStats
    created_at: datetime
