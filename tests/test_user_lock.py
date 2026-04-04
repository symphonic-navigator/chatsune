import asyncio


async def test_get_user_lock_returns_same_instance():
    from backend.jobs import get_user_lock

    lock_a = get_user_lock("user-1")
    lock_b = get_user_lock("user-1")
    assert lock_a is lock_b


async def test_get_user_lock_returns_different_for_different_users():
    from backend.jobs import get_user_lock

    lock_a = get_user_lock("user-1")
    lock_b = get_user_lock("user-2")
    assert lock_a is not lock_b


async def test_lock_serialises_access():
    from backend.jobs import get_user_lock

    lock = get_user_lock("user-serial")
    order = []

    async def task(name: str, delay: float):
        async with lock:
            order.append(f"{name}_start")
            await asyncio.sleep(delay)
            order.append(f"{name}_end")

    t1 = asyncio.create_task(task("a", 0.05))
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(task("b", 0.01))
    await asyncio.gather(t1, t2)

    assert order.index("a_end") < order.index("b_start")
