"""
Room Authorization Middleware

Security Scenario 2: Authorization for Video Room Access
- Verifies user is authenticated (JWT valid)
- Checks user is authorized to join specific room (ACL/roles)
- Rejects unauthorized access with 403
- Target: 100% requests validated, decision < 150ms
"""

import time
from typing import Optional, List
from enum import Enum
from datetime import datetime

from fastapi import HTTPException, status, Depends
from bson import ObjectId

from app.middleware.auth import CognitoUser, get_current_user
from app.database import get_database

import logging
logger = logging.getLogger(__name__)


class RoomRole(str, Enum):
    """User roles within a room/event"""
    CREATOR = "creator"      # Event creator - full control
    MODERATOR = "moderator"  # Can manage participants, mute, etc.
    PARTICIPANT = "participant"  # Regular participant
    VIEWER = "viewer"        # View-only access (future)
    BANNED = "banned"        # Explicitly banned from room


class RoomPermission(str, Enum):
    """Permissions for room actions"""
    JOIN = "join"
    SPEAK = "speak"
    SHARE_SCREEN = "share_screen"
    MODERATE = "moderate"
    END_EVENT = "end_event"
    DROP_COLLECTIBLES = "drop_collectibles"


# Permission matrix: role -> list of permissions
ROLE_PERMISSIONS = {
    RoomRole.CREATOR: [
        RoomPermission.JOIN,
        RoomPermission.SPEAK,
        RoomPermission.SHARE_SCREEN,
        RoomPermission.MODERATE,
        RoomPermission.END_EVENT,
        RoomPermission.DROP_COLLECTIBLES,
    ],
    RoomRole.MODERATOR: [
        RoomPermission.JOIN,
        RoomPermission.SPEAK,
        RoomPermission.SHARE_SCREEN,
        RoomPermission.MODERATE,
    ],
    RoomRole.PARTICIPANT: [
        RoomPermission.JOIN,
        RoomPermission.SPEAK,
        RoomPermission.SHARE_SCREEN,
    ],
    RoomRole.VIEWER: [
        RoomPermission.JOIN,
    ],
    RoomRole.BANNED: [],  # No permissions
}


async def get_user_room_role(
    user_id: str,
    event_id: str,
    db=None
) -> Optional[RoomRole]:
    """
    Get user's role in a specific event/room.

    Checks:
    1. If user is the creator -> CREATOR role
    2. If user is in moderators list -> MODERATOR role
    3. If user is banned -> BANNED role
    4. If event is public -> PARTICIPANT role (anyone can join)
    5. If event is private -> check invitation list

    Returns None if user has no access.
    """
    start_time = time.time()

    if db is None:
        db = await get_database()

    try:
        event = await db.events.find_one({"_id": ObjectId(event_id)})

        if not event:
            logger.warning(f"Event {event_id} not found for authorization check")
            return None

        # Check if user is creator
        if str(event.get("creator_id")) == user_id:
            role = RoomRole.CREATOR
            _log_authorization_time(start_time, user_id, event_id, role)
            return role

        # Check if user is banned
        banned_users = event.get("banned_users", [])
        if user_id in banned_users:
            logger.warning(f"Banned user {user_id} attempted to access event {event_id}")
            role = RoomRole.BANNED
            _log_authorization_time(start_time, user_id, event_id, role)
            return role

        # Check if user is moderator
        moderators = event.get("moderators", [])
        if user_id in moderators:
            role = RoomRole.MODERATOR
            _log_authorization_time(start_time, user_id, event_id, role)
            return role

        # Check event access type
        is_private = event.get("is_private", False)

        if is_private:
            # Check invitation list for private events
            invited_users = event.get("invited_users", [])
            if user_id in invited_users:
                role = RoomRole.PARTICIPANT
                _log_authorization_time(start_time, user_id, event_id, role)
                return role
            # Not invited to private event
            return None
        else:
            # Public event - anyone can join as participant
            role = RoomRole.PARTICIPANT
            _log_authorization_time(start_time, user_id, event_id, role)
            return role

    except Exception as e:
        logger.error(f"Error checking room authorization: {e}")
        return None


