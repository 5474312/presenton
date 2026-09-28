import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import httpx
import pytest
from openai import BadRequestError
from PIL import Image

from api.v1.ppt.endpoints.presentation import _apply_template_content_to_ui
from models.image_prompt import ImagePrompt
from models.sql.slide import SlideModel
from services.chat.memory_layer import PresentationChatMemoryLayer
from services.image_generation_service import (
    ImageGenerationService,
    _requested_image_size,
)
from utils.process_slides import (
    image_target_sizes_from_template,
    process_slide_and_fetch_assets,
)


def test_image_target_sizes_match_slots_with_identical_prompts():
    layout = {
        "components": [{
            "id": "hero",
            "elements": [
                {"type": "image", "name": "wide", "decorative": False,
                 "size": {"width": 400, "height": 200}},
                {"type": "image", "name": "tall", "decorative": False,
                 "size": {"width": 100, "height": 300}},
            ],
        }],
    }
    content = {"hero": {
        "wide": {"image_prompt": "same prompt"},
        "tall": {"image_prompt": "same prompt"},
    }}

    sizes = image_target_sizes_from_template(
        layout, content, _apply_template_content_to_ui
    )

    assert sizes[(('key', 'hero'), ('key', 'wide'))] == (400, 200)
    assert sizes[(('key', 'hero'), ('key', 'tall'))] == (100, 300)
    assert "image_url" not in content["hero"]["wide"]


def test_chat_hydration_matches_repeated_image_slots():
    layout = {"components": [{"id": "gallery", "elements": [{
        "type": "grid", "name": "photos", "children": [
            {"type": "image", "name": "photo", "decorative": False,
             "size": {"width": 300, "height": 150}}
        ],
    }]}]}
    content = {"gallery": {"photos": [
        {"image_prompt": "same"}, {"image_prompt": "same"},
    ]}}

    sizes = image_target_sizes_from_template(
        layout, content, PresentationChatMemoryLayer._apply_template_content_to_ui
    )

    assert sizes[(('key', 'gallery'), ('key', 'photos'), ('index', 0))] == (300, 150)
    assert sizes[(('key', 'gallery'), ('key', 'photos'), ('index', 1))] == (300, 150)


@pytest.mark.anyio
async def test_asset_generation_receives_target_size_and_missing_size_falls_back():
    service = AsyncMock()
    service.generate_image.side_effect = [
        "https://example.com/wide.png", "https://example.com/square.png"
    ]
    slide = SlideModel(
        presentation=uuid.uuid4(), layout_group="test", layout="test", index=0,
        content={"first": {"image_prompt": "wide"}, "second": {"image_prompt": "default"}},
    )
    sizes = {(('key', 'first'),): (400, 200)}

    await process_slide_and_fetch_assets(service, slide, image_target_sizes=sizes)

    requests = [call.args[0] for call in service.generate_image.await_args_list]
    assert [request.target_size for request in requests] == [(400, 200), None]


def test_provider_requests_template_size_and_square_fallback():
    assert _requested_image_size(None) == "1024x1024"
    assert _requested_image_size((500, 300)) == "500x300"
    assert _requested_image_size((1017.57, 997.22)) == "1018x997"
    assert ImagePrompt(prompt="default").target_size is None


@pytest.mark.anyio
async def test_service_passes_target_size_to_provider_and_keeps_default_call():
    service = object.__new__(ImageGenerationService)
    service.output_directory = "/tmp"
    service.is_image_generation_disabled = False
    service.is_stock_provider_selected = lambda: False
    service.image_gen_func = AsyncMock(return_value="https://example.com/generated.png")

    await service.generate_image(ImagePrompt(prompt="wide", target_width=400, target_height=200))
    assert service.image_gen_func.await_args.kwargs == {"target_size": (400, 200)}

    await service.generate_image(ImagePrompt(prompt="default"))
    assert service.image_gen_func.await_args.kwargs == {}


@pytest.mark.anyio
async def test_openai_provider_requests_template_size_and_square_fallback(tmp_path):
    service = ImageGenerationService(str(tmp_path))
    client = SimpleNamespace(images=SimpleNamespace(generate=AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(b"image").decode()
        )])
    )))
    with patch("services.image_generation_service.AsyncOpenAI", return_value=client):
        await service.generate_image_openai(
            "landscape", str(tmp_path), "dall-e-3", "standard", (1600, 900)
        )
        assert client.images.generate.await_args.kwargs["size"] == "1600x900"

        await service.generate_image_openai(
            "default", str(tmp_path), "dall-e-3", "standard"
        )
        assert client.images.generate.await_args.kwargs["size"] == "1024x1024"


@pytest.mark.anyio
async def test_openai_provider_retries_default_when_template_size_is_rejected(tmp_path):
    rejected_size = BadRequestError(
        "Unsupported image size",
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://example.com/images/generations")
        ),
        body=None,
    )
    result = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(b"image").decode())]
    )
    client = SimpleNamespace(
        images=SimpleNamespace(generate=AsyncMock(side_effect=[rejected_size, result]))
    )
    service = ImageGenerationService(str(tmp_path))

    with patch("services.image_generation_service.AsyncOpenAI", return_value=client):
        await service.generate_image_openai(
            "landscape", str(tmp_path), "dall-e-3", "standard", (400, 200)
        )

    sizes = [call.kwargs["size"] for call in client.images.generate.await_args_list]
    assert sizes == ["400x200", "1024x1024"]


@pytest.mark.anyio
async def test_generated_image_is_not_resized_after_provider_returns(tmp_path):
    image_path = tmp_path / "generated.png"
    Image.new("RGB", (1024, 1024), "red").save(image_path)
    service = object.__new__(ImageGenerationService)
    service.output_directory = str(tmp_path)
    service.is_image_generation_disabled = False
    service.is_stock_provider_selected = lambda: False
    service.image_gen_func = AsyncMock(return_value=str(image_path))

    await service.generate_image(
        ImagePrompt(prompt="banner", target_width=400, target_height=200)
    )

    with Image.open(image_path) as result:
        assert result.size == (1024, 1024)
