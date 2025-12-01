"""
Rate Limiting Middleware for Brute Force Protection

Security Scenario 3: Rate Limiting against Brute Force
- Max 5 failed login attempts per minute per IP
- Block IP for 15 minutes after exceeding limit
- Log all security incidents
- Target: 100% block rate, < 10ms latency
"""

import time
import asyncio
from typing import Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

import logging
logger = logging.getLogger(__name__)


@dataclass
class IPRecord:
    """Track failed attempts and blocks for an IP address"""
    failed_attempts: int = 0
    first_attempt_time: float = 0
    blocked_until: float = 0
    total_blocks: int = 0  # Track total blocks for this IP


class RateLimiter:
    """
    In-memory rate limiter with IP-based tracking.

    For production, consider using Redis for distributed rate limiting
    across multiple backend instances behind load balancer.

    Configuration:
    - MAX_ATTEMPTS: Maximum failed attempts in the time window (default: 5)
    - TIME_WINDOW: Time window in seconds (default: 60 seconds = 1 minute)
    - BLOCK_DURATION: How long to block after exceeding limit (default: 900 seconds = 15 minutes)
    """

    def __init__(
        self,
        max_attempts: int = None,
        time_window: int = 60,
        block_duration: int = None
    ):
        self.max_attempts = max_attempts or settings.RATE_LIMIT_MAX_ATTEMPTS
        self.time_window = time_window
        self.block_duration = block_duration or settings.RATE_LIMIT_BLOCK_DURATION
        self._records: Dict[str, IPRecord] = defaultdict(IPRecord)
        self._lock = asyncio.Lock()

    async def is_blocked(self, ip: str) -> Tuple[bool, Optional[int]]:
        """
        Check if an IP is currently blocked.

        Returns:
            Tuple of (is_blocked, seconds_remaining)
        """
        start_time = time.time()

        async with self._lock:
            record = self._records.get(ip)
            if not record:
                return False, None

            current_time = time.time()

            # Check if currently blocked
            if record.blocked_until > current_time:
                remaining = int(record.blocked_until - current_time)
                latency = (time.time() - start_time) * 1000
                if latency > 10:
                    logger.warning(f"Rate limit check exceeded 10ms target: {latency:.2f}ms")
                return True, remaining

            # Not blocked, but check if we should reset the counter
            if current_time - record.first_attempt_time > self.time_window:
                record.failed_attempts = 0
                record.first_attempt_time = 0

        latency = (time.time() - start_time) * 1000
        if latency > 10:
            logger.warning(f"Rate limit check exceeded 10ms target: {latency:.2f}ms")

        return False, None

    async def record_failed_attempt(self, ip: str) -> Tuple[bool, Optional[int]]:
        """
        Record a failed login attempt for an IP.

        Returns:
            Tuple of (now_blocked, block_duration_seconds)
        """
        start_time = time.time()

        async with self._lock:
            record = self._records[ip]
            current_time = time.time()

            # Reset counter if time window has passed
            if current_time - record.first_attempt_time > self.time_window:
                record.failed_attempts = 0
                record.first_attempt_time = current_time

            # First attempt in window
            if record.first_attempt_time == 0:
                record.first_attempt_time = current_time

            # Increment failed attempts
            record.failed_attempts += 1

            logger.info(
                f"Failed login attempt {record.failed_attempts}/{self.max_attempts} "
                f"from IP: {ip}"
            )

            # Check if we should block
            if record.failed_attempts >= self.max_attempts:
                record.blocked_until = current_time + self.block_duration
                record.total_blocks += 1

                # Log security incident
                self._log_security_incident(ip, record)

                latency = (time.time() - start_time) * 1000
                logger.info(f"Rate limit block applied in {latency:.2f}ms")

                return True, self.block_duration

        return False, None

    async def record_successful_attempt(self, ip: str):
        """
        Record a successful login - resets the failed attempt counter.
        """
        async with self._lock:
            if ip in self._records:
                record = self._records[ip]
                record.failed_attempts = 0
                record.first_attempt_time = 0
                # Note: We keep blocked_until intact if currently blocked

    async def unblock_ip(self, ip: str):
        """Manually unblock an IP (admin function)"""
        async with self._lock:
            if ip in self._records:
                self._records[ip].blocked_until = 0
                self._records[ip].failed_attempts = 0
                logger.info(f"IP {ip} manually unblocked")

    async def get_ip_status(self, ip: str) -> dict:
        """Get current status for an IP (for monitoring/admin)"""
        async with self._lock:
            record = self._records.get(ip)
            if not record:
                return {"ip": ip, "status": "clean", "failed_attempts": 0}

            current_time = time.time()
            is_blocked = record.blocked_until > current_time

            return {
                "ip": ip,
                "status": "blocked" if is_blocked else "monitored",
                "failed_attempts": record.failed_attempts,
                "blocked_until": datetime.fromtimestamp(record.blocked_until).isoformat() if is_blocked else None,
                "remaining_seconds": int(record.blocked_until - current_time) if is_blocked else 0,
                "total_blocks": record.total_blocks
            }

    async def cleanup_old_records(self):
        """Remove old records to prevent memory bloat"""
        async with self._lock:
            current_time = time.time()
            cleanup_threshold = current_time - (self.block_duration * 2)

            ips_to_remove = []
            for ip, record in self._records.items():
                # Remove if not blocked and no recent activity
                if (record.blocked_until < current_time and
                    record.first_attempt_time < cleanup_threshold):
                    ips_to_remove.append(ip)

            for ip in ips_to_remove:
                del self._records[ip]

            if ips_to_remove:
                logger.info(f"Cleaned up {len(ips_to_remove)} old rate limit records")

    def _log_security_incident(self, ip: str, record: IPRecord):
        """Log security incident for audit trail"""
        incident = {
            "type": "RATE_LIMIT_BLOCK",
            "ip": ip,
            "timestamp": datetime.utcnow().isoformat(),
            "failed_attempts": record.failed_attempts,
            "block_duration_minutes": self.block_duration // 60,
            "total_blocks_for_ip": record.total_blocks
        }

        # Log as warning for monitoring systems to pick up
        logger.warning(
            f"SECURITY INCIDENT: IP {ip} blocked after {record.failed_attempts} "
            f"failed attempts. Block duration: {self.block_duration // 60} minutes. "
            f"Total blocks for this IP: {record.total_blocks}"
        )

        # In production, you might want to:
        # - Send to SIEM system
        # - Store in database for audit
        # - Trigger alerts if total_blocks is high


