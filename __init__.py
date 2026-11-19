# Copyright 2026 Michael Beckh (mbeckh)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Helper for monkey patching the same function from different plugins."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import inspect
import operator
import threading
from typing import (
    TYPE_CHECKING,
    cast,
)

from packaging.version import Version

from picard.plugin3.api import PluginApi


if TYPE_CHECKING:  # import interface for type checking only
    from collections.abc import Callable
    from types import ModuleType

    from .monkey import (
        C,
        ClassMethodPatchWrapper,
        P,
        PatchWrapper,
        R,
        patch,
        patch_classmethod,
        unpatch,
        unpatch_module,
    )

__all__ = [
    'API_VERSION',
    'patch',
    'patch_classmethod',
    'unpatch',
    'unpatch_module',
]

API_VERSION = Version('1.0.0')
"""Compatible API version for this implementation."""


@dataclass
class _DispatcherDetails:
    chain: Callable
    original: Callable
    wrappers: list[tuple[int, PatchWrapper]]


_lock = threading.Lock()


def _get_registry() -> dict[tuple[ModuleType | type, str] | tuple[type, str, str], _DispatcherDetails]:
    """Store registry in some (random) class in Picard so it survices plugin reloads.

    Returns:
        The dispatcher registry.
    """
    attr_name = '_mbmp_registry'
    with _lock:
        registry = getattr(PluginApi, attr_name, None)
        if not registry:
            registry = {}
            setattr(PluginApi, attr_name, registry)
    return registry


#
# Apply patches
#


def _find_attr_name(
    target: ModuleType | type, wrapped: Callable[P, R] | property | staticmethod[P, R] | classmethod[C, P, R]
) -> str:
    """Get name of function in target object.

    Args:
        target: The module or type to patch.
        wrapped: The function or property to patch.

    Returns:
        Name of attribute under which wrapped is stored in target.

    Raises:
        AttributeError: If wrapped is not found in target.
    """
    # Unwrap bound @classmethod if applicable (bound methods have __func__ and __self__)
    target_func = getattr(wrapped, "__func__", wrapped)

    for name in dir(target):
        raw_attr = inspect.getattr_static(target, name, None)
        # Unwrap raw @classmethod or @staticmethod descriptors stored on the class
        raw_func = getattr(raw_attr, "__func__", raw_attr)

        if raw_func is target_func:
            return name

    raise AttributeError(f"Could not find {wrapped!r} on {target!r}")


def _rebuild_chain(details: _DispatcherDetails) -> None:
    """Rebuild wrapper chain."""
    chain = details.original
    for _, fn in details.wrappers:
        chain = functools.partial(fn, chain)
    details.chain = chain


def _apply_patch(
    target: ModuleType | type,
    wrapped: Callable[P, R] | property | staticmethod[P, R],
    wrapper: PatchWrapper,
    priority: int,
    property_type: str,
) -> PatchWrapper:
    """Apply the patch.

    Adds the wrapper to the dispatcher, installing the latter if not yet present.

    Args:
        target: The module or class to patch.
        wrapped: The function or property to patch.
        wrapper: The function called instead of wrapped.
        priority: Wrapper execution order from highest on the outside to lowest on the inside.
        property_type: Property accessor (fget, fset or fdel).

    Returns:
        The wrapper function.

    Raises:
        AttributeError: If wrapped is not found in target.
    """
    name = _find_attr_name(target, wrapped)

    is_property = isinstance(wrapped, property)
    if is_property:
        wrapped_func = getattr(wrapped, property_type)
        if wrapped_func is None:
            raise AttributeError(f"Property '{name}' has no {property_type} defined.")
    else:
        # use __func__ if available
        wrapped_func = getattr(wrapped, '__func__', wrapped)

    key = (cast('type', target), name, property_type) if is_property else (target, name)
    registry = _get_registry()
    with _lock:
        details = registry.get(key)
        if details:
            # remove wrapper if it already exists (might happen on reloads)
            details.wrappers = [*(pw for pw in details.wrappers if pw[1] is not wrapper), (priority, wrapper)]
            details.wrappers.sort(key=operator.itemgetter(0))

            _rebuild_chain(details)
        else:
            # create and install dispatcher
            details = _DispatcherDetails(
                chain=functools.partial(wrapper, wrapped_func),
                original=wrapped_func,
                wrappers=[(priority, wrapper)],
            )
            registry[key] = details

            dispatcher = cast(
                'Callable',
                # it is NOT possible to inline the following lambda because
                # details.chain can change at runtime and MUST NOT be bound
                # before the actual call
                functools.update_wrapper(lambda *args, **kwargs: details.chain(*args, **kwargs), wrapped_func),  # ruff: ignore[unnecessary-lambda]
            )

            if is_property:
                prop = {
                    'fget': wrapped.fget,
                    'fset': wrapped.fset,
                    'fdel': wrapped.fdel,
                    'doc': wrapped.__doc__,
                }
                prop[property_type] = dispatcher
                setattr(target, name, property(**prop))
            elif isinstance(wrapped, classmethod) or isinstance(getattr(wrapped, '__self__', None), type):
                setattr(target, name, classmethod(dispatcher))
            elif isinstance(inspect.getattr_static(target, name), staticmethod):
                setattr(target, name, staticmethod(dispatcher))
            else:
                setattr(target, name, dispatcher)

    return wrapper


