from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.gemini import list_gemini_models

GEMINI_MODEL_PRESETS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite"
]

class GeminiPanel(QWidget):
    def __init__(self, initial_settings: dict, key_source=None, parent=None):
        super().__init__(parent)
        self._key_source = key_source
        root = QVBoxLayout(self)
        root.setSpacing(8)

        g_cfg = QGroupBox("설정")
        cg = QGridLayout(g_cfg)
        cg.setSpacing(8)

        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        for m in GEMINI_MODEL_PRESETS:
            self.combo_model.addItem(m, m)

        self.btn_fetch_models = QPushButton("모델 조회")
        self.btn_fetch_models.clicked.connect(self._fetch_models)

        model_row = QHBoxLayout()
        model_row.addWidget(self.combo_model, 1)
        model_row.addWidget(self.btn_fetch_models)

        self.spin_rpm = QSpinBox()
        self.spin_rpm.setRange(1, 10000)

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 200)

        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 30)
        self.spin_batch.setSuffix("장")
        self.spin_batch.setValue(4)
        self.spin_batch.setEnabled(True)

        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 1.5)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setDecimals(2)

        self.spin_temp_step = QDoubleSpinBox()
        self.spin_temp_step.setRange(0.0, 0.5)
        self.spin_temp_step.setSingleStep(0.05)
        self.spin_temp_step.setDecimals(2)
        self.spin_temp_step.setPrefix("+")

        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(1, 20)
        self.spin_retries.setSuffix("회")

        cg.addWidget(QLabel("모델"), 0, 0)
        cg.addLayout(model_row, 0, 1, 1, 3)
        cg.addWidget(QLabel("키당 RPM"), 1, 0)
        cg.addWidget(self.spin_rpm, 1, 1)
        cg.addWidget(QLabel("동시 요청"), 1, 2)
        cg.addWidget(self.spin_concurrent, 1, 3)
        cg.addWidget(QLabel("묶음 장수"), 2, 0)
        cg.addWidget(self.spin_batch, 2, 1)
        cg.addWidget(QLabel("시작 온도"), 2, 2)
        cg.addWidget(self.spin_temp, 2, 3)
        cg.addWidget(QLabel("최대 재시도"), 3, 0)
        cg.addWidget(self.spin_retries, 3, 1)
        cg.addWidget(QLabel("누적 온도 증가"), 3, 2)
        cg.addWidget(self.spin_temp_step, 3, 3)
        root.addWidget(g_cfg)

        g_z = QGroupBox("Z-Score")
        zg = QGridLayout(g_z)
        zg.setSpacing(8)

        self.spin_z = QDoubleSpinBox()
        self.spin_z.setRange(1.0, 10.0)
        self.spin_z.setSingleStep(0.1)
        self.spin_z.setDecimals(1)

        self.chk_z_retry = QCheckBox("Z-score 이상 시 자동 재시도")

        self.combo_on_fail = QComboBox()
        self.combo_on_fail.addItem("사용자 확인 창 띄우기 (직접 보고 결정)", "ask")
        self.combo_on_fail.addItem("자동으로 기존 결과 유지", "keep")
        self.combo_on_fail.addItem("자동으로 건너뛰기", "skip")

        zg.addWidget(QLabel("허용 |Z| 기준"), 0, 0)
        zg.addWidget(self.spin_z, 0, 1)
        zg.addWidget(self.chk_z_retry, 0, 2, 1, 2)
        zg.addWidget(QLabel("재시도 후 실패 시"), 1, 0)
        zg.addWidget(self.combo_on_fail, 1, 1, 1, 3)
        root.addWidget(g_z)

        root.addStretch()
        self.set_config(initial_settings)

    def _fetch_models(self):
        keys = self._key_source.keys() if self._key_source is not None else []
        if not keys:
            QMessageBox.warning(self, "안내", "먼저 Gemini API 키를 1개 이상 입력하세요.")
            return
        try:
            models = list_gemini_models(keys[0])
            if not models:
                QMessageBox.information(self, "안내", "사용 가능한 Gemini 모델을 찾지 못했습니다.")
                return
            cur = self.combo_model.currentText().strip()
            self.combo_model.blockSignals(True)
            self.combo_model.clear()
            for m in models:
                self.combo_model.addItem(m, m)
            if cur in models:
                self.combo_model.setCurrentText(cur)
            elif "gemini-3.1-flash-lite" in models:
                self.combo_model.setCurrentText("gemini-3.1-flash-lite")
            self.combo_model.blockSignals(False)
            QMessageBox.information(self, "조회 완료", f"{len(models)}개 모델을 불러왔습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "모델 조회 실패", str(exc))

    def get_config(self) -> dict:
        self.spin_rpm.interpretText()
        self.spin_concurrent.interpretText()
        self.spin_batch.interpretText()
        self.spin_temp.interpretText()
        self.spin_temp_step.interpretText()
        self.spin_retries.interpretText()
        self.spin_z.interpretText()
        return {
            "gemini_model": self.combo_model.currentText().strip() or "gemini-3.1-flash-lite",
            "gemini_rpm": self.spin_rpm.value(),
            "gemini_max_concurrent": self.spin_concurrent.value(),
            "gemini_batch_size": self.spin_batch.value(),
            "gemini_temperature": self.spin_temp.value(),
            "gemini_temp_step": self.spin_temp_step.value(),
            "gemini_max_retries": self.spin_retries.value(),
            "gemini_z_threshold": self.spin_z.value(),
            "gemini_z_retry": self.chk_z_retry.isChecked(),
            "gemini_on_fail_action": self.combo_on_fail.currentData(),
        }

    def set_config(self, cfg: dict):
        self.combo_model.setCurrentText(str(cfg.get("gemini_model", "gemini-3.1-flash-lite")))
        self.spin_rpm.setValue(int(cfg.get("gemini_rpm", 10)))
        self.spin_concurrent.setValue(int(cfg.get("gemini_max_concurrent", 4)))
        self.spin_batch.setValue(int(cfg.get("gemini_batch_size", 4)))
        self.spin_temp.setValue(max(0.0, min(1.5, float(cfg.get("gemini_temperature", 0.1)))))
        self.spin_temp_step.setValue(float(cfg.get("gemini_temp_step", 0.25)))
        self.spin_retries.setValue(int(cfg.get("gemini_max_retries", 3)))
        self.spin_z.setValue(float(cfg.get("gemini_z_threshold", 2.5)))
        self.chk_z_retry.setChecked(bool(cfg.get("gemini_z_retry", False)))
        idx = self.combo_on_fail.findData(cfg.get("gemini_on_fail_action", "ask"))
        if idx >= 0:
            self.combo_on_fail.setCurrentIndex(idx)