# Global rate limiter instance
rate_limiter = RateLimiter()


async def rate_limit_check(request: Request) -> bool:
    """
    FastAPI dependency for rate limit checking.

    Usage:
        @router.post("/login")
        async def login(request: Request, _: bool = Depends(rate_limit_check)):
            # Only reaches here if not blocked
            ...

    Returns True if allowed, raises HTTPException if blocked.
    """
    # Get client IP (handle proxy headers)
    ip = get_client_ip(request)

    is_blocked, remaining = await rate_limiter.is_blocked(ip)

    if is_blocked:
        logger.warning(f"Blocked request from IP {ip}, {remaining}s remaining")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Too many failed login attempts",
                "blocked_for_seconds": remaining,
                "message": f"IP blocked for {remaining // 60} minutes and {remaining % 60} seconds"
            },
            headers={
                "Retry-After": str(remaining),
                "X-RateLimit-Blocked": "true"
            }
        )

    return True


def get_client_ip(request: Request) -> str:
    """
    Extract client IP from request, handling proxy headers.

    Checks in order:
    1. X-Forwarded-For header (from load balancer/proxy)
    2. X-Real-IP header
    3. Direct client host
    """
    # Check X-Forwarded-For (common for load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct client
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to apply rate limiting to specific endpoints.

    This middleware can be configured to only apply to certain paths.
    """

    def __init__(
        self,
        app,
        protected_paths: list = None,
        limiter: RateLimiter = None
    ):
        super().__init__(app)
        self.protected_paths = protected_paths or ["/api/users/login", "/api/auth/login"]
        self.limiter = limiter or rate_limiter

    async def dispatch(self, request: Request, call_next):
        # Check if this path needs rate limiting
        if not any(request.url.path.startswith(path) for path in self.protected_paths):
            return await call_next(request)

        ip = get_client_ip(request)

        # Check if blocked
        is_blocked, remaining = await self.limiter.is_blocked(ip)
        if is_blocked:
            from starlette.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many failed login attempts",
                    "blocked_for_seconds": remaining,
                    "message": f"IP blocked for {remaining // 60} minutes and {remaining % 60} seconds"
                },
                headers={
                    "Retry-After": str(remaining),
                    "X-RateLimit-Blocked": "true"
                }
            )

        return await call_next(request)
