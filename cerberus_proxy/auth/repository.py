import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cerberus_proxy.auth.models import ApiKey

logger = logging.getLogger("cerberus_proxy.auth")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KeyRepository(ABC):
    @abstractmethod
    async def create(
        self, name: str, key_hash: str, endpoint_id: int | None = None
    ) -> ApiKey: ...

    @abstractmethod
    async def get_by_hash(self, key_hash: str) -> ApiKey | None: ...

    @abstractmethod
    async def get_by_id(self, key_id: int) -> ApiKey | None: ...

    @abstractmethod
    async def update_limits(
        self,
        key_id: int,
        rpm: int | None = None,
        rph: int | None = None,
        rpd: int | None = None,
    ) -> ApiKey | None: ...

    @abstractmethod
    async def list_all(self) -> list[ApiKey]: ...

    @abstractmethod
    async def revoke(self, key_id: int) -> bool: ...

    @abstractmethod
    async def revoke_by_endpoint(self, endpoint_id: int) -> int: ...

    @abstractmethod
    async def update_last_used(self, key_id: int) -> None: ...


class SQLiteKeyRepository(KeyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, name: str, key_hash: str, endpoint_id: int | None = None
    ) -> ApiKey:
        key = ApiKey(name=name, key_hash=key_hash, endpoint_id=endpoint_id)
        self._session.add(key)
        await self._session.flush()
        await self._session.refresh(key)
        return key

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        key = result.scalar_one_or_none()
        if key is None or key.revoked_at is not None:
            return None
        return key

    async def get_by_id(self, key_id: int) -> ApiKey | None:
        return await self._session.get(ApiKey, key_id)

    async def update_limits(
        self,
        key_id: int,
        rpm: int | None = None,
        rph: int | None = None,
        rpd: int | None = None,
    ) -> ApiKey | None:
        # Only fields explicitly provided (non-None) are changed; pass None to
        # leave a window's limit untouched.
        key = await self._session.get(ApiKey, key_id)
        if key is None:
            return None
        if rpm is not None:
            key.rate_limit_rpm = rpm
        if rph is not None:
            key.rate_limit_rph = rph
        if rpd is not None:
            key.rate_limit_rpd = rpd
        await self._session.flush()
        await self._session.refresh(key)
        return key

    async def list_all(self) -> list[ApiKey]:
        result = await self._session.execute(select(ApiKey).order_by(ApiKey.id))
        return list(result.scalars().all())

    async def revoke(self, key_id: int) -> bool:
        key = await self._session.get(ApiKey, key_id)
        if key is None or key.revoked_at is not None:
            return False
        key.revoked_at = _utcnow()
        await self._session.flush()
        return True

    async def revoke_by_endpoint(self, endpoint_id: int) -> int:
        result = await self._session.execute(
            select(ApiKey).where(
                ApiKey.endpoint_id == endpoint_id, ApiKey.revoked_at.is_(None)
            )
        )
        keys = list(result.scalars().all())
        now = _utcnow()
        for key in keys:
            key.revoked_at = now
        await self._session.flush()
        return len(keys)

    async def update_last_used(self, key_id: int) -> None:
        # Fire-and-forget: never let last-used bookkeeping break a request.
        try:
            await self._session.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=_utcnow())
            )
            await self._session.flush()
        except Exception:  # noqa: BLE001
            logger.debug("Failed to update last_used_at for key %s", key_id, exc_info=True)