def _log_authorization_time(start_time: float, user_id: str, event_id: str, role: RoomRole):
    """Log authorization decision time"""
    decision_time = (time.time() - start_time) * 1000
    logger.debug(f"Room auth decision for user {user_id} on event {event_id}: {role.value} ({decision_time:.2f}ms)")

    if decision_time > 150:
        logger.warning(
            f"Room authorization exceeded 150ms target: {decision_time:.2f}ms "
            f"(user={user_id}, event={event_id})"
        )


async def check_room_permission(
    user_id: str,
    event_id: str,
    permission: RoomPermission,
    db=None
) -> bool:
    """
    Check if user has specific permission in a room.

    Returns True if permitted, False otherwise.
    """
    role = await get_user_room_role(user_id, event_id, db)

    if role is None:
        return False

    allowed_permissions = ROLE_PERMISSIONS.get(role, [])
    return permission in allowed_permissions


async def authorize_room_join(
    event_id: str,
    user: CognitoUser = Depends(get_current_user)
) -> CognitoUser:
    """
    FastAPI dependency to authorize room join.

    Usage:
        @router.post("/events/{event_id}/join")
        async def join_event(
            event_id: str,
            user: CognitoUser = Depends(authorize_room_join)
        ):
            # User is authorized to join
            ...

    Raises 403 if not authorized.
    """
    start_time = time.time()

    db = await get_database()
    role = await get_user_room_role(user.user_id, event_id, db)

    if role is None:
        decision_time = (time.time() - start_time) * 1000
        logger.warning(
            f"Unauthorized room access attempt: user={user.user_id}, "
            f"event={event_id}, decision_time={decision_time:.2f}ms"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to join this room"
        )

    if role == RoomRole.BANNED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have been banned from this event"
        )

    if RoomPermission.JOIN not in ROLE_PERMISSIONS.get(role, []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not permit joining this room"
        )

    decision_time = (time.time() - start_time) * 1000
    logger.info(
        f"Room access authorized: user={user.user_id}, event={event_id}, "
        f"role={role.value}, decision_time={decision_time:.2f}ms"
    )

    return user


async def authorize_room_action(
    event_id: str,
    permission: RoomPermission,
    user: CognitoUser
) -> bool:
    """
    Check if user can perform specific action in room.

    Usage:
        async def end_event(event_id: str, user: CognitoUser):
            if not await authorize_room_action(event_id, RoomPermission.END_EVENT, user):
                raise HTTPException(403, "Not authorized to end this event")
            ...
    """
    return await check_room_permission(user.user_id, event_id, permission)


class RoomAuthorizationResult:
    """Result of room authorization check"""

    def __init__(
        self,
        authorized: bool,
        role: Optional[RoomRole] = None,
        permissions: List[RoomPermission] = None,
        reason: str = None
    ):
        self.authorized = authorized
        self.role = role
        self.permissions = permissions or []
        self.reason = reason


async def full_room_authorization(
    user_id: str,
    event_id: str
) -> RoomAuthorizationResult:
    """
    Perform full authorization check and return detailed result.

    Useful for getting complete authorization info in one call.
    """
    start_time = time.time()

    db = await get_database()
    role = await get_user_room_role(user_id, event_id, db)

    if role is None:
        return RoomAuthorizationResult(
            authorized=False,
            reason="User has no access to this event"
        )

    if role == RoomRole.BANNED:
        return RoomAuthorizationResult(
            authorized=False,
            role=role,
            permissions=[],
            reason="User is banned from this event"
        )

    permissions = ROLE_PERMISSIONS.get(role, [])

    decision_time = (time.time() - start_time) * 1000
    if decision_time > 150:
        logger.warning(f"Full room authorization exceeded 150ms: {decision_time:.2f}ms")

    return RoomAuthorizationResult(
        authorized=True,
        role=role,
        permissions=permissions
    )
