from core.gemini.review.base import ReviewBaseMixin
from core.gemini.review.content_review import ContentReviewMixin
from core.gemini.review.illust_toc import IllustTocMixin
from core.gemini.review.missing_toc import MissingTocMixin
from core.gemini.review.structure_audit import StructureAuditMixin
from core.gemini.review.toc_reconcile import TocReconcileMixin


class ReviewMixin(
    ReviewBaseMixin,
    ContentReviewMixin,
    TocReconcileMixin,
    MissingTocMixin,
    StructureAuditMixin,
    IllustTocMixin,
):
    pass


__all__ = ["ReviewMixin"]
