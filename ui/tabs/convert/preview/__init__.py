from ui.tabs.convert.preview.actions import PreviewActionsMixin
from ui.tabs.convert.preview.cache import PreviewCacheMixin
from ui.tabs.convert.preview.viewer import PreviewViewerMixin


class PreviewMixin(PreviewCacheMixin, PreviewViewerMixin, PreviewActionsMixin):
    pass


__all__ = ["PreviewMixin"]
