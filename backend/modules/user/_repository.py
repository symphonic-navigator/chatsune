from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.auth import UserDto


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["users"]

    async def create_indexes(self) -> None:
        await self._collection.create_index("username", unique=True)
        await self._collection.create_index("email", unique=True)
        await self._collection.create_index(
            "role",
            unique=True,
            partialFilterExpression={"role": "master_admin"},
        )

    async def find_by_username(self, username: str) -> dict | None:
        return await self._collection.find_one({"username": username})

    async def find_by_id(self, user_id: str) -> dict | None:
        return await self._collection.find_one({"_id": user_id})

    async def find_by_role(self, role: str) -> dict | None:
        return await self._collection.find_one({"role": role})

    async def create(
        self,
        username: str,
        email: str,
        display_name: str,
        password_hash: str,
        role: str,
        must_change_password: bool = False,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "username": username,
            "email": email,
            "display_name": display_name,
            "password_hash": password_hash,
            "role": role,
            "is_active": True,
            "must_change_password": must_change_password,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def update(self, user_id: str, fields: dict) -> dict | None:
        fields["updated_at"] = datetime.now(UTC)
        await self._collection.update_one(
            {"_id": user_id}, {"$set": fields}
        )
        return await self.find_by_id(user_id)

    async def list_users(
        self, skip: int = 0, limit: int = 50
    ) -> list[dict]:
        cursor = self._collection.find().sort("created_at", 1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count(self) -> int:
        return await self._collection.count_documents({})

    async def update_about_me(self, user_id: str, about_me: str | None) -> dict | None:
        fields = {"about_me": about_me, "updated_at": datetime.now(UTC)}
        await self._collection.update_one({"_id": user_id}, {"$set": fields})
        return await self.find_by_id(user_id)

    async def get_about_me(self, user_id: str) -> str | None:
        doc = await self.find_by_id(user_id)
        if doc is None:
            return None
        return doc.get("about_me")

    async def get_mcp_gateways(self, user_id: str) -> list[dict]:
        """Return the user's remote MCP gateway configurations."""
        doc = await self._collection.find_one({"_id": user_id}, {"mcp_gateways": 1})
        if not doc:
            return []
        return doc.get("mcp_gateways", [])

    async def add_mcp_gateway(self, user_id: str, gateway: dict) -> None:
        """Append a gateway to the user's MCP gateway list."""
        await self._collection.update_one(
            {"_id": user_id},
            {
                "$push": {"mcp_gateways": gateway},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )

    async def update_mcp_gateway(self, user_id: str, gateway_id: str, updates: dict) -> bool:
        """Update a specific gateway by ID. Returns True if found and updated."""
        result = await self._collection.update_one(
            {"_id": user_id, "mcp_gateways.id": gateway_id},
            {
                "$set": {
                    **{f"mcp_gateways.$.{k}": v for k, v in updates.items()},
                    "updated_at": datetime.now(UTC),
                },
            },
        )
        return result.modified_count > 0

    async def delete_mcp_gateway(self, user_id: str, gateway_id: str) -> bool:
        """Remove a gateway by ID. Returns True if found and removed."""
        result = await self._collection.update_one(
            {"_id": user_id},
            {
                "$pull": {"mcp_gateways": {"id": gateway_id}},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )
        return result.modified_count > 0

    @staticmethod
    def to_dto(doc: dict) -> UserDto:
        return UserDto(
            id=doc["_id"],
            username=doc["username"],
            email=doc["email"],
            display_name=doc["display_name"],
            role=doc["role"],
            is_active=doc["is_active"],
            must_change_password=doc["must_change_password"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
