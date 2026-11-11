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
import sys
import threading
from typing import (
    TYPE_CHECKING,
    Protocol,
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


class _Dispatcher(Protocol):
    _mbdd: _DispatcherDetails


_patches: dict[
    str, list[tuple[Callable | property | staticmethod | classmethod, PatchWrapper | ClassMethodPatchWrapper, str]]
] = {}
_patches_lock = threading.Lock()

#
# Apply patches
#


def _find_mod_or_cls_and_name(wrapped):
    """Find object and name for provided function."""
    if isinstance(wrapped, property):
        underlying_func = wrapped.fget or wrapped.fset or wrapped.fdel
    else:
        underlying_func = getattr(wrapped, '__func__', wrapped)

    if not underlying_func:
        raise AttributeError(f"Cannot find {wrapped}.")

    mod_name = getattr(underlying_func, '__module__', None)
    qualname = getattr(underlying_func, '__qualname__', None)
    if not mod_name or not qualname or mod_name not in sys.modules:
        raise AttributeError(f"Cannot find module or qualname for {wrapped}.")

    parts = qualname.split('.')
    current_obj = sys.modules[mod_name]
    for part in parts[:-1]:
        current_obj = getattr(current_obj, part)

    return current_obj, parts[-1]


def _get_dispatcher(fn) -> _Dispatcher | None:
    """Get our dispatcher in the call chain."""
    if hasattr(fn, '_mbdd'):
        return fn
    # try wrapper from functools
    wrapped_inner = getattr(fn, '__wrapped__', None)
    if wrapped_inner:
        return _get_dispatcher(wrapped_inner)
    return None


def _rebuild_chain(mbdd: _DispatcherDetails) -> None:
    """Rebuild wrapper chain."""
    chain = mbdd.original
    for _, fn in mbdd.wrappers:
        chain = functools.update_wrapper(functools.partial(fn, chain), mbdd.original)
    mbdd.chain = chain


def _apply_patch(
    wrapped: Callable[P, R] | property | staticmethod | classmethod,
    wrapper: PatchWrapper,
    priority: int,
    property_type: str,
) -> PatchWrapper[P, R]:
    """Apply the patch."""
    mod_or_cls, name = _find_mod_or_cls_and_name(wrapped)

    if isinstance(wrapped, property):
        wrapped_func: Callable = getattr(wrapped, property_type)
        if wrapped_func is None:
            raise AttributeError(f"Property '{name}' has no {property_type} defined.")
    elif isinstance(wrapped, classmethod):
        wrapped_func: Callable = wrapped.__func__
    else:
        # use __func__ if available
        wrapped_func: Callable = getattr(wrapped, '__func__', wrapped)

    dispatcher = _get_dispatcher(wrapped_func)
    if dispatcher:
        mbdd = cast(_Dispatcher, dispatcher)._mbdd
        mbdd.wrappers.append((priority, wrapper))
        mbdd.wrappers.sort(key=lambda item: item[0])

        _rebuild_chain(mbdd)
    else:
        # create and install dispatcher
        mbdd = _DispatcherDetails(
            chain=functools.update_wrapper(functools.partial(wrapper, wrapped_func), wrapped_func),
            original=wrapped_func,
            wrappers=[(priority, wrapper)],
        )
        dispatcher = functools.update_wrapper(lambda *a, **kw: mbdd.chain(*a, **kw), wrapped_func)
        cast(_Dispatcher, dispatcher)._mbdd = mbdd

        if isinstance(wrapped, property):
            prop = {
                'fget': wrapped.fget,
                'fset': wrapped.fset,
                'fdel': wrapped.fdel,
                'doc': wrapped.__doc__,
            }
            prop[property_type] = dispatcher
            setattr(mod_or_cls, name, property(**prop))
        elif isinstance(wrapped, classmethod) or isinstance(getattr(wrapped, '__self__', None), type):
            setattr(mod_or_cls, name, classmethod(cast(ClassMethodPatchWrapper, dispatcher)))
        elif isinstance(wrapped, staticmethod):
            setattr(mod_or_cls, name, staticmethod(dispatcher))
        else:
            setattr(mod_or_cls, name, dispatcher)
    with _patches_lock:
        patches = _patches[wrapper.__module__]
        if not patches:
            _patches[wrapper.__module__] = patches = []
        patches.append((wrapped, wrapper, property_type))

    return wrapper


def patch(
    wrapped: Callable[P, R] | property | staticmethod, priority: int = 0, property_type: str = 'fget'
) -> Callable[[PatchWrapper[P, R]], PatchWrapper[P, R]]:
    return lambda wrapper: _apply_patch(wrapped, wrapper, priority, property_type)


def patch_classmethod(
    wrapped: Callable[P, R] | classmethod,  # type checking does not see real class method
    priority: int = 0,
    property_type: str = 'fget',
) -> Callable[[ClassMethodPatchWrapper[C, P, R]], ClassMethodPatchWrapper[C, P, R]]:
    return cast(
        Callable[[ClassMethodPatchWrapper[C, P, R]], ClassMethodPatchWrapper[C, P, R]],
        lambda wrapper: _apply_patch(wrapped, wrapper, priority, property_type),
    )


def unpatch(
    wrapped: Callable[P, R] | property | staticmethod | classmethod,
    wrapper: PatchWrapper[P, R] | ClassMethodPatchWrapper[C, P, R],
    property_type: str = 'fget',
) -> bool:
    if isinstance(wrapped, property):
        wrapped_func = getattr(wrapped, property_type)
    else:
        wrapped_func = getattr(wrapped, '__func__', wrapped)

    dispatcher = _get_dispatcher(wrapped_func)
    if dispatcher is None:
        return False

    mbdd = cast(_Dispatcher, dispatcher)._mbdd

    old_count = len(mbdd.wrappers)
    mbdd.wrappers = [(priority, fn) for priority, fn in mbdd.wrappers if fn is not wrapper]
    if len(mbdd.wrappers) == old_count:
        return False

    _rebuild_chain(mbdd)
    return True


def unpatch_module(module: str) -> None:
    with _patches_lock:
        patches = _patches[module]
        if patches:
            for patch in patches:
                unpatch(patch[0], patch[1], patch[2])


#
# Register plugin
#
def enable(api: PluginApi):
    pass


def disable():
    pass
