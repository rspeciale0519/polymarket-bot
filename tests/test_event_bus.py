"""Tests for the event bus."""

import asyncio
from dataclasses import dataclass

import pytest

from engine.core.event_bus import EventBus


@dataclass
class SampleEvent:
    value: int


@dataclass
class OtherEvent:
    name: str


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = EventBus()
    received = []

    async def handler(event: SampleEvent):
        received.append(event.value)

    bus.subscribe(SampleEvent, handler)
    await bus.publish(SampleEvent(value=42))
    await bus.drain()

    assert received == [42]


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = EventBus()
    results_a = []
    results_b = []

    async def handler_a(event: SampleEvent):
        results_a.append(event.value)

    async def handler_b(event: SampleEvent):
        results_b.append(event.value * 2)

    bus.subscribe(SampleEvent, handler_a)
    bus.subscribe(SampleEvent, handler_b)
    await bus.publish(SampleEvent(value=10))
    await bus.drain()

    assert results_a == [10]
    assert results_b == [20]


@pytest.mark.asyncio
async def test_no_crosstalk():
    bus = EventBus()
    test_received = []
    other_received = []

    async def test_handler(event: SampleEvent):
        test_received.append(event.value)

    async def other_handler(event: OtherEvent):
        other_received.append(event.name)

    bus.subscribe(SampleEvent, test_handler)
    bus.subscribe(OtherEvent, other_handler)

    await bus.publish(SampleEvent(value=1))
    await bus.publish(OtherEvent(name="hello"))
    await bus.drain()

    assert test_received == [1]
    assert other_received == ["hello"]


@pytest.mark.asyncio
async def test_publish_with_no_subscribers():
    bus = EventBus()
    await bus.publish(SampleEvent(value=99))
    await bus.drain()
    # Should not raise


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    received = []

    async def handler(event: SampleEvent):
        received.append(event.value)

    bus.subscribe(SampleEvent, handler)
    await bus.publish(SampleEvent(value=1))
    await bus.drain()

    bus.unsubscribe(SampleEvent, handler)
    await bus.publish(SampleEvent(value=2))
    await bus.drain()

    assert received == [1]


@pytest.mark.asyncio
async def test_error_in_callback_does_not_crash():
    bus = EventBus()
    received = []

    async def bad_handler(event: SampleEvent):
        raise ValueError("intentional error")

    async def good_handler(event: SampleEvent):
        received.append(event.value)

    bus.subscribe(SampleEvent, bad_handler)
    bus.subscribe(SampleEvent, good_handler)

    await bus.publish(SampleEvent(value=5))
    await bus.drain()

    assert received == [5]


@pytest.mark.asyncio
async def test_subscriber_count():
    bus = EventBus()

    async def h1(e): pass
    async def h2(e): pass

    assert bus.subscriber_count == 0
    bus.subscribe(SampleEvent, h1)
    assert bus.subscriber_count == 1
    bus.subscribe(OtherEvent, h2)
    assert bus.subscriber_count == 2
