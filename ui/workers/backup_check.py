import json
from collections import Counter
from pathlib import Path
from typing import Dict

from PySide6.QtCore import QThread, Signal

from core.export.exporters import load_ocr_backup
from core.vision.image_utils import image_fingerprint, is_blank_image, list_images_in_folder, load_image_rgb
from core.vision.novel_detector import SplitPart
from core.vision.page_pipeline import compute_base_parts, split_illustration_side_crop
from ui.workers.entries import build_source_config, build_source_key


_SETTING_LABELS = {
    "split_enabled": "페이지 분할 사용 여부",
    "split_skip_first": "첫 이미지 분할 제외",
    "split_only_wide": "가로로 긴 이미지에만 분할",
    "split_large_images": "큰 이미지 분할 설정",
    "read_direction": "읽기 방향",
    "remove_text_header": "상단 헤더 제거",
    "header_cut_mode": "상단 자르기 방식",
    "header_top_pct": "상단 자르기 비율",
    "footer_bottom_pct": "하단 자르기 비율",
    "crop_illustrations": "삽화 상단 자르기",
    "trim_enabled": "삽화 여백 제거",
    "trim_top": "위쪽 여백 제거",
    "trim_bottom": "아래쪽 여백 제거",
    "trim_left": "왼쪽 여백 제거",
    "trim_right": "오른쪽 여백 제거",
    "trim_padding": "여백 보존값",
    "white_threshold": "흰색 판정 기준",
    "small_illust_enabled": "작은 삽화 감지",
    "trim_before_illust_detect": "삽화 판정 전 여백 제거",
    "illust_sensitivity": "본문·삽화 판정 민감도",
    "gemini_model": "Gemini OCR 모델",
    "ocr_language": "OCR 언어",
    "ocr_orientation": "OCR 방향",
    "classification_overrides": "페이지별 본문·삽화 판정",
    "illust_trim_overrides": "페이지별 삽화 여백 설정",
    "illust_side_crops": "삽화 좌우 자르기 설정",
    "illust_no_merge": "양면 삽화 자동 병합 설정",
    "no_auto_separate": "자동 세로 분리 해제 설정",
}


