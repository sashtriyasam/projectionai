# ADR-006: Event Bus for Cross-Layer Communication

## Status

Accepted

## Context

The application has multiple layers (UI, editor subsystems, core) that need to communicate without tight coupling. Direct method calls between layers create dependency cycles and make testing difficult. A publish-subscribe pattern was needed.

## Decision

Implement an in-process event bus with typed event classes and flexible listener registration.

- Events are lightweight dataclasses inheriting from a base `Event` type.
- The event bus (`EventBus`) provides `subscribe`, `unsubscribe`, and `emit` methods.
- Listeners are callables that accept the event type.
- Two independent buses exist: `CoreEventBus` for application-level events and `EditorEventBus` for viewport/editor events.

## Consequences

- **Positive**: Decoupled communication — senders don't need to know about receivers.
- **Positive**: Easy to add new event types without modifying existing code.
- **Positive**: Simplifies testing — components can be tested in isolation by simulating events.
- **Positive**: The typed event classes provide self-documenting event contracts.
- **Negative**: Data flow is less obvious than direct method calls — hard to trace "who handles this event?"
- **Negative**: Risk of event storms if listeners trigger additional events cyclically.
- **Negative**: No compile-time checking that event types are subscribed correctly.
