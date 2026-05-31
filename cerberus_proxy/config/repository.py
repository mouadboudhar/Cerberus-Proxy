from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cerberus_proxy.config.models import Endpoint


class EndpointRepository(ABC):
    @abstractmethod
    async def create(
        self,
        name: str,
        provider: str,
        upstream_url: str,
        default_model: str | None = None,
        kb_type: str | None = None,
        kb_url: str | None = None,
        kb_collection: str | None = None,
        kb_top_k: int = 4,
    ) -> Endpoint: ...

    @abstractmethod
    async def get_by_id(self, endpoint_id: int) -> Endpoint | None: ...

    @abstractmethod
    async def list_all(self) -> list[Endpoint]: ...

    @abstractmethod
    async def update(self, endpoint_id: int, **kwargs) -> Endpoint | None: ...

    @abstractmethod
    async def delete(self, endpoint_id: int) -> bool: ...


_UPDATABLE_FIELDS = {
    "name",
    "provider",
    "upstream_url",
    "default_model",
    "is_active",
    "kb_type",
    "kb_url",
    "kb_collection",
    "kb_top_k",
    "disabled_input_rules",
    "custom_blocked_phrases",
    "active_languages",
}


class SQLiteEndpointRepository(EndpointRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        name: str,
        provider: str,
        upstream_url: str,
        default_model: str | None = None,
        kb_type: str | None = None,
        kb_url: str | None = None,
        kb_collection: str | None = None,
        kb_top_k: int = 4,
    ) -> Endpoint:
        endpoint = Endpoint(
            name=name,
            provider=provider,
            upstream_url=upstream_url,
            default_model=default_model,
            kb_type=kb_type,
            kb_url=kb_url,
            kb_collection=kb_collection,
            kb_top_k=kb_top_k,
        )
        self._session.add(endpoint)
        await self._session.flush()
        await self._session.refresh(endpoint)
        return endpoint

    async def get_by_id(self, endpoint_id: int) -> Endpoint | None:
        return await self._session.get(Endpoint, endpoint_id)

    async def list_all(self) -> list[Endpoint]:
        result = await self._session.execute(select(Endpoint).order_by(Endpoint.id))
        return list(result.scalars().all())

    async def update(self, endpoint_id: int, **kwargs) -> Endpoint | None:
        endpoint = await self._session.get(Endpoint, endpoint_id)
        if endpoint is None:
            return None
        for field, value in kwargs.items():
            if field in _UPDATABLE_FIELDS:
                setattr(endpoint, field, value)
        await self._session.flush()
        await self._session.refresh(endpoint)
        return endpoint

    async def delete(self, endpoint_id: int) -> bool:
        endpoint = await self._session.get(Endpoint, endpoint_id)
        if endpoint is None:
            return False
        await self._session.delete(endpoint)
        await self._session.flush()
        return True
