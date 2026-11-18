# Monkey

![Latest Version](https://img.shields.io/github/v/tag/mbeckh/picard-plugin-monkey?sort=semver&filter=v*&style=flat-square&label=latest)
![Supports](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmbeckh%2Fpicard-plugin-monkey%2Frefs%2Fheads%2Fmain%2Fpyproject.toml&search=dependencies%5Cs*%3D%5Cs*%5C%5B%5B%5E%5D%5D*%22picard%5B%5E%22%5D*(%3E%3D.*%3F)%5B%2C%22%5D&replace=%241&flags=s&style=flat-square&label=picard&color=orange)
![Tested with](https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmbeckh%2Fpicard-plugin-monkey%2Frefs%2Fheads%2Fmain%2Fpyproject.toml&search=dependencies%5Cs*%3D%5Cs*%5C%5B%5B%5E%5D%5D*%22(picard)%5B%5E%22%5D*(%3C%3D.*%3F)%5B%2C%22%5D&replace=%241%242&flags=s&style=flat-square&label=tested+with&color=green)

A plugin for [MusicBrainz Picard](https://picard.musicbrainz.org) to allow
monkey patching the same function from different plugins using function
decorators.

## Installation and Basic Usage

Using Monkey from a plugin requires two steps:

First it is required to install Monkey (this repository) as a plugin in Picard.

Second, the using plugin must add the Monkey _API_ to its code base. To do this,
copy the file [monkey.py] to your plugin.

It is recommended to regularly check the source for updates e.g. using a worker
or a sync action. Loading a plugin will fail if it is not compatible with the
installed Monkey plugin. Compatibility requires the same API major version and
Monkey plugin having a minor version not less than that of the client.

Then from your module, do a regular import and use the decorators:

```python
from . import monkey

@monkey.patch(SomeClass, SomeClass.somemethod):
def my_wrapper(wrapped, self): ...
```

**The wrappers themselves should be regular functions in module scope.** To be
frank, I have not yet tested what happens if you supply a class method.

> [!WARNING] If you are monkey patching Picard, even a minor update can break
> your plugin.

## Documentation

### @patch

```python
def patch[C, **P, R](
        target: ModuleType | type[C],
        wrapped: Callable[P, R] | property | staticmethod[P, R],
        priority: int = 0,
        property_type: str = 'fget',
) -> Callable[[PatchWrapper[P, R]], PatchWrapper[P, R]]
```

Install a wrapper around a function.

Args:

* `target`: The module or type to patch.
* `wrapped`: The function or property to patch.
* `priority`: Wrapper execution order from highest on the outside to lowest on
  the inside (defaults to 0).
* `property_type`: Property accessor to patch (`fget`, `fset` or `fdel`,
  defaults to `fget`).

Raises:

* `AttributeError`: If the target function cannot be found.

### @patch_classmethod

```python
def patch_classmethod[C, **P, R](
    target: type[C],
    wrapped: Callable[P, R],
    priority: int = 0,
    property_type: str = 'fget',
) -> Callable[[ClassMethodPatchWrapper[C, P, R]], ClassMethodPatchWrapper[C, P, R]]
```

Install a wrapper around a class method. Same as patch, but class methods
require special handling to account for the class parameter.

Args:

* `target`: The module or type to patch.
* `wrapped`: The function or property to patch.
* `priority`: Wrapper execution order from highest on the outside to lowest on
  the inside (defaults to 0).
* `property_type`: Property accessor to patch (`fget`, `fset` or `fdel`,
  defaults to `fget`).

Raises:

* `AttributeError`: If the target function cannot be found.

### unpatch

```python
def unpatch[C, **P, R](
    target: ModuleType | type[C],
    wrapped: Callable[P, R] | property | staticmethod[P, R],
    wrapper: PatchWrapper[P, R] | ClassMethodPatchWrapper[C, P, R],
    property_type: str = 'fget',
) -> bool
```

Remove a previously installed wrapper.

Args:

* `target`: The module or type that was patched.
* `wrapped`: The patched function, method or property.
* `wrapper`: The wrapper function to remove.
* `property_type`: Property accessor to remove (`fget`, `fset` or `fdel`,
  defaults to `fget`).

Returns:

* True if the wrapper was found and removed.

### unpatch_module

```python
def unpatch_module(module: str) -> None
```

Remove all patches for functions from a module.

Args:

* `module`: The name of the module container the wrapper functions.

## Example

One, admittedly not very useful, example to see how it works is to add some
static text to every task bar message. Put the following code into a plugin to
see how it works.

```python
from picard.i18n import gettext
from picard.ui.mainwindow import MainWindow
from . import monkey


@monkey.patch(MainWindow, MainWindow.set_statusbar_message)
def _my_wrapper(wrapped, self, message, *args, **kwargs):
    translate = kwargs.get('translate', gettext)
    kwargs['translate'] = lambda msg: (translate(msg) if translate else msg) + ' - Kilroy was here'
    wrapped(self, message, *args, **kwargs)
```

## License

The code is released under the Apache License Version 2.0. Please see
[LICENSE](LICENSE) for details and [NOTICE](NOTICE) for the required information
when using picard-plugin-monkey in your own work.
