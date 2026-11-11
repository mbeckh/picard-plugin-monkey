# Monkey

A plugin for [MusicBrainz Picard](https://picard.musicbrainz.org) to allow monkey patching the same function from different plugins using function decorators.

## Installation and Basic Usage
Using Monkey from a plugin requires two steps:

First it is required to install Monkey (this repository) as a plugin Picard.

Second, the using plugin must add the [Monkey *API*](https://github.com/mbeckh/picard-plugin-monkey-api) to its code base. To do this, add the API repository as a subtree to your plugin (select the API version as required) in the `monkey` directory.
```shell
git remote add -f monkey-api https://github.com/mbeckh/picard-plugin-monkey-api.git
git subtree --prefix=monkey --gpg-sign --squash -m "Add Monkey API" add monkey-api v1.0.0
```

Then from your module, do a regular import and use the decorators:
```python
from . import monkey

@monkey.patch(SomeClass.somemethod):
def my_wrapper(wrapped, self): ...
```
**The wrappers themselves should be regular functions in module scope.** To be frank, I have not yet tested what happens if you supply a class method.

To get updates or switch to a different branch:
```shell
git subtree --prefix=monkey --gpg-sign --squash -m "Switch to experimental branch of Monkey API" pull monkey-api some-experimental-branch
```

## Documentation
### @patch
```python
def patch(
    wrapped: Callable[P, R] | property | staticmethod,
    priority: int = 0,
    property_type: str = 'fget'
) -> Callable[[PatchWrapper[P, R]], PatchWrapper[P, R]]
```
Install a wrapper around a function.

Args:
* `wrapped`: The function or property to patch.
* `priority`: Wrapper execution order. Higher values execute first (defaults to 0).
* `property_type`: Property accessor to patch (`fget`, `fset` or `fdel`, defaults to `fget`).

Raises:
* `AttributeError`: If the target function cannot be found.

### @patch_classmethod
```python
def patch_classmethod(
    wrapped: Callable[P, R],
    priority: int = 0,
    property_type: str = 'fget',
) -> Callable[[ClassMethodPatchWrapper[C, P, R]], ClassMethodPatchWrapper[C, P, R]]
```
Install a wrapper around a class method. Same as patch, but class methods require special handling to account for the class parameter.

Args:
* `wrapped`: The function or property to patch.
* `priority`: Wrapper execution order. Higher values execute first.
* `property_type`: Property accessor to patch (`fget`, `fset` or `fdel`, defaults to `fget`).

Raises:
* `AttributeError`: If the target function cannot be found.

### unpatch
```python
def unpatch(
    wrapped: Callable[P, R],
    wrapper: PatchWrapper[P, R] | property | staticmethod | ClassMethodPatchWrapper[C, P, R],
    property_type: str = 'fget',
) -> bool
```
Remove a previously installed wrapper.

Args:
* `wrapped`: The patched function, method or property.
* `wrapper`: The wrapper function to remove.
* `property_type`: Property accessor to remove (`fget`, `fset` or `fdel`, defaults to `fget`).

Returns:
* True if the wrapper was found and removed.

## Example
One, admittedly not very useful, example to see how it works is to add some static text to every task bar message. Put the following code into a plugin to see how it works.
```python
from picard.i18n import gettext
from picard.ui.mainwindow import MainWindow
from . import monkey

@monkey.patch(MainWindow.set_statusbar_message)
def _my_wrapper(wrapped, self, message, *args, **kwargs):
    translate = kwargs.get('translate', gettext)
    kwargs['translate'] = lambda msg: (translate(msg) if translate else msg) + ' - Kilroy was here'
    wrapped(self, message, *args, **kwargs)
```

## License

The code is released under the Apache License Version 2.0. Please see [LICENSE](LICENSE) for details and [NOTICE](NOTICE) for the required information when using picard-plugin-monkey in your own work.