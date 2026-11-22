from ui.workers.review.content_check import ContentCheckWorkerMixin
from ui.workers.review.helpers import ReviewHelpersMixin
from ui.workers.review.illust_toc import IllustTocReviewMixin
from ui.workers.review.missing_toc import MissingTocWorkerMixin
from ui.workers.review.ocr_anomalies import OcrAnomaliesMixin
from ui.workers.review.structure_check import StructureCheckWorkerMixin
from ui.workers.review.toc_reconcile import TocReconcileWorkerMixin


class ReviewMixin(
    ReviewHelpersMixin,
    OcrAnomaliesMixin,
    IllustTocReviewMixin,
    TocReconcileWorkerMixin,
    MissingTocWorkerMixin,
    ContentCheckWorkerMixin,
    StructureCheckWorkerMixin,
):
    pass


__all__ = ["ReviewMixin"]
