import unittest

from src.analysis_dashboard import HTML
from src.control_panel_i18n import ZH_CN_TRANSLATIONS, localization_script


class ControlPanelLocalizationTests(unittest.TestCase):
    def test_chinese_catalog_covers_primary_navigation_and_ai_console(self) -> None:
        expected = {
            "Overview": "概览",
            "Media": "媒体",
            "AI Console": "AI 控制台",
            "Preferences": "偏好设置",
            "Generate speech": "生成语音",
        }
        for english, chinese in expected.items():
            self.assertEqual(ZH_CN_TRANSLATIONS[english], chinese)

    def test_localization_script_is_injected_into_dashboard(self) -> None:
        self.assertNotIn("/* CONTROL_PANEL_I18N */", HTML)
        self.assertIn("const CONTROL_PANEL_LOCALE_KEY", HTML)
        self.assertIn('data-locale="zh-CN"', HTML)
        self.assertIn('data-locale="en"', HTML)

    def test_script_contains_utf8_catalog_and_supported_locales(self) -> None:
        script = localization_script()
        self.assertIn('"Overview":"概览"', script)
        self.assertIn("locale !== 'en' && locale !== 'zh-CN'", script)
        self.assertIn("parts.leading + translated + parts.trailing", script)


if __name__ == "__main__":
    unittest.main()
