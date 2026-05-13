import pytest


@pytest.fixture(autouse=True)
def _disable_plan_image_generation(monkeypatch):
    async def noop_generate_room_images(*args, **kwargs):
        if False:
            yield b""

    monkeypatch.setattr("chat.routes.plans.generate_room_images", noop_generate_room_images, raising=False)
