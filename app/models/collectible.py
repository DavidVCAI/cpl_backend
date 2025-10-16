from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from bson import ObjectId


class GeoLocation(BaseModel):
    """GeoJSON Point"""
    type: str = "Point"
    coordinates: list[float]


class CollectibleMetadata(BaseModel):
    """Collectible metadata for race conditions"""
    total_available: int = 1
    claim_attempts: int = 0
    successful_claims: int = 0


class Collectible(BaseModel):
    """Collectible model"""
    id: Optional[str] = Field(alias="_id", default=None)
    name: str
    type: str = Field(..., description="common, rare, epic, legendary")
    rarity_score: int = Field(..., ge=1, le=100)
    image_url: Optional[str] = None
    description: str
    event_id: str
    dropped_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    drop_location: GeoLocation
    metadata: CollectibleMetadata = Field(default_factory=CollectibleMetadata)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class UserCollectible(BaseModel):
    """User collectible inventory"""
    id: Optional[str] = Field(alias="_id", default=None)
    user_id: str
    collectible_id: str
    claimed_at: datetime = Field(default_factory=datetime.now)
    claim_order: int = Field(..., description="Position in claim race (1st, 2nd, etc)")
    event_id: str

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