class BackupCheckWorker(QThread):
    result = Signal(object)
    progress = Signal(int, int)

    def __init__(self, settings: Dict, backup_json: Path, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.backup_json = Path(backup_json)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _emit(self, state, **values):
        self.result.emit({"state": state, **values})

    def _pipeline_params(self):
        s = self.settings
        return {
            "split_enabled": bool(s.get("split_enabled", True)),
            "split_skip_first": bool(s.get("split_skip_first", True)),
            "split_only_wide": bool(s.get("split_only_wide", True)),
            "split_large_images": bool(s.get("split_large_images", False)),
            "read_direction": str(s.get("read_direction", "RTL")),
            "illust_sensitivity": str(s.get("illust_sensitivity", "normal")),
            "remove_text_header": bool(s.get("remove_text_header", True)),
            "crop_illustrations": bool(s.get("crop_illustrations", False)),
            "header_top_pct": float(s.get("header_top_pct", 6.0)),
            "footer_bottom_pct": float(s.get("footer_bottom_pct", 0.0)),
            "header_cut_mode": str(s.get("header_cut_mode", "auto")),
            "small_illust_enabled": bool(s.get("small_illust_enabled", True)),
            "trim_before_illust_detect": bool(s.get("trim_before_illust_detect", True)),
            "trim_enabled": bool(s.get("trim_enabled", True)),
            "trim_top": bool(s.get("trim_top", True)),
            "trim_bottom": bool(s.get("trim_bottom", True)),
            "trim_left": bool(s.get("trim_left", True)),
            "trim_right": bool(s.get("trim_right", True)),
            "white_threshold": int(s.get("white_threshold", 240)),
            "trim_padding": int(s.get("trim_padding", 1)),
        }

    def _build_current_pages(self, files):
        s = self.settings
        params = self._pipeline_params()
        classification_overrides = s.get("classification_overrides", {}) or {}
        no_merge = s.get("illust_no_merge", {}) or {}
        no_auto_separate = s.get("no_auto_separate", {}) or {}
        side_crops = s.get("illust_side_crops", {}) or {}
        all_pages = []

        for file_index, path in enumerate(files):
            if self._cancelled:
                return None
            source = load_image_rgb(path)
            file_params = dict(params)
            file_params["auto_separate_disabled"] = bool(no_auto_separate.get(path.name, False))
            parts = compute_base_parts(source, file_index == 0, True, file_params)
            resolved = []
            for original_index, part in enumerate(parts):
                fp = image_fingerprint(part.image)
                blank = is_blank_image(part.image)
                override_key = f"{path.name}::{original_index}::{fp}"
                if override_key in classification_overrides:
                    part.is_illustration = bool(classification_overrides[override_key])
                    part.analysis_reason = "사용자 지정 삽화" if part.is_illustration else "사용자 지정 본문"
                part.fingerprint = fp
                part.is_blank = blank
                resolved.append((original_index, part, fp, blank))

            if not bool(s.get("split_large_images", False)) and not no_merge.get(path.name, False) and len(resolved) > 1:
                non_blank = [item for item in resolved if not item[3]]
                if len(non_blank) >= 2 and all(item[1].is_illustration for item in non_blank):
                    fp = image_fingerprint(source)
                    merged = SplitPart(source, "양면 삽화 병합", True, "분리된 양면 삽화 자동 병합", fingerprint=fp, is_blank=is_blank_image(source))
                    override_key = f"{path.name}::0::{fp}"
                    if override_key in classification_overrides:
                        merged.is_illustration = bool(classification_overrides[override_key])
                        merged.analysis_reason = "사용자 지정 삽화" if merged.is_illustration else "사용자 지정 본문"
                    resolved = [(0, merged, fp, bool(merged.is_blank))]

            expanded = []
            for original_index, part, fp, blank in resolved:
                override_key = f"{path.name}::{original_index}::{fp}"
                side_crop = side_crops.get(override_key)
                if part.is_illustration and not blank and side_crop and len(side_crop) == 2 and (float(side_crop[0]) > 0.0 or float(side_crop[1]) > 0.0):
                    source_part = SplitPart(
                        part.image, part.split_note, True, part.analysis_reason,
                        header_cut_applied=part.header_cut_applied,
                        detected_header_cut_y=part.detected_header_cut_y,
                        is_mini_illust=part.is_mini_illust,
                    )
                    split_parts = split_illustration_side_crop(source_part, side_crop=(float(side_crop[0]), float(side_crop[1])), origin_key=override_key)
                    for split_part in split_parts:
                        split_fp = image_fingerprint(split_part.image)
                        split_blank = is_blank_image(split_part.image)
                        expanded.append((split_part, split_fp, split_blank))
                else:
                    expanded.append((part, fp, blank))

            file_pages = []
            for part_index, (part, fp, blank) in enumerate(expanded):
                meta = SplitPart(
                    None, part.split_note, part.is_illustration, part.analysis_reason,
                    header_cut_applied=part.header_cut_applied,
                    detected_header_cut_y=part.detected_header_cut_y,
                    is_mini_illust=part.is_mini_illust,
                    fingerprint=fp,
                    is_blank=blank,
                    side_crop_origin_key=part.side_crop_origin_key,
                    side_crop_applied=part.side_crop_applied,
                )
                file_pages.append((path.name, part_index, meta, fp, blank))
            all_pages.extend(file_pages)
            self.progress.emit(file_index + 1, len(files))
            if hasattr(source, "close"):
                source.close()

        seen_text = set()
        filtered = []
        for item in all_pages:
            _, _, part, fp, blank = item
            if part.is_illustration:
                filtered.append(item)
            elif fp not in seen_text:
                seen_text.add(fp)
                filtered.append(item)
        return filtered

    def _config_differences(self, old_config, current_config):
        if not isinstance(old_config, dict) or not old_config:
            return []
        return [key for key, value in current_config.items() if key in old_config and old_config.get(key) != value]

    @staticmethod
    def _setting_value_text(value, other=None):
        if isinstance(value, bool):
            return "켬" if value else "끔"
        if isinstance(value, dict):
            other = other if isinstance(other, dict) else {}
            changed = sorted(key for key in set(value) | set(other) if value.get(key) != other.get(key))
            suffix = f" · 변경 항목: {', '.join(map(str, changed[:5]))}" if changed else ""
            if len(changed) > 5:
                suffix += f" 외 {len(changed) - 5}개"
            return f"{len(value)}개 항목{suffix}"
        if isinstance(value, list):
            return f"{len(value)}개 항목"
        if isinstance(value, float):
            return f"{value:g}"
        if value is None:
            return "설정 없음"
        return str(value)

    def run(self):
        try:
            if not self.backup_json.is_file():
                self._emit("missing", message="OCR 백업 파일이 없습니다.")
                return
            raw = json.loads(self.backup_json.read_text(encoding="utf-8"))
            if not isinstance(raw, list) or not raw:
                self._emit("invalid", message="백업 파일이 비어 있거나 JSON 형식이 올바르지 않습니다.")
                return
            raw_valid = []
            missing_images = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    page_no = int(item.get("page_no", 0))
                    version = int(item.get("ocr_version", 0))
                except (TypeError, ValueError):
                    continue
                if page_no <= 0 or version < 4 or not str(item.get("source_key", "")):
                    continue
                if item.get("type") == "illustration":
                    rel = str(item.get("image_rel", ""))
                    image_path = (self.backup_json.parent / rel).resolve() if rel else None
                    if image_path is None or not image_path.is_file():
                        missing_images.append(page_no)
                raw_valid.append(item)
            if not raw_valid:
                self._emit("legacy", message="이 백업은 현재 이어하기에 필요한 OCR 백업 형식이 아닙니다. 새 백업을 만들어야 합니다.")
                return
            if missing_images:
                self._emit("invalid", message=f"백업 삽화 이미지 누락: {len(missing_images)}개 (페이지 {', '.join(map(str, missing_images[:12]))})")
                return
            old_entries = load_ocr_backup(self.backup_json)
            old_by_page = {int(entry["page_no"]): entry for entry in old_entries if int(entry.get("page_no", 0)) > 0 and int(entry.get("ocr_version", 0)) >= 4 and entry.get("source_key")}
            input_dir = Path(str(self.settings.get("input_dir", "")))
            files = list_images_in_folder(input_dir)
            if not files:
                self._emit("invalid", message="현재 선택된 원본 폴더에 이미지가 없습니다.")
                return
            current = self._build_current_pages(files)
            if current is None or self._cancelled:
                return

            current_config = build_source_config(self.settings)
            matched = 0
            mismatched_pages = []
            missing_pages = []
            page_reasons = Counter()
            changed_setting_counts = Counter()
            changed_setting_pairs = {}
            legacy_mismatch_pages = []
            for page_no, item in enumerate(current, start=1):
                source_name, part_index, part, fp, blank = item
                if blank:
                    continue
                override_key = f"{source_name}::{part_index}::{fp}"
                trim_override = (self.settings.get("illust_trim_overrides", {}) or {}).get(override_key)
                side_crop = (self.settings.get("illust_side_crops", {}) or {}).get(override_key)
                current_key = build_source_key(self.settings, source_name, part_index, part, trim_override=trim_override, fingerprint=fp, side_crop=side_crop)
                old = old_by_page.get(page_no)
                if old and old.get("source_key") == current_key:
                    matched += 1
                    continue
                if not old:
                    missing_pages.append(page_no)
                    page_reasons["백업에 저장되지 않은 새 페이지"] += 1
                    continue
                mismatched_pages.append(page_no)
                old_config = old.get("source_config") or {}
                snapshot_complete = isinstance(old_config, dict) and all(key in old_config for key in current_config)
                differences = self._config_differences(old_config, current_config)
                for key in differences:
                    changed_setting_counts[_SETTING_LABELS.get(key, key)] += 1
                    old_value = json.dumps(old_config.get(key), ensure_ascii=False, sort_keys=True, default=str)
                    current_value = json.dumps(current_config.get(key), ensure_ascii=False, sort_keys=True, default=str)
                    changed_setting_pairs.setdefault(key, Counter())[(old_value, current_value)] += 1
                metadata_reason = None
                if str(old.get("source_name", "")) != source_name:
                    metadata_reason = "원본 파일명 또는 페이지 순서 변경"
                elif int(old.get("source_part_index", 0)) != int(part_index):
                    metadata_reason = "페이지 분할 결과 또는 분할 순서 변경"
                elif str(old.get("page_fingerprint", "")) != fp:
                    metadata_reason = "원본 이미지 또는 이미지 전처리 결과 변경"
                elif str(old.get("type", "")) != ("illustration" if part.is_illustration else "text"):
                    metadata_reason = "본문·삽화 분류 변경"
                if not snapshot_complete:
                    legacy_mismatch_pages.append(page_no)
                    page_reasons["이전 백업의 설정 스냅샷이 없거나 불완전해 OCR 설정 변경 원인 확인 불가"] += 1
                else:
                    for key in differences:
                        page_reasons[_SETTING_LABELS.get(key, key)] += 1
                if metadata_reason:
                    page_reasons[metadata_reason] += 1
                elif not differences and snapshot_complete:
                    page_reasons["백업 생성 당시 OCR 처리 기준과 현재 기준이 다름"] += 1

            backup_pages = set(old_by_page)
            current_positions = set(range(1, len(current) + 1))
            orphaned = sorted(backup_pages - current_positions)
            reusable = matched
            total_current = sum(1 for item in current if not item[4])
            changed_settings = [name for name, _ in changed_setting_counts.most_common()]
            changed_setting_values = []
            for key, pairs in changed_setting_pairs.items():
                for (old_json, current_json), count in pairs.most_common(3):
                    try:
                        old_value = json.loads(old_json)
                        current_value = json.loads(current_json)
                    except (TypeError, ValueError):
                        old_value, current_value = old_json, current_json
                    changed_setting_values.append({
                        "name": _SETTING_LABELS.get(key, key),
                        "backup_value": self._setting_value_text(old_value, current_value),
                        "current_value": self._setting_value_text(current_value, old_value),
                        "pages": count,
                    })
            self._emit(
                "checked",
                matched=reusable,
                current=total_current,
                backup=len(old_by_page),
                mismatched=mismatched_pages,
                missing=missing_pages,
                orphaned=orphaned,
                legacy_mismatch=legacy_mismatch_pages,
                changed_settings=changed_settings,
                changed_setting_values=changed_setting_values,
                changed_setting_counts=dict(changed_setting_counts),
                reasons=dict(page_reasons),
                old_config_missing=sum(1 for entry in old_by_page.values() if not isinstance(entry.get("source_config"), dict) or not all(key in entry.get("source_config", {}) for key in current_config)),
                settings=current_config,
            )
        except Exception as exc:
            self._emit("error", message=f"백업 설정 검사 실패: {exc}")
