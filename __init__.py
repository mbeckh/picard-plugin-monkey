# Helper for monkey patching the same function from different plugins.
#
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

from collections.abc import Callable
from dataclasses import dataclass
import functools
import inspect
import threading
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    cast,
)

from picard.plugin3.api import PluginApi


if TYPE_CHECKING:  # import interface for type checking only
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
    'patch',
    'patch_classmethod',
    'unpatch',
    'unpatch_module',
]


@dataclass
class _DispatcherDetails:
    chain: Callable
    original: Callable
    wrappers: list[tuple[int, PatchWrapper]]


_lock = threading.Lock()
_registry: dict[tuple[ModuleType | type, str] | tuple[type, str, str], _DispatcherDetails] = {}

#
# Apply patches
#


def _find_attr_name(
    target: ModuleType | type, wrapped: Callable[P, R] | property | staticmethod[P, R] | classmethod[C, P, R]
) -> str:
    """Get name of function in target object."""
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
        chain = functools.update_wrapper(functools.partial(fn, chain), details.original)
    details.chain = chain


def _apply_patch(
    target: ModuleType | type,
    wrapped,
    wrapper: PatchWrapper,
    priority: int,
    property_type: str,
) -> Callable:
    """Apply the patch."""
    name = _find_attr_name(target, wrapped)

    is_property = isinstance(wrapped, property)
    if is_property:
        wrapped_func = getattr(wrapped, property_type)
        if wrapped_func is None:
            raise AttributeError(f"Property '{name}' has no {property_type} defined.")
    else:
        # use __func__ if available
        wrapped_func = getattr(wrapped, '__func__', wrapped)

    key = (cast(type, target), name, property_type) if is_property else (target, name)
    with _lock:
        details = _registry.get(key)
        if details:
            details.wrappers.append((priority, wrapper))
            details.wrappers.sort(key=lambda item: item[0])

            _rebuild_chain(details)
        else:
            # create and install dispatcher
            details = _DispatcherDetails(
                chain=functools.update_wrapper(functools.partial(wrapper, wrapped_func), wrapped_func),
                original=wrapped_func,
                wrappers=[(priority, wrapper)],
            )
            _registry[key] = details
            dispatcher = cast(
                Callable, functools.update_wrapper(lambda *a, **kw: details.chain(*a, **kw), wrapped_func)
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
            elif isinstance(wrapped, staticmethod):
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
    return lambda wrapper: _apply_patch(target, wrapped, wrapper, priority, property_type)


def patch_classmethod(
    target: type[C], wrapped: Callable[P, R] | classmethod[C, P, R], priority: int = 0, property_type: str = 'fget'
) -> Callable[[ClassMethodPatchWrapper[C, P, R]], ClassMethodPatchWrapper[C, P, R]]:
    return lambda wrapper: _apply_patch(target, wrapped, wrapper, priority, property_type)


def unpatch(
    target: ModuleType | type[C],
    wrapped: Callable[P, R] | property | staticmethod[P, R] | classmethod[C, P, R],
    wrapper: PatchWrapper[P, R] | ClassMethodPatchWrapper[C, P, R],
    property_type: str = 'fget',
) -> bool:
    name = _find_attr_name(target, wrapped)

    is_property = isinstance(wrapped, property)
    key = (cast(type, target), name, property_type) if is_property else (target, name)

    with _lock:
        details = _registry.get(key)
        if details is None:
            return False

        old_count = len(details.wrappers)
        details.wrappers = [(priority, fn) for priority, fn in details.wrappers if fn is not wrapper]
        if len(details.wrappers) == old_count:
            return False

        _rebuild_chain(details)
    return True


def unpatch_module(module: str) -> None:
    with _lock:
        for details in _registry.values():
            old_count = len(details.wrappers)
            details.wrappers = [(priority, fn) for priority, fn in details.wrappers if fn.__module__ != module]
            if len(details.wrappers) == old_count:
                return

            _rebuild_chain(details)


def enable(api: PluginApi):
    """Enable plugin."""
    pass


def disable():
    """Disable plugin."""
    pass