def patch(
    target: ModuleType | type[C],
    wrapped: Callable[P, R] | property | staticmethod[P, R],
    priority: int = 0,
    property_type: str = 'fget',
) -> Callable[[PatchWrapper[P, R]], PatchWrapper[P, R]]:
    """Install a wrapper around a function.

    Args:
        target: The module or type to patch.
        wrapped: The function or property to patch.
        priority: Wrapper execution order from highest on the outside to lowest on the inside.
        property_type: Property accessor to patch (fget, fset or fdel).

    Returns:
        The wrapper function.

    Raises:
        AttributeError: If the target function cannot be found.
    """
    return lambda wrapper: _apply_patch(target, wrapped, wrapper, priority, property_type)


def patch_classmethod(
    target: type[C], wrapped: Callable[P, R], priority: int = 0, property_type: str = 'fget'
) -> Callable[[ClassMethodPatchWrapper[C, P, R]], ClassMethodPatchWrapper[C, P, R]]:
    """Install a wrapper around a class method.

    Same as patch, but class methods require special handling to account for the class parameter.

    Args:
        target: The module or type to patch.
        wrapped: The function or property to patch.
        priority: Wrapper execution order from highest on the outside to lowest on the inside.
        property_type: Property accessor to patch (fget, fset or fdel).

    Returns:
        The wrapper function.

    Raises:
        AttributeError: If the target function cannot be found.
    """
    return lambda wrapper: _apply_patch(target, wrapped, wrapper, priority, property_type)


def unpatch(
    target: ModuleType | type[C],
    wrapped: Callable[P, R] | property | staticmethod[P, R],
    wrapper: PatchWrapper[P, R] | ClassMethodPatchWrapper[C, P, R],
    property_type: str = 'fget',
) -> bool:
    """Remove a previously installed wrapper.

    Args:
        target: The module or type to unpatch.
        wrapped: The patched function, method or property.
        wrapper: The wrapper function to remove.
        property_type: Property accessor (fget, fset or fdel).

    Returns:
        True if the wrapper was found and removed.
    """
    name = _find_attr_name(target, wrapped)

    is_property = isinstance(wrapped, property)
    key = (cast('type', target), name, property_type) if is_property else (target, name)

    registry = _get_registry()
    with _lock:
        details = registry.get(key)
        if details is None:
            return False

        old_count = len(details.wrappers)
        details.wrappers = [(priority, fn) for priority, fn in details.wrappers if fn is not wrapper]
        if len(details.wrappers) == old_count:
            return False

        _rebuild_chain(details)
    return True


def unpatch_module(module: str) -> None:
    """Remove all patches for functions from a module.

    Args:
        module: The name of the module container the wrapper functions.
    """
    registry = _get_registry()
    with _lock:
        for details in registry.values():
            old_count = len(details.wrappers)
            details.wrappers = [(priority, fn) for priority, fn in details.wrappers if fn.__module__ != module]
            if len(details.wrappers) == old_count:
                return

            _rebuild_chain(details)


def enable(api: PluginApi) -> None:
    """Enable plugin."""


def disable() -> None:
    """Disable plugin."""
