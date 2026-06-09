"""
tests/test_dispense.py
Тесты налива для всех 6 режимов кнопок.
Каждый класс — отдельный тест в GUI.

Логика каждого теста:
  1. Сбросить счётчики HMI
  2. Нажать кнопку (press <id> 1000)
  3. Подождать пока вода нальётся
  4. Прочитать get_counter total/filter/cold(amb)
  5. Прочитать get_pulse с Hydraulic
  6. Сравнить: все значения должны совпасть ± допуск
"""
import time
from tests.test_base import BaseTest, TestResult

# Допуск совпадения мл
TOLERANCE_ML = 150


def _run_dispense_test(test: BaseTest, button_id: int, counter_key: str,
                       label: str) -> TestResult:
    """
    Общая функция для всех dispense-тестов.
    counter_key: 'cold' или 'amb' (для горячей используем 'total')
    """
    err = test._require_hmi()
    if err:
        return err

    target_ml = int(float(test.config.get("target_liters", 1)) * 1000)
    duration_ms = int(test.config.get("press_duration_ms", 1000))
    wait_sec = float(test.config.get("pour_wait_sec", 40))
    use_hydraulic = test.config.get("use_hydraulic", True)
    tolerance = float(test.config.get("tolerance_ml", TOLERANCE_ML))

    test.log(f"[{test.NAME}] btn={button_id}, target={target_ml} ml, wait={wait_sec}s")

    # ── сброс счётчиков ──────────────────────────────────────────────
    test.hmi.reset_counter("total",  0)
    test.hmi.reset_counter("filter", 0)
    test.hmi.reset_counter(counter_key, 0)
    time.sleep(0.5)

    # ── нажать кнопку ────────────────────────────────────────────────
    resp = test.hmi.press(button_id, duration_ms)
    if resp is None:
        return test._fail(f"press {button_id} — no response from HMI")
    test.log(f"  press {button_id} → {resp}")

    # ── ждём налива ──────────────────────────────────────────────────
    test.log(f"  Waiting {wait_sec}s for dispense...")
    time.sleep(wait_sec)

    # ── читаем счётчики ──────────────────────────────────────────────
    total_ml  = test.hmi.get_counter("total")
    filter_ml = test.hmi.get_counter("filter")
    type_ml   = test.hmi.get_counter(counter_key)
    pulse_ml  = test.hydraulic.get_pulse() if (use_hydraulic and test.hydraulic and test.hydraulic.is_connected()) else None

    test.log(f"  total_ml={total_ml}  filter_ml={filter_ml}  {counter_key}_ml={type_ml}  pulse={pulse_ml}")

    data = {
        "button":     button_id,
        "label":      label,
        "target_ml":  target_ml,
        "total_ml":   total_ml,
        "filter_ml":  filter_ml,
        f"{counter_key}_ml": type_ml,
        "pulse_ml":   pulse_ml,
    }

    errors = []

    # проверяем что вообще что-то налилось
    if total_ml is None:
        errors.append("total_ml = None")
    elif total_ml < target_ml - tolerance:
        errors.append(f"total({total_ml:.0f}) < target({target_ml}) - tolerance({tolerance})")

    # filter должен совпасть с total
    if filter_ml is not None and total_ml is not None:
        diff = abs(total_ml - filter_ml)
        if diff > tolerance:
            errors.append(f"total({total_ml:.0f}) vs filter({filter_ml:.0f}) diff={diff:.0f} > {tolerance}")

    # type counter (cold/amb) должен совпасть с total
    if type_ml is not None and total_ml is not None:
        diff = abs(total_ml - type_ml)
        if diff > tolerance:
            errors.append(f"total({total_ml:.0f}) vs {counter_key}({type_ml:.0f}) diff={diff:.0f} > {tolerance}")

    # hydraulic pulse должен совпасть с total
    if pulse_ml is not None and total_ml is not None:
        diff = abs(total_ml - pulse_ml)
        if diff > tolerance:
            errors.append(f"total({total_ml:.0f}) vs pulse({pulse_ml:.0f}) diff={diff:.0f} > {tolerance}")

    if errors:
        return test._fail(" | ".join(errors), data)
    return test._pass(
        f"OK {label}: total={total_ml:.0f}ml filter={filter_ml}ml {counter_key}={type_ml}ml pulse={pulse_ml}ml",
        data
    )


# ════════════════════════════════════════════════════════════════════════
#  6 тестов — по одному на каждую кнопку дозирования
# ════════════════════════════════════════════════════════════════════════

class TestColdGlass(BaseTest):
    NAME        = "Cold Glass (btn 4)"
    DESCRIPTION = "press 4 — COLD GLASS. Сравнивает total/filter/cold_ml/pulse."
    CATEGORY    = "dispense"
    def run(self) -> TestResult:
        return _run_dispense_test(self, 4, "cold", "COLD GLASS")


class TestColdJug(BaseTest):
    NAME        = "Cold Jug (btn 5)"
    DESCRIPTION = "press 5 — COLD JUG. Сравнивает total/filter/cold_ml/pulse."
    CATEGORY    = "dispense"
    def run(self) -> TestResult:
        return _run_dispense_test(self, 5, "cold", "COLD JUG")


class TestAmbGlass(BaseTest):
    NAME        = "Ambient Glass (btn 6)"
    DESCRIPTION = "press 6 — AMBIENT GLASS. Сравнивает total/filter/amb_ml/pulse."
    CATEGORY    = "dispense"
    def run(self) -> TestResult:
        return _run_dispense_test(self, 6, "amb", "AMB GLASS")


class TestAmbJug(BaseTest):
    NAME        = "Ambient Jug (btn 7)"
    DESCRIPTION = "press 7 — AMBIENT JUG. Сравнивает total/filter/amb_ml/pulse."
    CATEGORY    = "dispense"
    def run(self) -> TestResult:
        return _run_dispense_test(self, 7, "amb", "AMB JUG")


class TestHotGlass(BaseTest):
    NAME        = "Hot Glass (btn 1)"
    DESCRIPTION = "press 1 — HOT GLASS. Сравнивает total/filter/pulse."
    CATEGORY    = "dispense"
    def run(self) -> TestResult:
        return _run_dispense_test(self, 1, "total", "HOT GLASS")


class TestHotJug(BaseTest):
    NAME        = "Hot Jug (btn 2)"
    DESCRIPTION = "press 2 — HOT JUG. Сравнивает total/filter/pulse."
    CATEGORY    = "dispense"
    def run(self) -> TestResult:
        return _run_dispense_test(self, 2, "total", "HOT JUG")